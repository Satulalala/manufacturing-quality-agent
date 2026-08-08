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
) -> list[dict[str, object]]:
    """Filter records by safe, explicit dimensions."""

    start = _validate_date(start_date, "start_date") if start_date else None
    end = _validate_date(end_date, "end_date") if end_date else None
    if start and end and start > end:
        raise ValueError("start_date cannot be after end_date")

    lines = (
        [line.strip().upper() for line in production_line]
        if isinstance(production_line, list)
        else ([production_line] if production_line else None)
    )

    filtered: list[dict[str, object]] = []
    for record in records:
        timestamp = str(record.get("timestamp", ""))[:10]
        if start and timestamp < start:
            continue
        if end and timestamp > end:
            continue
        if lines and str(record.get("production_line")).strip().upper() not in lines:
            continue
        if vehicle_model and str(record.get("vehicle_model")) != vehicle_model:
            continue
        filtered.append(dict(record))

    return filtered
