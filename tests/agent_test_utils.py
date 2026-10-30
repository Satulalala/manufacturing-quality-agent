"""Deterministic model-action fixtures for Agent loop tests."""

from __future__ import annotations


def scripted_quality_decision(payload, timeout_seconds=None):
    """Exercise the real loop and tools without calling a live model."""

    context = payload.get("context", {})
    task = str(context.get("task", "quality_analysis"))
    observations = payload.get("observations", [])
    if observations:
        return {"action": "finish", "tool": "", "arguments": {}, "message": "基于工具证据完成分析。"}

    tool_by_task = {
        "quality_analysis": "quality_summary",
        "cpk": "calculate_cpk",
        "spc": "analyze_spc",
        "anomaly": "detect_anomalies",
        "knowledge": "search_knowledge",
        "sql": "read_only_query",
    }
    tool = tool_by_task.get(task)
    tools = {str(item.get("name")): item for item in payload.get("tools", []) if isinstance(item, dict)}
    if not tool or tool not in tools:
        return {"action": "ask_user", "tool": "", "arguments": {}, "message": "当前任务缺少可用的分析工具。"}

    context_args = context.get("task_args", {})
    if not isinstance(context_args, dict):
        context_args = {}
    pending = context.get("pending_task", {})
    pending_args = pending.get("parsed_query", {}) if isinstance(pending, dict) else {}
    if isinstance(pending_args, dict):
        context_args = {**context_args, **pending_args}
    if task == "cpk":
        arguments = {
            key: context_args[key]
            for key in ("field", "usl", "lsl", "unit")
            if key in context_args and context_args[key] is not None
        }
    elif task == "spc":
        arguments = {"field": context_args.get("field", "torque")}
    elif task == "knowledge":
        arguments = {"query": payload.get("question", "质量问题")[:300]}
    else:
        arguments = {}

    return {"action": "call_tool", "tool": tool, "arguments": arguments, "message": ""}
