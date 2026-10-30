"""SQLite-backed conversation metadata and JSON session state."""

from __future__ import annotations

import os
import operator
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Iterator, TypedDict
from uuid import UUID, uuid4

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SESSION_DB = _PROJECT_ROOT / ".cache" / "quality_agent_sessions.sqlite3"
DEFAULT_CHECKPOINT_DB = _PROJECT_ROOT / ".cache" / "quality_agent_checkpoints.sqlite3"
SESSION_SCHEMA_VERSION = 1
SUBMISSION_STALE_AFTER = timedelta(minutes=5)


class SessionState(TypedDict, total=False):
    messages: Annotated[list[dict[str, str]], operator.add]
    reports: Annotated[list[dict[str, object]], operator.add]
    active_filters: dict[str, object]
    active_query: dict[str, object]
    source_id: str
    data_version: str
    status: str
    schema_version: int
    pending_task: dict[str, object] | None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _identity_node(_: SessionState) -> dict[str, object]:
    return {}


def _session_graph(checkpointer):
    from langgraph.graph import END, START, StateGraph

    builder = StateGraph(SessionState)
    builder.add_node("persist_session_state", _identity_node)
    builder.add_edge(START, "persist_session_state")
    builder.add_edge("persist_session_state", END)
    return builder.compile(checkpointer=checkpointer)


@contextmanager
def _open_checkpointer(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Checkpoints contain only plain JSON-compatible dictionaries and lists.
    # Keep LangGraph's restricted MessagePack deserialization enabled.
    os.environ["LANGGRAPH_STRICT_MSGPACK"] = "true"
    from langgraph.checkpoint.sqlite import SqliteSaver

    with SqliteSaver.from_conn_string(str(path)) as checkpointer:
        checkpointer.setup()
        yield checkpointer


def _thread_config(session_id: str) -> dict[str, object]:
    return {"configurable": {"thread_id": session_id}, "recursion_limit": 20}


class SessionStore:
    """Store session indexes and JSON snapshots in the application-owned SQLite DB."""

    def __init__(
        self,
        metadata_path: str | Path | None = None,
        checkpoint_path: str | Path | None = None,
    ) -> None:
        self.metadata_path = Path(metadata_path or DEFAULT_SESSION_DB).resolve()
        self.checkpoint_path = Path(checkpoint_path or DEFAULT_CHECKPOINT_DB).resolve()
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    data_version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    last_question TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    schema_version INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_updated_at ON sessions(updated_at DESC)"
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS session_sources (
                    session_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    data_version TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    PRIMARY KEY (session_id, source_id)
                )"""
            )
            connection.execute("CREATE TABLE IF NOT EXISTS session_store_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            migrated = connection.execute(
                "SELECT 1 FROM session_store_meta WHERE key = 'session_sources_backfill_v1'"
            ).fetchone()
            if migrated is None:
                connection.execute(
                    """INSERT OR IGNORE INTO session_sources(session_id, source_id, data_version, position)
                       SELECT s.session_id, s.source_id, s.data_version, 0 FROM sessions AS s"""
                )
                connection.execute(
                    "INSERT INTO session_store_meta(key, value) VALUES ('session_sources_backfill_v1', 'done')"
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS session_submissions (
                    session_id TEXT NOT NULL,
                    submission_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    report_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (session_id, submission_id)
                )
                """
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS session_states (
                    session_id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                )"""
            )
        self._migrate_legacy_checkpoints()

    def _migrate_legacy_checkpoints(self) -> None:
        """Import legacy LangGraph state once, preserving the old checkpoint DB."""

        marker = "session_state_json_import_v1"
        with self._connect() as connection:
            if connection.execute("SELECT 1 FROM session_store_meta WHERE key = ?", (marker,)).fetchone():
                return
            session_ids = [
                str(row[0]) for row in connection.execute("SELECT session_id FROM sessions").fetchall()
            ]
        if not self.checkpoint_path.exists():
            with self._connect() as connection:
                connection.execute("INSERT OR REPLACE INTO session_store_meta(key, value) VALUES (?, 'done')", (marker,))
            return

        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
        except ImportError as error:
            raise RuntimeError(
                "发现旧版 LangGraph 会话 checkpoint。请在旧版环境运行会话迁移，或安装 requirements-migrate.txt 后重启。"
            ) from error

        backup_path = self.checkpoint_path.with_name(
            f"{self.checkpoint_path.stem}.pre-loop-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.sqlite3"
        )
        if self.checkpoint_path.stat().st_size:
            source = sqlite3.connect(f"file:{self.checkpoint_path.as_posix()}?mode=ro", uri=True)
            destination = sqlite3.connect(backup_path)
            try:
                source.backup(destination)
            finally:
                destination.close()
                source.close()

        try:
            with SqliteSaver.from_conn_string(str(self.checkpoint_path)) as checkpointer:
                checkpointer.setup()
                graph = _session_graph(checkpointer)
                states = {
                    session_id: dict(snapshot.values)
                    for session_id in session_ids
                    if (snapshot := graph.get_state(_thread_config(session_id)))
                    and snapshot.values
                }
        except Exception as error:
            raise RuntimeError("旧会话状态迁移失败；原 checkpoint 数据库和备份均已保留。") from error

        now = _utc_now()
        with self._connect() as connection:
            for session_id, state in states.items():
                connection.execute(
                    "INSERT OR IGNORE INTO session_states(session_id, state_json, updated_at) VALUES (?, ?, ?)",
                    (session_id, json.dumps(state, ensure_ascii=False, allow_nan=False), now),
                )
            connection.execute("INSERT OR REPLACE INTO session_store_meta(key, value) VALUES (?, 'done')", (marker,))

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.metadata_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _validate_session_id(session_id: str) -> str:
        try:
            return str(UUID(str(session_id)))
        except (ValueError, TypeError, AttributeError) as error:
            raise ValueError("会话 ID 格式无效") from error

    @staticmethod
    def _to_dict(row: sqlite3.Row | None) -> dict[str, object] | None:
        return dict(row) if row is not None else None

    def create_session(
        self,
        source_id: str,
        data_version: str,
        title: str = "新会话",
    ) -> dict[str, object]:
        source_id = str(source_id).strip()
        data_version = str(data_version).strip()
        if not source_id or not data_version:
            raise ValueError("创建会话必须绑定数据源和内容版本")

        session_id = str(uuid4())
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO sessions
                   (session_id, title, source_id, data_version, status, created_at, updated_at, schema_version)
                   VALUES (?, ?, ?, ?, 'active', ?, ?, ?)""",
                (session_id, title.strip()[:80] or "新会话", source_id, data_version, now, now, SESSION_SCHEMA_VERSION),
            )
            connection.execute(
                "INSERT INTO session_sources(session_id, source_id, data_version, position) VALUES (?, ?, ?, 0)",
                (session_id, source_id, data_version),
            )

        initial_state: dict[str, object] = {
            "messages": [],
            "reports": [],
            "active_filters": {},
            "active_query": {},
            "source_id": source_id,
            "data_version": data_version,
            "status": "active",
            "schema_version": SESSION_SCHEMA_VERSION,
        }
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO session_states(session_id, state_json, updated_at) VALUES (?, ?, ?)",
                (session_id, json.dumps(initial_state, ensure_ascii=False), now),
            )
        return self.get_session(session_id) or {}

    def get_session(self, session_id: str) -> dict[str, object] | None:
        session_id = self._validate_session_id(session_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if row is None:
                return None
            result = dict(row)
            refs = connection.execute(
                "SELECT source_id, data_version FROM session_sources WHERE session_id = ? ORDER BY position, source_id",
                (session_id,),
            ).fetchall()
        result["data_sources"] = [dict(item) for item in refs]
        return result

    def delete_session(self, session_id: str) -> bool:
        session_id = self._validate_session_id(session_id)
        if self.get_session(session_id) is None:
            return False

        with self._connect() as connection:
            connection.execute("DELETE FROM session_states WHERE session_id = ?", (session_id,))
            connection.execute("DELETE FROM session_submissions WHERE session_id = ?", (session_id,))
            connection.execute("DELETE FROM session_sources WHERE session_id = ?", (session_id,))
            cursor = connection.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        return cursor.rowcount > 0

    def list_sessions(
        self,
        source_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        limit = max(1, min(200, int(limit)))
        query = "SELECT * FROM sessions"
        parameters: tuple[object, ...] = ()
        if source_id is not None:
            query += " WHERE source_id = ?"
            parameters = (str(source_id),)
        query += " ORDER BY updated_at DESC LIMIT ?"
        parameters += (limit,)
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
            session_ids = [str(row["session_id"]) for row in rows]
            refs_by_session: dict[str, list[dict[str, str]]] = {item: [] for item in session_ids}
            if session_ids:
                placeholders = ",".join("?" for _ in session_ids)
                refs = connection.execute(
                    f"SELECT session_id, source_id, data_version FROM session_sources WHERE session_id IN ({placeholders}) ORDER BY position, source_id",
                    tuple(session_ids),
                ).fetchall()
                for ref in refs:
                    refs_by_session[str(ref["session_id"])].append(
                        {"source_id": str(ref["source_id"]), "data_version": str(ref["data_version"])}
                    )
        result = []
        for row in rows:
            item = dict(row)
            item["data_sources"] = refs_by_session[str(item["session_id"])]
            result.append(item)
        return result

    def set_session_sources(
        self,
        session_id: str,
        data_sources: list[dict[str, str]],
    ) -> dict[str, object] | None:
        session_id = self._validate_session_id(session_id)
        normalized: list[tuple[str, str]] = []
        seen: set[str] = set()
        for item in data_sources:
            source_id = str(item.get("source_id", "")).strip()
            data_version = str(item.get("data_version", "")).strip()
            if not source_id or not data_version:
                raise ValueError("会话文件必须包含数据源和版本")
            if source_id in seen:
                continue
            seen.add(source_id)
            normalized.append((source_id, data_version))
        if len(normalized) > 8:
            raise ValueError("一个会话最多保留 8 个数据文件")

        with self._connect() as connection:
            session = connection.execute(
                "SELECT status FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if session is None:
                return None
            if str(session["status"]) in {"running", "waiting_input"}:
                raise RuntimeError("本轮分析或参数补充完成前不能修改会话文件")
            connection.execute("DELETE FROM session_sources WHERE session_id = ?", (session_id,))
            connection.executemany(
                "INSERT INTO session_sources(session_id, source_id, data_version, position) VALUES (?, ?, ?, ?)",
                [(session_id, source_id, version, index) for index, (source_id, version) in enumerate(normalized)],
            )
            connection.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?", (_utc_now(), session_id)
            )
        return self.get_session(session_id)

    def update_session(
        self,
        session_id: str,
        *,
        title: str | None = None,
        last_question: str | None = None,
        status: str | None = None,
    ) -> dict[str, object] | None:
        session_id = self._validate_session_id(session_id)
        fields: list[str] = []
        values: list[object] = []
        if title is not None:
            fields.append("title = ?")
            values.append(title.strip()[:80] or "新会话")
        if last_question is not None:
            fields.append("last_question = ?")
            values.append(last_question[:1000])
        if status is not None:
            if status not in {"active", "running", "waiting_input", "completed", "failed", "cancelled"}:
                raise ValueError("会话状态无效")
            fields.append("status = ?")
            values.append(status)
        fields.append("updated_at = ?")
        values.append(_utc_now())
        values.append(session_id)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE sessions SET {', '.join(fields)} WHERE session_id = ?", values
            )
        return self.get_session(session_id)

    def get_state(self, session_id: str) -> dict[str, object]:
        session_id = self._validate_session_id(session_id)
        if self.get_session(session_id) is None:
            raise KeyError("会话不存在")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state_json FROM session_states WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row is None:
            return {}
        state = json.loads(str(row["state_json"]))
        return state if isinstance(state, dict) else {}

    def export_legacy_checkpoints(self, target_path: str | Path | None = None) -> dict[str, object]:
        """Export current JSON states to a fresh legacy checkpoint DB for rollback."""
        target = Path(target_path or self.checkpoint_path).resolve()
        if target == self.metadata_path:
            raise ValueError("旧 checkpoint 导出路径不能覆盖会话元数据库")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f"{target.stem}.export-{uuid4().hex}.sqlite3")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT session_id, state_json FROM session_states ORDER BY session_id"
            ).fetchall()
        states = {
            str(row["session_id"]): json.loads(str(row["state_json"]))
            for row in rows
        }

        try:
            with _open_checkpointer(temporary) as checkpointer:
                graph = _session_graph(checkpointer)
                for session_id, state in states.items():
                    graph.invoke(state, _thread_config(session_id))
                mismatches = []
                for session_id, expected in states.items():
                    snapshot = graph.get_state(_thread_config(session_id))
                    if not snapshot or dict(snapshot.values) != expected:
                        mismatches.append(session_id)
                if mismatches:
                    raise RuntimeError(
                        f"旧 checkpoint 回退导出校验失败，会话不匹配：{', '.join(mismatches[:5])}"
                    )

            backup_path = None
            if target.exists() and target.stat().st_size:
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                backup = target.with_name(f"{target.stem}.pre-export-{stamp}-{uuid4().hex[:8]}.sqlite3")
                source_db = sqlite3.connect(f"file:{target.as_posix()}?mode=ro", uri=True)
                backup_db = sqlite3.connect(backup)
                try:
                    source_db.backup(backup_db)
                finally:
                    backup_db.close()
                    source_db.close()
                backup_path = str(backup)
            os.replace(temporary, target)
            return {
                "sessions_exported": len(states),
                "checkpoint_path": str(target),
                "previous_checkpoint_backup": backup_path,
            }
        finally:
            for suffix in ("", "-wal", "-shm"):
                temporary.with_name(temporary.name + suffix).unlink(missing_ok=True)

    def update_state(
        self,
        session_id: str,
        *,
        messages: list[dict[str, str]] | None = None,
        reports: list[dict[str, object]] | None = None,
        active_filters: dict[str, object] | None = None,
        active_query: dict[str, object] | None = None,
        source_id: str | None = None,
        data_version: str | None = None,
        status: str | None = None,
        pending_task: dict[str, object] | None = None,
        clear_pending_task: bool = False,
    ) -> dict[str, object]:
        session_id = self._validate_session_id(session_id)
        session = self.get_session(session_id)
        if session is None:
            raise KeyError("会话不存在")
        if source_id is not None and source_id != session["source_id"]:
            raise ValueError("会话绑定的数据源不可变更")
        if data_version is not None and data_version != session["data_version"]:
            raise ValueError("会话绑定的数据版本不可变更")
        update: dict[str, object] = {}
        if messages is not None:
            update["messages"] = messages
        if reports is not None:
            update["reports"] = reports
        if active_filters is not None:
            update["active_filters"] = active_filters
        if active_query is not None:
            update["active_query"] = active_query
        if source_id is not None:
            update["source_id"] = source_id
        if data_version is not None:
            update["data_version"] = data_version
        if status is not None:
            update["status"] = status
        if pending_task is not None:
            update["pending_task"] = pending_task
        elif clear_pending_task:
            update["pending_task"] = None
        update["schema_version"] = SESSION_SCHEMA_VERSION
        state = self.get_state(session_id)
        for key, value in update.items():
            if key in {"messages", "reports"}:
                existing = state.get(key, [])
                state[key] = [*(existing if isinstance(existing, list) else []), *value]
            else:
                state[key] = value
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO session_states(session_id, state_json, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET state_json = excluded.state_json, updated_at = excluded.updated_at",
                (session_id, json.dumps(state, ensure_ascii=False, allow_nan=False), _utc_now()),
            )
        return state

    def claim_submission(self, session_id: str, submission_id: str) -> dict[str, object]:
        session_id = self._validate_session_id(session_id)
        submission_id = self._validate_session_id(submission_id)
        if self.get_session(session_id) is None:
            raise KeyError("会话不存在")
        now = _utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO session_submissions
                   (session_id, submission_id, status, created_at, updated_at)
                   VALUES (?, ?, 'running', ?, ?)""",
                (session_id, submission_id, now, now),
            )
            row = connection.execute(
                "SELECT * FROM session_submissions WHERE session_id = ? AND submission_id = ?",
                (session_id, submission_id),
            ).fetchone()
        result = self._to_dict(row) or {}
        result["claimed"] = cursor.rowcount == 1
        result["reclaimed"] = False
        if not result["claimed"] and result.get("status") == "running":
            try:
                updated_at = datetime.fromisoformat(str(result.get("updated_at", "")))
                stale = datetime.now(timezone.utc) - updated_at.astimezone(timezone.utc) > SUBMISSION_STALE_AFTER
            except (TypeError, ValueError):
                stale = False
            if stale:
                with self._connect() as connection:
                    reclaimed = connection.execute(
                        """UPDATE session_submissions SET status = 'running', report_json = NULL, updated_at = ?
                           WHERE session_id = ? AND submission_id = ? AND status = 'running' AND updated_at = ?""",
                        (_utc_now(), session_id, submission_id, result.get("updated_at")),
                    )
                result["claimed"] = reclaimed.rowcount == 1
                result["reclaimed"] = result["claimed"]
        if result.get("report_json"):
            result["report"] = json.loads(str(result["report_json"]))
        return result

    def complete_submission(
        self,
        session_id: str,
        submission_id: str,
        report: dict[str, object],
    ) -> None:
        session_id = self._validate_session_id(session_id)
        submission_id = self._validate_session_id(submission_id)
        report_json = json.dumps(report, ensure_ascii=False, allow_nan=False, default=str)
        with self._connect() as connection:
            connection.execute(
                """UPDATE session_submissions
                   SET status = 'completed', report_json = ?, updated_at = ?
                   WHERE session_id = ? AND submission_id = ?""",
                (report_json, _utc_now(), session_id, submission_id),
            )

    def get_submission(self, session_id: str, submission_id: str) -> dict[str, object] | None:
        session_id = self._validate_session_id(session_id)
        submission_id = self._validate_session_id(submission_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM session_submissions WHERE session_id = ? AND submission_id = ?",
                (session_id, submission_id),
            ).fetchone()
        submission = self._to_dict(row)
        if submission and submission.get("report_json"):
            submission["report"] = json.loads(str(submission["report_json"]))
        return submission

