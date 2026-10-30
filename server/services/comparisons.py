"""Persisted comparisons that execute each selected data source independently."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterator
from uuid import UUID, uuid5

from server.services.conversations import ConversationService
from server.services.runs import ACTIVE_STATUSES, RunManager
from server.services.sources import PROJECT_ROOT, SourceRegistry


COMPARISON_DB = PROJECT_ROOT / ".cache" / "quality_workbench" / "comparisons.sqlite3"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ComparisonService:
    def __init__(
        self,
        sources: SourceRegistry,
        conversations: ConversationService,
        runs: RunManager,
        database_path: str | Path | None = None,
    ) -> None:
        self.sources = sources
        self.conversations = conversations
        self.runs = runs
        self.database_path = Path(database_path or COMPARISON_DB).resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS comparisons (
                    comparison_id TEXT PRIMARY KEY,
                    question TEXT NOT NULL,
                    source_ids_json TEXT NOT NULL,
                    parent_session_id TEXT NOT NULL DEFAULT '',
                    session_ids_json TEXT NOT NULL,
                    run_ids_json TEXT NOT NULL,
                    use_decision_loop INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(comparisons)").fetchall()}
            if "parent_session_id" not in columns:
                connection.execute("ALTER TABLE comparisons ADD COLUMN parent_session_id TEXT NOT NULL DEFAULT ''")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def create(
        self,
        comparison_id: str,
        question: str,
        source_ids: list[str],
        *,
        session_ids: dict[str, str] | None = None,
        parent_session_id: str | None = None,
        use_decision_loop: bool = True,
    ) -> dict[str, Any]:
        try:
            comparison_id = str(UUID(str(comparison_id)))
        except (ValueError, TypeError, AttributeError) as error:
            raise ValueError("比较 ID 格式无效") from error
        question = question.strip()
        if not question:
            raise ValueError("比较问题不能为空")
        normalized_sources = list(dict.fromkeys(str(item) for item in source_ids))
        if not 2 <= len(normalized_sources) <= 8:
            raise ValueError("一次比较需要选择 2 至 8 个数据源")
        source_objects = []
        for source_id in normalized_sources:
            source = self.sources.get(source_id)
            if source is None:
                raise KeyError(f"数据源不存在：{source_id}")
            source_objects.append(source)

        parent_session_id = str(parent_session_id or "").strip()
        parent_session = None
        if parent_session_id:
            try:
                parent_session_id = str(UUID(parent_session_id))
            except (ValueError, TypeError, AttributeError) as error:
                raise ValueError("主会话 ID 格式无效") from error
            parent_session = self.conversations.get_session(parent_session_id)
            if parent_session is None:
                raise KeyError("主会话不存在")
            allowed = {
                str(item.get("source_id")): str(item.get("data_version"))
                for item in parent_session.get("data_sources", [])
                if isinstance(item, dict)
            }
            if any(allowed.get(source.source_id) != source.data_version for source in source_objects):
                raise ValueError("参与比较的文件必须先加入当前会话")

        with self._lock:
            existing = self._find(comparison_id)
            if existing:
                stored_sources = json.loads(str(existing["source_ids_json"]))
                stored_parent = str(existing.get("parent_session_id", ""))
                if str(existing["question"]) != question or stored_sources != normalized_sources or stored_parent != parent_session_id:
                    raise ValueError("comparison_id 已用于另一条比较")
                chosen_sessions = json.loads(str(existing["session_ids_json"]))
                run_ids = json.loads(str(existing["run_ids_json"]))
                loop_enabled = True
            else:
                if parent_session and str(parent_session.get("status")) == "running":
                    raise RuntimeError("当前会话已有分析正在运行")
                supplied_sessions = session_ids or {}
                chosen_sessions: dict[str, str] = {}
                run_ids: dict[str, str] = {}
                for source in source_objects:
                    provided = supplied_sessions.get(source.source_id)
                    if provided:
                        session = self.conversations.get_session(str(provided))
                        if session is None:
                            raise KeyError("用于继续比较的会话不存在")
                        if session["source_id"] != source.source_id or session["data_version"] != source.data_version:
                            raise ValueError("比较会话与当前数据版本不匹配，请新建比较")
                        chosen_sessions[source.source_id] = str(session["session_id"])
                    else:
                        created = self.conversations.create_session(source, question[:80])
                        chosen_sessions[source.source_id] = str(created["session_id"])
                    run_ids[source.source_id] = str(uuid5(UUID(comparison_id), source.source_id))
                now = _now()
                loop_enabled = True
                with self._connect() as connection:
                    connection.execute(
                        "INSERT INTO comparisons(comparison_id, question, source_ids_json, parent_session_id, session_ids_json, run_ids_json, use_decision_loop, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            comparison_id,
                            question,
                            json.dumps(normalized_sources),
                            parent_session_id,
                            json.dumps(chosen_sessions),
                            json.dumps(run_ids),
                            int(loop_enabled),
                            now,
                            now,
                        ),
                    )

            if parent_session_id:
                self._ensure_parent_question(parent_session_id, comparison_id, question)

            # Child runs are idempotent, so a retry after a lost HTTP response
            # safely reconnects to the same per-source work.
            for source in source_objects:
                self.runs.start(
                    chosen_sessions[source.source_id],
                    source.source_id,
                    question,
                    run_ids[source.source_id],
                    loop_enabled,
                )
        return self.get(comparison_id) or {}

    def _ensure_parent_question(self, session_id: str, comparison_id: str, question: str) -> None:
        store = self.conversations.store
        submission = store.get_submission(session_id, comparison_id)
        if submission and submission.get("status") == "completed":
            return
        if submission is None:
            store.claim_submission(session_id, comparison_id)
        state = store.get_state(session_id)
        messages = state.get("messages", [])
        already_added = isinstance(messages, list) and any(
            isinstance(item, dict) and item.get("comparison_id") == comparison_id
            for item in messages
        )
        if not already_added:
            store.update_state(
                session_id,
                messages=[{"role": "user", "content": question, "comparison_id": comparison_id}],
                status="running",
            )
        store.update_session(session_id, last_question=question, status="running")

    def _find(self, comparison_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM comparisons WHERE comparison_id = ?", (comparison_id,)
            ).fetchone()
        return dict(row) if row else None

    def get(self, comparison_id: str) -> dict[str, Any] | None:
        try:
            normalized = str(UUID(str(comparison_id)))
        except (ValueError, TypeError, AttributeError):
            return None
        row = self._find(normalized)
        if row is None:
            return None
        source_ids = json.loads(str(row["source_ids_json"]))
        parent_session_id = str(row["parent_session_id"] or "")
        session_ids = json.loads(str(row["session_ids_json"]))
        run_ids = json.loads(str(row["run_ids_json"]))
        children = []
        updated_at_values = [str(row["updated_at"])]
        for source_id in source_ids:
            source = self.sources.get(source_id)
            run = self.runs.get(run_ids.get(source_id, ""))
            run_updated_at = run.get("updated_at") if run else None
            if run_updated_at:
                updated_at_values.append(str(run_updated_at))
            children.append(
                {
                    "source_id": source_id,
                    "source_name": source.name if source else "数据源已移除",
                    "session_id": session_ids.get(source_id, ""),
                    "run_id": run_ids.get(source_id, ""),
                    "status": run["status"] if run else "not_started",
                    "report": run.get("report") if run else None,
                }
            )
        statuses = [str(child["status"]) for child in children]
        if any(status in ACTIVE_STATUSES for status in statuses) or "not_started" in statuses:
            status = "running"
        elif "interrupted" in statuses:
            status = "interrupted"
        elif "failed" in statuses:
            status = "failed"
        elif "cancelled" in statuses:
            status = "cancelled"
        elif "needs_input" in statuses:
            status = "needs_input"
        else:
            status = "completed"
        result = {
            "comparison_id": normalized,
            "question": str(row["question"]),
            "source_ids": source_ids,
            "parent_session_id": parent_session_id or None,
            "status": status,
            "created_at": str(row["created_at"]),
            "updated_at": max(updated_at_values),
            "children": children,
        }
        if parent_session_id and status not in ACTIVE_STATUSES and "not_started" not in statuses:
            self._sync_parent_result(result)
        return result

    def _sync_parent_result(self, comparison: dict[str, Any]) -> None:
        session_id = str(comparison.get("parent_session_id") or "")
        if not session_id:
            return
        store = self.conversations.store
        with self._lock:
            submission = store.get_submission(session_id, str(comparison["comparison_id"]))
            if submission and submission.get("status") == "completed":
                return
            state = store.get_state(session_id)
            reports = state.get("reports", [])
            existing = next(
                (
                    item for item in reports
                    if isinstance(item, dict) and item.get("comparison_id") == comparison["comparison_id"]
                ),
                None,
            ) if isinstance(reports, list) else None
            if isinstance(existing, dict):
                store.complete_submission(session_id, str(comparison["comparison_id"]), existing)
                return

            parent = self.conversations.get_session(session_id) or {}
            refs = []
            for child in comparison.get("children", []):
                source = self.sources.get(str(child.get("source_id", "")))
                child_report = child.get("report") if isinstance(child.get("report"), dict) else {}
                refs.append({
                    "source_id": str(child.get("source_id", "")),
                    "name": str(child.get("source_name", "数据文件")),
                    "data_version": source.data_version if source else "",
                    "record_count": len(source.records) if source else 0,
                })
            child_reports = [
                child.get("report") for child in comparison.get("children", [])
                if isinstance(child.get("report"), dict)
            ]
            matched_count = sum(
                int((item.get("data_scope") or {}).get("matched_count", 0))
                for item in child_reports
                if isinstance(item.get("data_scope"), dict)
            )
            source_count = sum(ref["record_count"] for ref in refs)
            ranges = [
                str(value)
                for item in child_reports
                for value in (
                    (item.get("data_scope") or {}).get("actual_start_date"),
                    (item.get("data_scope") or {}).get("actual_end_date"),
                )
                if value
            ]
            descriptions = [
                f"{child.get('source_name', '数据文件')}：{(child.get('report') or {}).get('summary', '本文件分析未返回摘要')}"
                for child in comparison.get("children", [])
            ]
            status = str(comparison.get("status", "failed"))
            succeeded = sum(1 for child in comparison.get("children", []) if child.get("status") in {"completed", "needs_input"})
            result_status = "success" if succeeded == len(comparison.get("children", [])) else "cancelled" if status == "cancelled" else "error"
            report: dict[str, Any] = {
                "status": result_status,
                "task": "multi_file_comparison",
                "task_label": "逐文件比较",
                "question": comparison.get("question", ""),
                "summary": f"已完成 {succeeded}/{len(comparison.get('children', []))} 个文件的独立分析。",
                "explanation": "\n\n".join(descriptions),
                "comparison_id": comparison.get("comparison_id"),
                "comparison": comparison,
                "data_sources": refs,
                "data_scope": {
                    "matched_count": matched_count,
                    "source_count": source_count,
                    "source_record_count": source_count,
                    "actual_start_date": min(ranges) if ranges else None,
                    "actual_end_date": max(ranges) if ranges else None,
                    "datasets": refs,
                },
                "run_id": comparison.get("comparison_id"),
                "session_id": session_id,
                "source_id": str(parent.get("source_id", "")),
                "data_version": str(parent.get("data_version", "")),
                "elapsed_ms": 0,
                "comparison_status": status,
            }
            store.update_state(
                session_id,
                messages=[{"role": "assistant", "content": str(report["explanation"]), "comparison_id": str(comparison["comparison_id"])}],
                reports=[report],
                status="completed" if report["status"] == "success" else "cancelled" if report["status"] == "cancelled" else "failed",
            )
            store.update_session(
                session_id,
                status="completed" if report["status"] == "success" else "cancelled" if report["status"] == "cancelled" else "failed",
            )
            store.complete_submission(session_id, str(comparison["comparison_id"]), report)

    def list(self, limit: int = 30) -> list[dict[str, Any]]:
        bounded = max(1, min(100, int(limit)))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT comparison_id FROM comparisons ORDER BY created_at DESC LIMIT ?", (bounded,)
            ).fetchall()
        return [item for row in rows if (item := self.get(str(row["comparison_id"]))) is not None]

    def detach_session(self, session_id: str) -> set[str]:
        """Keep comparison reports while removing their link to a deleted conversation."""
        preserved_run_ids: set[str] = set()
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT comparison_id, parent_session_id, session_ids_json, run_ids_json FROM comparisons"
            ).fetchall()
            for row in rows:
                session_ids = json.loads(str(row["session_ids_json"]))
                run_ids = json.loads(str(row["run_ids_json"]))
                changed = False
                if str(row["parent_session_id"] or "") == session_id:
                    connection.execute(
                        "UPDATE comparisons SET parent_session_id = '' WHERE comparison_id = ?",
                        (row["comparison_id"],),
                    )
                for source_id, child_session_id in session_ids.items():
                    if str(child_session_id) == session_id:
                        session_ids[source_id] = ""
                        run_id = run_ids.get(source_id)
                        if run_id:
                            preserved_run_ids.add(str(run_id))
                        changed = True
                if changed:
                    connection.execute(
                        "UPDATE comparisons SET session_ids_json = ? WHERE comparison_id = ?",
                        (json.dumps(session_ids), row["comparison_id"]),
                    )
        return preserved_run_ids

    def delete_session(self, session_id: str) -> bool:
        # Comparison creation also takes this lock before starting its child runs.
        # Keep the same lock order here to avoid races with a new comparison.
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT comparison_id FROM comparisons WHERE parent_session_id = ?",
                    (str(session_id),),
                ).fetchall()
            if any((comparison := self.get(str(row["comparison_id"]))) and comparison["status"] == "running" for row in rows):
                raise RuntimeError("该会话的多文件比较仍在运行，请等待结束后再删除")
            return self.runs.delete_session(session_id, detach_comparisons=self.detach_session)

    def cancel(self, comparison_id: str) -> dict[str, Any] | None:
        comparison = self.get(comparison_id)
        if comparison is None:
            return None
        for child in comparison["children"]:
            if child["status"] in ACTIVE_STATUSES:
                self.runs.cancel(child["run_id"])
        return self.get(comparison_id)
