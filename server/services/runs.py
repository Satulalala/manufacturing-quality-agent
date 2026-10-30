"""Background execution and replayable SSE events for local Agent runs."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable
from uuid import UUID

from agent.session_store import SessionStore
from agent.workflow import AgentRunCancelled, QualityAgent
from server.services.conversations import ConversationService
from server.services.sources import PROJECT_ROOT, SourceRegistry


LOGGER = logging.getLogger(__name__)
RUN_DB = PROJECT_ROOT / ".cache" / "quality_workbench" / "runs.sqlite3"
ACTIVE_STATUSES = {"queued", "running", "cancelling"}
TERMINAL_STATUSES = {"completed", "needs_input", "failed", "cancelled", "interrupted"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RunManager:
    def __init__(
        self,
        sources: SourceRegistry,
        conversations: ConversationService,
        database_path: str | Path | None = None,
    ) -> None:
        self.sources = sources
        self.conversations = conversations
        self.database_path = Path(database_path or RUN_DB).resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_lock = RLock()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="quality-agent")
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._db_lock, self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    source_ids_json TEXT NOT NULL DEFAULT '[]',
                    submission_id TEXT NOT NULL,
                    question TEXT NOT NULL,
                    status TEXT NOT NULL,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    report_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(runs)").fetchall()}
            if "source_ids_json" not in columns:
                connection.execute("ALTER TABLE runs ADD COLUMN source_ids_json TEXT NOT NULL DEFAULT '[]'")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_runs_session_status ON runs(session_id, status)"
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS run_events (
                    run_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, sequence)
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_run_events_run ON run_events(run_id, sequence)"
            )
            stale = connection.execute(
                "SELECT run_id FROM runs WHERE status IN ('queued', 'running', 'cancelling')"
            ).fetchall()
            now = _utc_now()
            for row in stale:
                connection.execute(
                    "UPDATE runs SET status = 'interrupted', updated_at = ? WHERE run_id = ?",
                    (now, row["run_id"]),
                )
                self._append_event_locked(connection, str(row["run_id"]), "run.interrupted", {"status": "interrupted"})

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        raw = item.pop("report_json", None)
        item["report"] = json.loads(raw) if raw else None
        item["source_ids"] = json.loads(str(item.pop("source_ids_json", "[]") or "[]"))
        item.pop("cancel_requested", None)
        return item

    def _append_event_locked(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        event_type: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        row = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS next FROM run_events WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        sequence = int(row["next"])
        created_at = _utc_now()
        payload = {"type": event_type, "run_id": run_id, "created_at": created_at, **data}
        connection.execute(
            "INSERT INTO run_events(run_id, sequence, event_type, data_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (run_id, sequence, event_type, json.dumps(payload, ensure_ascii=False, allow_nan=False, default=str), created_at),
        )
        return {"id": sequence, "data": payload}

    def _emit(self, run_id: str, event_type: str, data: dict[str, Any]) -> None:
        with self._db_lock, self._connect() as connection:
            self._append_event_locked(connection, run_id, event_type, data)

    def _update(self, run_id: str, *, status: str | None = None, report: dict[str, Any] | None = None) -> None:
        fields = ["updated_at = ?"]
        values: list[Any] = [_utc_now()]
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if report is not None:
            fields.append("report_json = ?")
            values.append(json.dumps(report, ensure_ascii=False, allow_nan=False, default=str))
        values.append(run_id)
        with self._db_lock, self._connect() as connection:
            connection.execute(f"UPDATE runs SET {', '.join(fields)} WHERE run_id = ?", values)

    def get(self, run_id: str) -> dict[str, Any] | None:
        try:
            normalized = str(UUID(str(run_id)))
        except (ValueError, TypeError, AttributeError):
            return None
        with self._db_lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (normalized,)).fetchone()
        return self._decode(row)

    def list_for_session(self, session_id: str, limit: int = 10) -> list[dict[str, Any]]:
        try:
            session_id = str(UUID(str(session_id)))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("会话 ID 格式无效")
        bounded_limit = max(1, min(50, int(limit)))
        with self._db_lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM runs WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
                (session_id, bounded_limit),
            ).fetchall()
        return [item for row in rows if (item := self._decode(row)) is not None]

    def delete_session(
        self,
        session_id: str,
        *,
        detach_comparisons: Callable[[str], set[str]],
    ) -> bool:
        try:
            session_id = str(UUID(str(session_id)))
        except (ValueError, TypeError, AttributeError) as error:
            raise ValueError("会话 ID 格式无效") from error

        with self._db_lock:
            if self.conversations.get_session(session_id) is None:
                return False
            with self._connect() as connection:
                active = connection.execute(
                    "SELECT 1 FROM runs WHERE session_id = ? AND status IN ('queued', 'running', 'cancelling') LIMIT 1",
                    (session_id,),
                ).fetchone()
            if active:
                raise RuntimeError("该会话正在分析，请等待分析结束后再删除")

            preserved_run_ids = detach_comparisons(session_id)
            if not self.conversations.delete_session(session_id):
                return False

            with self._connect() as connection:
                if preserved_run_ids:
                    placeholders = ", ".join("?" for _ in preserved_run_ids)
                    parameters: tuple[Any, ...] = (session_id, *sorted(preserved_run_ids))
                    rows = connection.execute(
                        f"SELECT run_id FROM runs WHERE session_id = ? AND run_id NOT IN ({placeholders})",
                        parameters,
                    ).fetchall()
                    run_ids = [str(row["run_id"]) for row in rows]
                    if run_ids:
                        run_placeholders = ", ".join("?" for _ in run_ids)
                        connection.execute(
                            f"DELETE FROM run_events WHERE run_id IN ({run_placeholders})", run_ids
                        )
                        connection.execute(
                            f"DELETE FROM runs WHERE session_id = ? AND run_id NOT IN ({placeholders})",
                            parameters,
                        )
                else:
                    connection.execute(
                        "DELETE FROM run_events WHERE run_id IN (SELECT run_id FROM runs WHERE session_id = ?)",
                        (session_id,),
                    )
                    connection.execute("DELETE FROM runs WHERE session_id = ?", (session_id,))
            return True

    def start(
        self,
        session_id: str,
        source_id: str,
        question: str,
        submission_id: str,
        use_decision_loop: bool = True,
        source_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        try:
            session_id = str(UUID(str(session_id)))
            submission_id = str(UUID(str(submission_id)))
        except (ValueError, TypeError, AttributeError) as error:
            raise ValueError("会话或提交 ID 格式无效") from error
        question = str(question).strip()
        if not question:
            raise ValueError("问题不能为空")
        session = self.conversations.get_session(session_id)
        if session is None:
            raise KeyError("会话不存在")
        if str(session["source_id"]) != str(source_id):
            raise ValueError("会话绑定的数据源与本次请求不一致")
        from agent.direct_answer import is_direct_question

        direct_only = is_direct_question(question)
        if direct_only:
            selected_source_ids: list[str] = []
            selected_sources = []
        else:
            session_refs = {
                str(item.get("source_id")): str(item.get("data_version"))
                for item in session.get("data_sources", [])
                if isinstance(item, dict)
            }
            requested = source_ids if source_ids is not None else [source_id]
            selected_source_ids = list(dict.fromkeys(str(item) for item in requested))
            if not selected_source_ids:
                raise ValueError("请先为本轮添加至少一个数据文件")
            if len(selected_source_ids) > 8:
                raise ValueError("一次最多分析 8 个数据文件")
            selected_sources = []
            for selected_id in selected_source_ids:
                source = self.sources.get(selected_id)
                if source is None or session_refs.get(selected_id) != (source.data_version if source else None):
                    raise ValueError("本轮所选文件不属于当前会话，或文件版本已不可用")
                selected_sources.append(source)
            if str(session.get("status")) == "waiting_input":
                pending = next(
                    (
                        item for item in self.list_for_session(session_id, 50)
                        if item.get("status") == "needs_input"
                        and isinstance(item.get("report"), dict)
                        and item["report"].get("task") == "cpk"
                    ),
                    None,
                )
                prior_source_ids = pending.get("source_ids", []) if pending else []
                if prior_source_ids and selected_source_ids != prior_source_ids:
                    raise ValueError("请先用原来的数据文件完成当前 Cpk 参数补充，再更换文件")

        existing = self.get(submission_id)
        if existing is not None:
            if existing["session_id"] != session_id or existing["question"] != question or existing.get("source_ids", []) != selected_source_ids:
                raise ValueError("submission_id 已用于另一条请求")
            return existing

        if str(session.get("status")) == "running":
            raise RuntimeError("当前会话已有分析正在运行")

        store = SessionStore()
        prior_submission = store.get_submission(session_id, submission_id)
        if prior_submission and prior_submission.get("status") == "completed":
            report = prior_submission.get("report")
            if isinstance(report, dict) and str(report.get("question", "")).strip() != question:
                raise ValueError("submission_id 已用于另一条请求")
            now = _utc_now()
            with self._db_lock, self._connect() as connection:
                current_session = self.conversations.get_session(session_id)
                if current_session is None:
                    raise KeyError("会话不存在")
                connection.execute(
                    "INSERT INTO runs(run_id, session_id, source_id, source_ids_json, submission_id, question, status, report_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (submission_id, session_id, source_id, json.dumps(selected_source_ids), submission_id, question, "completed", json.dumps(report, ensure_ascii=False, allow_nan=False, default=str) if isinstance(report, dict) else None, now, now),
                )
                self._append_event_locked(connection, submission_id, "run.completed", {"status": "completed", "report": report})
            return self.get(submission_id) or {}

        now = _utc_now()
        with self._db_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current_session = self.conversations.get_session(session_id)
            if current_session is None:
                raise KeyError("会话不存在")
            active = connection.execute(
                "SELECT run_id FROM runs WHERE session_id = ? AND status IN ('queued', 'running', 'cancelling') LIMIT 1",
                (session_id,),
            ).fetchone()
            if active:
                raise RuntimeError("该会话已有一轮分析正在运行")
            connection.execute(
                "INSERT INTO runs(run_id, session_id, source_id, source_ids_json, submission_id, question, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?)",
                (submission_id, session_id, source_id, json.dumps(selected_source_ids), submission_id, question, now, now),
            )
            self._append_event_locked(connection, submission_id, "run.started", {"status": "queued", "question": question})
        SessionStore().update_session(session_id, status="running")
        try:
            self._executor.submit(self._execute, submission_id, selected_sources, question, session_id, True)
        except RuntimeError:
            SessionStore().update_session(session_id, status="failed")
            self._update(submission_id, status="failed")
            raise
        return self.get(submission_id) or {}

    def _is_cancel_requested(self, run_id: str) -> bool:
        with self._db_lock, self._connect() as connection:
            row = connection.execute("SELECT cancel_requested FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return bool(row and row["cancel_requested"])

    def _execute(self, run_id: str, selected_sources: list[Any], question: str, session_id: str, use_decision_loop: bool) -> None:
        if self._is_cancel_requested(run_id):
            self._update(run_id, status="cancelled")
            self._emit(run_id, "run.cancelled", {"status": "cancelled"})
            return
        self._update(run_id, status="running")
        self._emit(run_id, "run.running", {"status": "running"})

        stage_names = {
            "quality_agent_route": "理解问题与筛选条件",
            "quality_agent_filter_tool": "筛选生产记录",
            "quality_agent_statistics_tool": "计算质量统计",
            "quality_agent_domain_tool": "计算工艺指标",
            "quality_agent_readonly_sql_tool": "查询生产数据",
            "quality_agent_retrieval": "检索知识库",
            "quality_agent_report": "生成结果解释",
        }

        def on_progress(stage: str, event: str, elapsed: float | None) -> None:
            if event == "start" and self._is_cancel_requested(run_id):
                raise AgentRunCancelled("run cancelled between stages")
            self._emit(
                run_id,
                "stage.started" if event == "start" else "stage.completed",
                {
                    "stage": stage,
                    "label": stage_names.get(stage, "处理本轮内容"),
                    "elapsed_ms": elapsed,
                },
            )

        def on_partial_report(report: dict[str, Any]) -> None:
            self._emit(run_id, "statistics.ready", {"report": report})

        session: dict[str, Any] = {}
        try:
            session = self.conversations.get_session(session_id) or {}
            source_id = str(session.get("source_id", ""))
            data_version = str(session.get("data_version", ""))
            records = [record for source in selected_sources for record in source.records]
            agent = QualityAgent(
                records,
                llm_provider="ollama",
                log_dir=PROJECT_ROOT / "logs",
                source_id=source_id,
                data_version=data_version,
                progress_fn=on_progress,
                partial_report_fn=on_partial_report,
                use_decision_loop=use_decision_loop,
            )
            report = agent.answer(question, session_id=session_id, submission_id=run_id)
            if selected_sources:
                source_refs = [
                    {
                        "source_id": source.source_id,
                        "name": source.name,
                        "data_version": source.data_version,
                        "record_count": len(source.records),
                    }
                    for source in selected_sources
                ]
                report["data_sources"] = source_refs
                if isinstance(report.get("data_scope"), dict):
                    report["data_scope"]["datasets"] = source_refs
                    report["data_scope"]["source_record_count"] = len(records)
                SessionStore().complete_submission(session_id, run_id, report)
            report_status = str(report.get("status", "error"))
            run_status = {
                "success": "completed",
                "no_data": "completed",
                "needs_input": "needs_input",
                "cancelled": "cancelled",
            }.get(report_status, "failed")
            self._update(run_id, status=run_status, report=report)
            if run_status == "cancelled":
                self._emit(run_id, "run.cancelled", {"status": run_status, "report": report})
            elif run_status in {"completed", "needs_input"}:
                self._emit(run_id, "message.completed", {"report": report})
                self._emit(run_id, "run.completed", {"status": run_status, "report": report})
            else:
                self._emit(run_id, "run.failed", {"status": run_status, "report": report})
        except Exception as error:
            LOGGER.exception("Quality Agent run %s failed", run_id)
            cancelled = self._is_cancel_requested(run_id)
            session = self.conversations.get_session(session_id) or {}
            report = {
                "status": "cancelled" if cancelled else "error",
                "question": question,
                "summary": "本轮分析已停止，未完成的统计不作为分析结果。" if cancelled else "本轮分析遇到内部错误，请重试。",
                "explanation": "",
                "error_type": type(error).__name__,
                "run_id": run_id,
                "source_id": str(session.get("source_id", "")),
                "data_version": str(session.get("data_version", "")),
                "data_sources": [
                    {"source_id": source.source_id, "name": source.name, "data_version": source.data_version, "record_count": len(source.records)}
                    for source in selected_sources
                ],
            }
            status = "cancelled" if cancelled or isinstance(error, AgentRunCancelled) else "failed"
            try:
                store = SessionStore()
                store.update_state(
                    session_id,
                    messages=[{"role": "assistant", "content": report["summary"]}],
                    reports=[report],
                    status=status,
                )
                store.update_session(session_id, last_question=question, status=status)
            except Exception:
                LOGGER.exception("Could not persist failed run %s to its conversation", run_id)
            self._update(run_id, status=status, report=report)
            self._emit(run_id, "run.cancelled" if status == "cancelled" else "run.failed", {"status": status, "report": report})

    def cancel(self, run_id: str) -> dict[str, Any] | None:
        run = self.get(run_id)
        if run is None:
            return None
        if run["status"] in TERMINAL_STATUSES:
            return run
        with self._db_lock, self._connect() as connection:
            connection.execute(
                "UPDATE runs SET status = 'cancelling', cancel_requested = 1, updated_at = ? WHERE run_id = ? AND status IN ('queued', 'running', 'cancelling')",
                (_utc_now(), str(run["run_id"])),
            )
            self._append_event_locked(connection, str(run["run_id"]), "run.cancelling", {"status": "cancelling"})
        return self.get(run_id)

    def events_after(self, run_id: str, sequence: int) -> list[dict[str, Any]]:
        with self._db_lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT sequence, data_json FROM run_events WHERE run_id = ? AND sequence > ? ORDER BY sequence LIMIT 500",
                (run_id, sequence),
            ).fetchall()
        return [{"id": int(row["sequence"]), "data": json.loads(row["data_json"])} for row in rows]

    def event_bounds(self, run_id: str) -> tuple[int, int]:
        with self._db_lock, self._connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(MIN(sequence), 0) AS first, COALESCE(MAX(sequence), 0) AS last FROM run_events WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return int(row["first"]), int(row["last"])

    def stream(self, run_id: str, after_sequence: int = 0):
        sequence = max(0, int(after_sequence))
        while True:
            first, last = self.event_bounds(run_id)
            if sequence and first and sequence < first - 1:
                snapshot = self.get(run_id)
                sequence = first - 1
                yield {"id": sequence, "data": {"type": "run.snapshot", "run": snapshot}}
            events = self.events_after(run_id, sequence)
            for event in events:
                sequence = event["id"]
                yield event
            run = self.get(run_id)
            if run is None or (run["status"] in TERMINAL_STATUSES and sequence >= last):
                return
            if not events:
                yield None
                time.sleep(0.6)
