"""Versioned, user-confirmed local preferences, separate from checkpoints and RAG."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from uuid import uuid4


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MEMORY_DB = Path(
    os.environ.get("QUALITY_AGENT_MEMORY_DB", _PROJECT_ROOT / ".cache" / "quality_agent_memory.sqlite3")
).resolve()
_MEMORY_TYPES = {"preference", "specification", "investigation"}


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_current(item: dict[str, object], now: str) -> bool:
    return (
        str(item.get("valid_from", "")) <= now
        and (not item.get("valid_until") or str(item["valid_until"]) > now)
    )


class MemoryStore:
    """Store only confirmed structured memories and preserve their edit history."""

    def __init__(self, path: str | Path | None = None) -> None:
        configured_path = os.environ.get("QUALITY_AGENT_MEMORY_DB")
        self.path = Path(path or configured_path or DEFAULT_MEMORY_DB).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    memory_key TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    scope_json TEXT NOT NULL,
                    unit TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL,
                    confirmed_status TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    valid_from TEXT NOT NULL,
                    valid_until TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_owner_active ON memories(owner_id, status, memory_type)"
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

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, object]:
        item = dict(row)
        item["content"] = json.loads(item.pop("content_json"))
        item["scope"] = json.loads(item.pop("scope_json"))
        return item

    def save_confirmed(
        self,
        *,
        owner_id: str,
        memory_type: str,
        memory_key: str,
        content: dict[str, object],
        source: str,
        scope: dict[str, object] | None = None,
        unit: str = "",
        valid_until: str | None = None,
        confirmed: bool = False,
    ) -> dict[str, object]:
        owner_id, memory_key, source = owner_id.strip(), memory_key.strip(), source.strip()
        if not confirmed:
            raise ValueError("只有用户明确确认的内容可以写入长期记忆")
        if memory_type not in _MEMORY_TYPES or not owner_id or not memory_key or not source:
            raise ValueError("记忆类型、归属、键和来源均不能为空")
        content_json = _json(content)
        scope_json = _json(scope or {})
        if len(content_json.encode("utf-8")) > 4000 or len(scope_json.encode("utf-8")) > 2000:
            raise ValueError("记忆内容或适用范围过长")
        now = _now()
        memory_id = str(uuid4())
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT version FROM memories
                   WHERE owner_id = ? AND memory_type = ? AND memory_key = ? AND scope_json = ?
                   ORDER BY version DESC""",
                (owner_id, memory_type, memory_key, scope_json),
            ).fetchall()
            version = (int(rows[0]["version"]) + 1) if rows else 1
            connection.execute(
                """UPDATE memories SET status = 'superseded', updated_at = ?
                   WHERE owner_id = ? AND memory_type = ? AND memory_key = ? AND scope_json = ?
                     AND status = 'active'""",
                (now, owner_id, memory_type, memory_key, scope_json),
            )
            connection.execute(
                """INSERT INTO memories
                   (memory_id, owner_id, memory_type, memory_key, content_json, scope_json, unit,
                    source, confirmed_status, version, status, valid_from, valid_until, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?, 'active', ?, ?, ?, ?)""",
                (
                    memory_id, owner_id, memory_type, memory_key, content_json, scope_json,
                    unit.strip()[:32], source[:500], version, now, valid_until, now, now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM memories WHERE memory_id = ?", (memory_id,)
            ).fetchone()
        return self._decode(row)

    def list_memories(self, owner_id: str, *, include_history: bool = False) -> list[dict[str, object]]:
        query = "SELECT * FROM memories WHERE owner_id = ?"
        if not include_history:
            query += " AND status = 'active'"
        query += " ORDER BY updated_at DESC"
        with self._connect() as connection:
            rows = connection.execute(query, (owner_id,)).fetchall()
        return [self._decode(row) for row in rows]

    def confirmed_preferences(self, owner_id: str) -> list[dict[str, object]]:
        now = _now()
        return [
            item for item in self.list_memories(owner_id)
            if item["memory_type"] == "preference"
            and item["confirmed_status"] == "confirmed"
            and _is_current(item, now)
        ]

    def find_confirmed(
        self,
        *,
        owner_id: str,
        memory_type: str,
        memory_key: str,
        scope: dict[str, object],
    ) -> list[dict[str, object]]:
        now = _now()
        exact_scope = _json(scope)
        return [
            item for item in self.list_memories(owner_id)
            if item["memory_type"] == memory_type
            and item["memory_key"] == memory_key
            and item["confirmed_status"] == "confirmed"
            and _json(item["scope"]) == exact_scope
            and _is_current(item, now)
        ]

    def get_active(self, memory_id: str, *, owner_id: str) -> dict[str, object] | None:
        for item in self.list_memories(owner_id):
            if item["memory_id"] == memory_id and item["confirmed_status"] == "confirmed":
                return item if _is_current(item, _now()) else None
        return None

    def delete(self, memory_id: str, *, owner_id: str) -> bool:
        now = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE memories SET status = 'deleted', updated_at = ?
                   WHERE memory_id = ? AND owner_id = ? AND status = 'active'""",
                (now, str(memory_id), owner_id),
            )
        return cursor.rowcount == 1
