"""Safe, deterministic data tools for the local quality Agent."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Mapping


Record = Mapping[str, object]


def _validate_date(value: str, field_name: str) -> str:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as error:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format") from error
    return value


def filter_records(
    records: Iterable[Record],
    start_date: str | None = None,
    end_date: str | None = None,
    production_line: str | list[str] | None = None,
    vehicle_model: str | None = None,
    workstation: str | list[str] | None = None,
    shift: str | list[str] | None = None,
    supplier_id: str | list[str] | None = None,
    batch_id: str | list[str] | None = None,
    defect_type: str | list[str] | None = None,
) -> list[dict[str, object]]:
    """Filter records by safe, explicit dimensions."""

    start = _validate_date(start_date, "start_date") if start_date else None
    end = _validate_date(end_date, "end_date") if end_date else None
    if start and end and start > end:
        raise ValueError("start_date cannot be after end_date")

    def normalize_values(value: str | list[str] | None, field_name: str) -> set[str] | None:
        if value is None or value == "":
            return None
        values = value if isinstance(value, list) else [value]
        if not values or len(values) > 32:
            raise ValueError(f"{field_name} must contain between 1 and 32 values")
        normalized: set[str] = set()
        for item in values:
            if not isinstance(item, str):
                raise ValueError(f"{field_name} values must be strings")
            text = item.strip()
            if not text or len(text) > 100 or any(ord(character) < 32 for character in text):
                raise ValueError(f"{field_name} contains an invalid value")
            normalized.add(text.casefold())
        return normalized

    lines = normalize_values(production_line, "production_line")
    workstations = normalize_values(workstation, "workstation")
    shifts = normalize_values(shift, "shift")
    suppliers = normalize_values(supplier_id, "supplier_id")
    batches = normalize_values(batch_id, "batch_id")
    defect_types = normalize_values(defect_type, "defect_type")

    filtered: list[dict[str, object]] = []
    for record in records:
        timestamp = str(record.get("timestamp", ""))[:10]
        if start and timestamp < start:
            continue
        if end and timestamp > end:
            continue
        if lines and str(record.get("production_line", "")).strip().casefold() not in lines:
            continue
        if vehicle_model and str(record.get("vehicle_model")) != vehicle_model:
            continue
        if workstations and str(record.get("workstation", "")).strip().casefold() not in workstations:
            continue
        if shifts and str(record.get("shift", "")).strip().casefold() not in shifts:
            continue
        if suppliers and str(record.get("supplier_id", "")).strip().casefold() not in suppliers:
            continue
        if batches and str(record.get("batch_id", "")).strip().casefold() not in batches:
            continue
        if defect_types and str(record.get("defect_type", "")).strip().casefold() not in defect_types:
            continue
        filtered.append(dict(record))

    return filtered
