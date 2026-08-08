"""Structured JSON run logs for traceability.

Every ``QualityAgent.answer()`` call writes one JSON file under ``logs/``:
question, filters, per-tool steps, status, defect rate, candidate factors,
elapsed time, and the human-review flag. Logging failures never break the
main workflow.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Mapping


DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


def log_run(
    report: Mapping[str, object],
    trace: list[dict[str, object]],
    provider: str,
    elapsed_ms: float,
    log_dir: str | Path = DEFAULT_LOG_DIR,
) -> Path:
    """Write one structured run entry and return its path."""

    baseline = report.get("baseline") or {}
    top_factors = [
        {
            "dimension": factor.get("dimension"),
            "value": factor.get("value"),
            "defect_rate_percent": factor.get("defect_rate_percent"),
            "sample_count": factor.get("sample_count"),
        }
        for factor in report.get("top_factors") or []
    ]
    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "question": report.get("question"),
        "provider": provider,
        "status": report.get("status"),
        "filters": report.get("filters"),
        "defect_rate_percent": baseline.get("defect_rate_percent"),
        "top_factors": top_factors,
        "steps": [dict(step) for step in trace],
        "total_elapsed_ms": round(elapsed_ms, 2),
        "requires_human_review": bool(report.get("requires_human_review", False)),
    }

    destination = Path(log_dir)
    destination.mkdir(parents=True, exist_ok=True)
    filename = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.json"
    path = destination / filename
    path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def measure_run(func):
    """Decorator: time a callable and return ``(result, elapsed_ms)``."""

    def wrapped(*args, **kwargs):
        started = time.perf_counter()
        result = func(*args, **kwargs)
        return result, (time.perf_counter() - started) * 1000

    return wrapped
