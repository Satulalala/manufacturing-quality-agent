"""Local SQLite storage for tool evidence kept outside session checkpoints."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from uuid import uuid4


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULT_DB = _PROJECT_ROOT / ".cache" / "quality_agent_results.sqlite3"
QUALITY_TOOL_VERSION = "1"


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)


def _scope_hash(data_version: str, filters: dict[str, object], tool: str, tool_version: str) -> str:
    return hashlib.sha256(_json({
        "data_version": data_version,
        "filters": filters,
        "tool": tool,
        "tool_version": tool_version,
    }).encode("utf-8")).hexdigest()


def evidence_staleness(
    reference: dict[str, object],
    *,
    data_version: str,
    filters: dict[str, object],
    tool_version: str = QUALITY_TOOL_VERSION,
) -> str | None:
    """Return why a reference cannot answer the current scope, or None if current."""

    if reference.get("status") != "success":
        return "not_successful"
    if reference.get("data_version") != data_version:
        return "data_version_changed"
    if reference.get("tool_version") != tool_version:
        return "tool_version_changed"
    stored_filters = reference.get("filters")
    if not isinstance(stored_filters, dict) or _json(stored_filters) != _json(filters):
        return "scope_changed"
    return None


class ResultStore:
    """Persist bounded tool outputs and expose opaque, session-scoped references."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or DEFAULT_RESULT_DB).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS evidence_results (
                    evidence_id TEXT PRIMARY KEY,
                    session_id TEXT,
                    run_id TEXT NOT NULL,
                    tool_call_id TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    tool_version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    filters_json TEXT NOT NULL,
                    data_version TEXT NOT NULL,
                    scope_hash TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_evidence_session ON evidence_results(session_id, created_at)"
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def save_observation(
        self,
        observation: dict[str, object],
        *,
        session_id: str | None,
        run_id: str,
        filters: dict[str, object],
        data_version: str,
    ) -> dict[str, object] | None:
        tool = observation.get("tool")
        tool_call_id = observation.get("tool_call_id")
        status = observation.get("status")
        if not all(isinstance(value, str) and value for value in (tool, tool_call_id, status)):
            return None
        result = observation.get("result")
        result_json = _json(result) if isinstance(result, dict) else None
        error = str(observation.get("error", ""))[:500] or None
        evidence_id = str(uuid4())
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO evidence_results
                   (evidence_id, session_id, run_id, tool_call_id, tool, tool_version, status,
                    arguments_json, filters_json, data_version, scope_hash, result_json, error, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    evidence_id,
                    session_id,
                    run_id,
                    tool_call_id,
                    tool,
                    QUALITY_TOOL_VERSION,
                    status,
                    _json(observation.get("arguments", {})),
                    _json(filters),
                    data_version,
                    _scope_hash(data_version, filters, tool, QUALITY_TOOL_VERSION),
                    result_json,
                    error,
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                ),
            )
        summary = ""
        if isinstance(result, dict):
            summary = str(result.get("evidence") or result.get("summary") or result.get("status") or "工具返回结果")
            baseline = result.get("baseline")
            if isinstance(baseline, dict) and "total_count" in baseline:
                summary = (
                    f"样本 {baseline.get('total_count', 0)} 条；缺陷 {baseline.get('defect_count', 0)} 条；"
                    f"不良率 {baseline.get('defect_rate_percent', 0)}%"
                )
        return {
            "evidence_id": evidence_id,
            "tool": tool,
            "tool_call_id": tool_call_id,
            "tool_version": QUALITY_TOOL_VERSION,
            "status": status,
            "summary": summary[:300],
            "data_version": data_version,
            "filters": json.loads(_json(filters)),
            "scope_hash": _scope_hash(data_version, filters, tool, QUALITY_TOOL_VERSION),
        }

    def get(self, evidence_id: str, *, session_id: str | None = None) -> dict[str, object] | None:
        query = "SELECT * FROM evidence_results WHERE evidence_id = ?"
        params: tuple[object, ...] = (str(evidence_id),)
        if session_id is not None:
            query += " AND session_id = ?"
            params += (str(session_id),)
        with self._connect() as connection:
            row = connection.execute(query, params).fetchone()
        if row is None:
            return None
        value = dict(row)
        value["arguments"] = json.loads(value.pop("arguments_json"))
        value["filters"] = json.loads(value.pop("filters_json"))
        result_json = value.pop("result_json")
        value["result"] = json.loads(result_json) if result_json else None
        return value
