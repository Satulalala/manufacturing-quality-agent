"""Structured JSON run logs for traceability.

Every ``QualityAgent.answer()`` call writes one JSON file under ``logs/``:
question, filters, per-tool steps, status, defect rate, candidate factors,
elapsed time, and the human-review flag. Logging failures never break the
main workflow.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Mapping


DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
DEFAULT_EVENT_LOG = Path(__file__).resolve().parent.parent / ".cache" / "quality_agent_events.jsonl"
_EVENT_LOCK = threading.Lock()


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
        "stage_timings": report.get("stage_timings", {}),
        "llm_status": report.get("llm_status"),
        "explanation_source": report.get("explanation_source"),
        "requires_human_review": bool(report.get("requires_human_review", False)),
    }

    destination = Path(log_dir)
    destination.mkdir(parents=True, exist_ok=True)
    filename = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.json"
    path = destination / filename
    path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def log_execution_event(
    report: Mapping[str, object],
    *,
    session_id: str | None,
    task_id: str,
    data_version: str,
    recovery_event: str,
    event_log: str | Path = DEFAULT_EVENT_LOG,
) -> Path:
    """Append compact operational metadata without prompts or tool result bodies."""

    decision = report.get("decision_loop") or {}
    if not isinstance(decision, Mapping):
        decision = {}
    events = decision.get("events") or []
    tool_call_ids = [
        str(event["tool_call_id"])
        for event in events
        if isinstance(event, Mapping) and event.get("tool_call_id")
    ]
    tool_calls = [
        {
            "tool_call_id": str(event["tool_call_id"]),
            "tool": event.get("tool"),
            "action": event.get("action"),
        }
        for event in events
        if isinstance(event, Mapping) and event.get("tool_call_id")
    ]
    entry = {
        "event_id": str(uuid.uuid4()),
        "event_type": "run_completed",
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "session_id": session_id,
        "run_id": report.get("run_id"),
        "task_id": task_id,
        "source_id": report.get("source_id"),
        "data_version": data_version,
        "task": report.get("task"),
        "status": report.get("status"),
        "latency_ms": round(float(report.get("elapsed_ms") or 0), 2),
        "tool_call_ids": tool_call_ids,
        "tool_calls": tool_calls,
        "tool_call_count": decision.get("tool_call_count", 0),
        "tool_execution_count": decision.get("tool_execution_count", 0),
        "retry_count": decision.get("retry_count", 0),
        "stop_reason": decision.get("stop_reason"),
        "recovery_event": recovery_event,
    }
    path = Path(event_log)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
    with _EVENT_LOCK, path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
    return path


def measure_run(func):
    """Decorator: time a callable and return ``(result, elapsed_ms)``."""

    def wrapped(*args, **kwargs):
        started = time.perf_counter()
        result = func(*args, **kwargs)
        return result, (time.perf_counter() - started) * 1000

    return wrapped
