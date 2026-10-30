"""CSV source identity and validation helpers."""

from hashlib import sha256
from io import BytesIO
import json

import pandas as pd

REQUIRED_COLUMNS = {"timestamp", "production_line", "workstation", "shift", "supplier_id", "result"}


def records_content_hash(records: list[dict]) -> str:
    """Hash a normalized record sequence for non-uploaded data sources."""

    payload = json.dumps(
        [dict(record) for record in records],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def source_from_csv(name: str, content: bytes) -> tuple[str, dict]:
    frame = pd.read_csv(BytesIO(content))
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"CSV 缺少字段：{', '.join(sorted(missing))}")
    if frame.empty:
        raise ValueError("CSV 没有生产记录")
    # Content, rather than filename/size, identifies a revision of a source.
    source_id = sha256(content).hexdigest()
    return source_id, {"name": name, "records": frame.fillna("").to_dict(orient="records")}


