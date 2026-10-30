"""Persisted local data sources with a clearly labeled synthetic demo source."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from data.source_manager import records_content_hash, source_from_csv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_DIR = PROJECT_ROOT / ".cache" / "quality_workbench" / "sources"
MAX_CSV_BYTES = 20 * 1024 * 1024
MAX_RECORDS = 500_000


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_filename(value: str) -> str:
    # Do not use any client-supplied path, including Windows paths on POSIX.
    name = str(value or "production-data.csv").replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip(" .")
    if not name:
        name = "production-data.csv"
    if not name.lower().endswith(".csv"):
        name += ".csv"
    return name[:120]


@dataclass(frozen=True)
class DataSource:
    source_id: str
    name: str
    kind: str
    data_version: str
    records: list[dict[str, object]]
    created_at: str

    def public(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "name": self.name,
            "kind": self.kind,
            "record_count": len(self.records),
            "data_version": self.data_version,
        }


class SourceRegistry:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or DEFAULT_SOURCE_DIR).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "index.json"
        self._lock = RLock()
        self._sources: dict[str, DataSource] = {}
        self._load_uploads()
        self._add_demo_datasets()

    def _add_demo_datasets(self) -> None:
        dataset_dir = PROJECT_ROOT / "data" / "datasets"
        for year in range(2022, 2027):
            path = dataset_dir / f"quality_records_{year}.csv"
            content = path.read_bytes()
            _, payload = source_from_csv(path.name, content)
            records = payload["records"]
            if len(records) > MAX_RECORDS:
                raise ValueError(f"内置数据集记录数超过限制：{path.name}")
            source_id = "demo" if year == 2026 else f"demo-{year}"
            cutoff = "（截至 2026-10-18）" if year == 2026 else ""
            self._sources[source_id] = DataSource(
                source_id=source_id,
                name=f"{year} 年整车装配质量数据（合成）{cutoff}",
                kind="demo",
                data_version=records_content_hash(records),
                records=records,
                created_at=f"{year}-01-01T00:00:00+08:00",
            )

    def _load_uploads(self) -> None:
        try:
            entries = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            entries = []
        if not isinstance(entries, list):
            return
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            source_id = str(entry.get("source_id", ""))
            if not re.fullmatch(r"[0-9a-f]{64}", source_id):
                continue
            file_path = (self.root / f"{source_id}.csv").resolve()
            if file_path.parent != self.root:
                continue
            try:
                content = file_path.read_bytes()
                if len(content) > MAX_CSV_BYTES:
                    continue
                parsed_id, payload = source_from_csv(_safe_filename(str(entry.get("name", "data.csv"))), content)
                if parsed_id != source_id or len(payload["records"]) > MAX_RECORDS:
                    continue
                records = payload["records"]
                self._sources[source_id] = DataSource(
                    source_id=source_id,
                    name=_safe_filename(str(entry.get("name", "data.csv"))),
                    kind="upload",
                    data_version=records_content_hash(records),
                    records=records,
                    created_at=str(entry.get("created_at", _utc_now())),
                )
            except (OSError, ValueError, UnicodeDecodeError):
                continue

    def _write_index(self) -> None:
        items = [
            {"source_id": source.source_id, "name": source.name, "created_at": source.created_at}
            for source in self._sources.values()
            if source.kind == "upload"
        ]
        fd, temporary = tempfile.mkstemp(prefix="index-", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(items, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.index_path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def list(self) -> list[dict[str, object]]:
        with self._lock:
            return [source.public() for source in sorted(self._sources.values(), key=lambda item: (item.kind != "demo", item.name.casefold()))]

    def get(self, source_id: str) -> DataSource | None:
        with self._lock:
            return self._sources.get(str(source_id))

    def dimensions(self, source_id: str) -> dict[str, object]:
        source = self.get(source_id)
        if source is None:
            raise KeyError("数据源不存在")

        def unique(field: str) -> list[str]:
            values = {
                str(record.get(field, "")).strip()
                for record in source.records
                if str(record.get(field, "")).strip()
            }
            return sorted(values, key=str.casefold)[:300]

        return {
            "source_id": source.source_id,
            "production_lines": unique("production_line"),
            "vehicle_models": unique("vehicle_model"),
            "workstations": unique("workstation"),
        }

    def add_csv(self, filename: str, content: bytes) -> DataSource:
        if not content:
            raise ValueError("CSV 文件为空")
        if len(content) > MAX_CSV_BYTES:
            raise ValueError("CSV 文件不能超过 20 MB")
        name = _safe_filename(filename)
        source_id, payload = source_from_csv(name, content)
        records = payload["records"]
        if len(records) > MAX_RECORDS:
            raise ValueError(f"记录数不能超过 {MAX_RECORDS:,} 条")
        with self._lock:
            existing = self._sources.get(source_id)
            if existing is not None:
                return existing
            destination = self.root / f"{source_id}.csv"
            fd, temporary = tempfile.mkstemp(prefix=f"{source_id}-", suffix=".tmp", dir=self.root)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, destination)
            finally:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
            source = DataSource(
                source_id=source_id,
                name=name,
                kind="upload",
                data_version=records_content_hash(records),
                records=records,
                created_at=_utc_now(),
            )
            self._sources[source_id] = source
            self._write_index()
            return source
