"""Opt-in LangSmith tracing for a complete quality-agent run."""

from __future__ import annotations

import os
from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path


_RECORD_KEYS = {"records", "filtered_records", "records_preview"}
_TRUE_VALUES = {"1", "true", "yes", "on"}


def langsmith_context(enabled: bool):
    """Explicitly control implicit LangGraph/LangChain tracing for one call."""

    try:
        from langsmith import tracing_context
    except ImportError:
        return nullcontext()
    return tracing_context(enabled=enabled)


def tracing_is_enabled() -> bool:
    """Require a project-specific switch before any remote trace is sent."""

    return os.environ.get("QUALITY_LANGSMITH_TRACING", "false").strip().lower() in _TRUE_VALUES


def _redact(value: object) -> object:
    """Keep useful run shape while omitting production rows and local paths."""

    if isinstance(value, dict):
        safe: dict[str, object] = {}
        for key, item in value.items():
            if key in _RECORD_KEYS and isinstance(item, (list, tuple)):
                safe[key] = {"record_count": len(item)}
            elif key == "model_fn":
                safe[key] = "[injected model function]"
            elif key == "csv_path" and item:
                safe[key] = Path(str(item)).name
            else:
                safe[str(key)] = _redact(item)
        return safe
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


def configure_tracing() -> tuple[Callable[[str, Callable], Callable], str]:
    """Return an instrumenter and an honest status without requiring LangSmith.

    Uploads are enabled only when tracing is explicitly enabled and a LangSmith
    API key is present. All other configurations stay local and usable.
    """

    if not tracing_is_enabled():
        return lambda _name, fn: fn, "disabled"
    if not (os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY")):
        return lambda _name, fn: fn, "unavailable: LangSmith API key is not set; local only"
    try:
        from langsmith import traceable
    except ImportError:
        return lambda _name, fn: fn, "unavailable: langsmith package is not installed; local only"

    def instrument(name: str, fn: Callable) -> Callable:
        run_type = "retriever" if "retrieval" in name else ("tool" if "tool" in name else "chain")
        return traceable(
            name=name,
            run_type=run_type,
            process_inputs=_redact,
            process_outputs=_redact,
        )(fn)

    return instrument, "enabled"
