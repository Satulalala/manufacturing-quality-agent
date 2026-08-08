"""Read-only DuckDB SQL tools for the quality Agent.

The Agent may generate SQL in later milestones, so every statement is checked
against a whitelist before it reaches DuckDB: single SELECT/WITH only, no write
or file-access keywords, and only the whitelisted ``production_records`` view.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import duckdb

from data.demo_data import FIELDNAMES


ALLOWED_TABLES = frozenset({"production_records"})
ALLOWED_COLUMNS = frozenset(FIELDNAMES)
DEFAULT_LIMIT = 5000
MAX_LIMIT = 10000

_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|DETACH|COPY|EXPORT|IMPORT"
    r"|PRAGMA|SET|INSTALL|LOAD|CALL|CHECKPOINT|VACUUM|MERGE|GRANT|REVOKE"
    r"|BEGIN|COMMIT|ROLLBACK|TRUNCATE|USE)\b",
    re.IGNORECASE,
)
_FILE_READERS = re.compile(
    r"\b(read_csv_auto|read_csv|read_parquet|read_json|read_ndjson|read_text"
    r"|read_blob|sqlite_scan|postgres_scan|mysql_scan|glob|parquet_scan|csv_reader)\b",
    re.IGNORECASE,
)
_COMMENT_PATTERN = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)
_CTE_PATTERN = re.compile(r"\bWITH\b\s+(?:RECURSIVE\s+)?(\w+)\s+AS|,\s*(\w+)\s+AS\s*\(", re.IGNORECASE)
_TABLE_REF_PATTERN = re.compile(r"\b(?:FROM|JOIN)\s+([a-zA-Z_][\w.]*)", re.IGNORECASE)


def _validate_date(value: str, field_name: str) -> str:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as error:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format") from error
    return value


def _validate_limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError) as error:
        raise ValueError("limit must be an integer") from error
    if value < 1:
        raise ValueError("limit must be positive")
    return min(value, MAX_LIMIT)


def _sanitize_select(sql: str) -> str:
    """Return a cleaned single-statement SELECT or raise ValueError."""

    cleaned = _COMMENT_PATTERN.sub(" ", sql).strip()
    if not cleaned:
        raise ValueError("SQL statement is empty")
    if ";" in cleaned.rstrip(";"):
        raise ValueError("multiple statements are not allowed")
    cleaned = cleaned.rstrip(";").strip()

    first_keyword = cleaned.split(None, 1)[0].upper()
    if first_keyword not in {"SELECT", "WITH"}:
        raise ValueError("only SELECT statements are allowed")
    if _FORBIDDEN_KEYWORDS.search(cleaned):
        raise ValueError("statement contains forbidden keywords")
    if _FILE_READERS.search(cleaned):
        raise ValueError("direct file or external-database reads are not allowed")

    cte_names = {name for group in _CTE_PATTERN.findall(cleaned) for name in group if name}
    allowed = ALLOWED_TABLES | {name.lower() for name in cte_names}
    for reference in _TABLE_REF_PATTERN.findall(cleaned):
        table = reference.split(".")[-1].lower()
        if table not in allowed:
            raise ValueError(f"table is not whitelisted: {reference}")
    return cleaned


def _connect(csv_path: str | Path) -> duckdb.DuckDBPyConnection:
    path = Path(csv_path)
    if not path.exists():
        raise ValueError(f"CSV file not found: {path}")
    connection = duckdb.connect()
    escaped_path = str(path).replace("'", "''")
    connection.execute(
        f"CREATE VIEW production_records AS SELECT * FROM read_csv_auto('{escaped_path}')"
    )
    return connection


def _execute(connection: duckdb.DuckDBPyConnection, sql: str, params: list[object]) -> dict[str, object]:
    cursor = connection.execute(sql, params)
    columns = [description[0] for description in cursor.description]
    records = [dict(zip(columns, row)) for row in cursor.fetchall()]
    return {"status": "success", "row_count": len(records), "records": records}


def run_readonly_query(
    csv_path: str | Path,
    sql: str,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, object]:
    """Run one sanitized read-only SELECT against the CSV-backed view."""

    cleaned = _sanitize_select(sql)
    safe_limit = _validate_limit(limit)
    with _connect(csv_path) as connection:
        result = _execute(connection, f"SELECT * FROM ({cleaned}) LIMIT ?", [safe_limit])
    result["sql"] = cleaned
    result["evidence"] = f"production_records:{Path(csv_path).name}"
    return result


def query_quality_data(
    csv_path: str | Path,
    start_date: str | None = None,
    end_date: str | None = None,
    production_line: str | None = None,
    vehicle_model: str | None = None,
    columns: list[str] | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, object]:
    """Filter production records with bound parameters only (no raw SQL)."""

    if start_date:
        _validate_date(start_date, "start_date")
    if end_date:
        _validate_date(end_date, "end_date")
    if start_date and end_date and start_date > end_date:
        raise ValueError("start_date cannot be after end_date")

    selected = list(columns) if columns else ["*"]
    unknown = set(selected) - ALLOWED_COLUMNS - {"*"}
    if unknown:
        raise ValueError(f"columns are not whitelisted: {', '.join(sorted(unknown))}")
    if not selected:
        raise ValueError("columns cannot be empty")

    conditions: list[str] = []
    params: list[object] = []
    if start_date:
        conditions.append("LEFT(CAST(timestamp AS VARCHAR), 10) >= ?")
        params.append(start_date)
    if end_date:
        conditions.append("LEFT(CAST(timestamp AS VARCHAR), 10) <= ?")
        params.append(end_date)
    if production_line:
        conditions.append("production_line = ?")
        params.append(production_line)
    if vehicle_model:
        conditions.append("vehicle_model = ?")
        params.append(vehicle_model)

    where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"SELECT {', '.join(selected)} FROM production_records{where_clause} LIMIT ?"
    params.append(_validate_limit(limit))

    with _connect(csv_path) as connection:
        result = _execute(connection, sql, params)

    filters = {
        "start_date": start_date,
        "end_date": end_date,
        "production_line": production_line,
        "vehicle_model": vehicle_model,
    }
    result["filters"] = filters
    date_range = f"{start_date or '*'}~{end_date or '*'}"
    result["evidence"] = f"production_records:{date_range}"
    return result
