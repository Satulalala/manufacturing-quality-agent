"""Bounded, explicit context assembly for quality Agent decisions."""

from __future__ import annotations

import json


DEFAULT_CONTEXT_TOKEN_BUDGET = 6000
CHARS_PER_ESTIMATED_TOKEN = 4
_FILTER_KEYS = (
    "start_date", "end_date", "production_line", "vehicle_model", "workstation",
    "shift", "supplier_id", "batch_id", "defect_type",
)


class ContextBudgetError(ValueError):
    """Raised when mandatory decision context cannot fit the configured budget."""


def _json_size(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str))


def _compact(value: object, *, depth: int = 0, max_string: int = 240) -> object:
    """Keep model-facing values small while preserving structured fields."""

    if depth >= 5:
        return "[nested value omitted]"
    if isinstance(value, str):
        return value[:max_string] + ("…" if len(value) > max_string else "")
    if isinstance(value, dict):
        return {
            str(key): _compact(item, depth=depth + 1, max_string=max_string)
            for key, item in list(value.items())[:20]
        }
    if isinstance(value, (list, tuple)):
        result = [_compact(item, depth=depth + 1, max_string=max_string) for item in value[:6]]
        if len(value) > 6:
            result.append(f"[{len(value) - 6} items omitted]")
        return result
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:max_string]


def _compact_observation(observation: dict[str, object]) -> dict[str, object]:
    result = {
        key: observation[key]
        for key in ("tool", "tool_call_id", "data_version", "arguments", "status", "cached", "error")
        if key in observation
    }
    raw = observation.get("result")
    if isinstance(raw, dict):
        # Tabular outputs are clipped independently so the summary and counts survive.
        compact_result = _compact(raw, max_string=180)
        if isinstance(compact_result, dict):
            for key in ("records_preview", "groups", "top_factors", "results", "items"):
                values = raw.get(key)
                if isinstance(values, list) and len(values) > 3:
                    compact_result[key] = [_compact(item, max_string=120) for item in values[:3]]
                    compact_result[f"{key}_truncated"] = True
            result["result"] = compact_result
    return result


def _compact_tools(tools: list[dict[str, object]]) -> tuple[list[dict[str, object]], bool]:
    """Shorten optional prose while keeping every callable schema intact."""

    compact_tools: list[dict[str, object]] = []
    description_compacted = False
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        compact_tool = dict(tool)
        description = compact_tool.get("description")
        if isinstance(description, str) and len(description) > 360:
            compact_tool["description"] = description[:360] + "…"
            description_compacted = True
        compact_tools.append(compact_tool)
    return compact_tools, description_compacted


def _compact_evidence_reference(reference: dict[str, object]) -> dict[str, object]:
    """Keep evidence identity and validity scope exact; compact its prose only."""

    result = {
        key: reference[key]
        for key in (
            "evidence_id", "tool", "tool_call_id", "tool_version", "status",
            "data_version", "filters", "scope_hash",
        )
        if key in reference
    }
    if "summary" in reference:
        result["summary"] = _compact(reference["summary"], max_string=180)
    return result


def _pending_summary(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    parsed = value.get("parsed_query")
    fields = ("task", "field", "lsl", "usl", "unit", *_FILTER_KEYS)
    compact_query = {
        key: parsed[key]
        for key in fields
        if isinstance(parsed, dict) and key in parsed
    }
    missing_inputs = value.get("missing_inputs", [])
    return {
        "task": value.get("task"),
        "parsed_query": compact_query,
        "missing_inputs": list(missing_inputs) if isinstance(missing_inputs, list) else [],
        "unit_confirmed": bool(value.get("unit_confirmed")),
    }


class ContextBuilder:
    """Construct a bounded decision payload without truncating locked conditions."""

    def __init__(self, token_budget: int = DEFAULT_CONTEXT_TOKEN_BUDGET) -> None:
        self.token_budget = max(256, int(token_budget))
        self.max_chars = self.token_budget * CHARS_PER_ESTIMATED_TOKEN

    def build(
        self,
        question: str,
        context: dict[str, object],
        tools: list[dict[str, object]],
        observations: list[dict[str, object]],
        remaining_tool_calls: int,
    ) -> tuple[dict[str, object], dict[str, object]]:
        filters = context.get("filters")
        locked_filters = {
            key: filters[key]
            for key in _FILTER_KEYS
            if isinstance(filters, dict) and key in filters
        }
        prompt_context: dict[str, object] = {
            "task": context.get("task"),
            "task_args": _compact(context.get("task_args", {}), max_string=160),
            "filters": locked_filters,
            "data_version": context.get("data_version", ""),
        }
        pending = _pending_summary(context.get("pending_task"))
        if pending:
            prompt_context["pending_task"] = pending
        messages = context.get("recent_messages")
        if isinstance(messages, list):
            prompt_context["recent_messages"] = [
                {
                    "role": str(item.get("role", "user"))[:16],
                    "content": _compact(item.get("content", ""), max_string=400),
                }
                for item in messages[-8:]
                if isinstance(item, dict)
            ]
        prior = context.get("prior_evidence")
        if isinstance(prior, list):
            prompt_context["prior_evidence"] = [
                _compact_evidence_reference(item) for item in prior[-6:] if isinstance(item, dict)
            ]
        preferences = context.get("confirmed_preferences")
        if isinstance(preferences, list):
            prompt_context["confirmed_preferences"] = [
                _compact(item, max_string=160) for item in preferences[:8] if isinstance(item, dict)
            ]
        stale = context.get("stale_evidence_count")
        if isinstance(stale, int) and stale > 0:
            prompt_context["stale_evidence_count"] = stale

        compact_tools, description_compacted = _compact_tools(tools)
        payload: dict[str, object] = {
            "question": question,
            "context": prompt_context,
            "tools": compact_tools,
            "observations": [_compact_observation(item) for item in observations[-6:]],
            "remaining_tool_calls": max(0, int(remaining_tool_calls)),
        }
        was_truncated = description_compacted

        # Drop only optional history first; task, data version, filters, tools and the
        # most recent observation are retained. A conservative fallback is explicit.
        while _json_size(payload) > self.max_chars and prompt_context.get("recent_messages"):
            prompt_context["recent_messages"].pop(0)
            was_truncated = True
        while _json_size(payload) > self.max_chars and prompt_context.get("prior_evidence"):
            prompt_context["prior_evidence"].pop(0)
            was_truncated = True
        while _json_size(payload) > self.max_chars and len(payload["observations"]) > 1:
            payload["observations"].pop(0)
            was_truncated = True
        size = _json_size(payload)
        if size > self.max_chars:
            raise ContextBudgetError(
                "当前问题、筛选条件和工具定义超出上下文预算，未调用模型或工具。"
            )
        metadata = {
            "budget_tokens": self.token_budget,
            "estimated_tokens": (size + CHARS_PER_ESTIMATED_TOKEN - 1) // CHARS_PER_ESTIMATED_TOKEN,
            "estimate_method": "json_characters_divided_by_4",
            "truncated": was_truncated or len(prompt_context.get("recent_messages", [])) < len(messages or []),
        }
        return payload, metadata
