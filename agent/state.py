"""Structured state shared by quality parsing and report generation."""

from __future__ import annotations

from typing import TypedDict


class TraceStep(TypedDict):
    tool: str
    detail: str


class QualityState(TypedDict, total=False):
    records: list[dict[str, object]]
    question: str
    parsed_query: dict[str, object]
    llm_provider: str
    task: str
    task_args: dict[str, object]
    csv_path: str | None
    model_fn: object
    progress_fn: object
    partial_report_fn: object
    stage_timings: dict[str, float]
    llm_status: str
    tracing_status: str
    filters: dict[str, object]
    interpretation: str
    clarification: str
    date_filter_requested: bool
    parse_error: str
    filtered_records: list[dict[str, object]]
    baseline: dict[str, float | int]
    candidates: list[dict[str, object]]
    knowledge: dict[str, object]
    tool_result: dict[str, object]
    missing_inputs: list[str]
    explanation: str
    explanation_citations: list[str]
    trace: list[TraceStep]
    report: dict[str, object]
    decision_loop: dict[str, object]
    preserve_partial_evidence: bool
    confirmed_preferences: list[dict[str, object]]


def initial_state(
    records: list[dict[str, object]],
    question: str,
    *,
    llm_provider: str = "ollama",
    csv_path: str | None = None,
    model_fn: object = None,
    llm_status: str = "disabled",
    tracing_status: str = "disabled",
    progress_fn: object = None,
    partial_report_fn: object = None,
    parsed_query: dict[str, object] | None = None,
    confirmed_preferences: list[dict[str, object]] | None = None,
) -> QualityState:
    state: QualityState = {
        "records": records,
        "question": question,
        "llm_provider": llm_provider,
        "csv_path": csv_path,
        "model_fn": model_fn,
        "llm_status": llm_status,
        "tracing_status": tracing_status,
        "progress_fn": progress_fn,
        "partial_report_fn": partial_report_fn,
        "stage_timings": {},
        "trace": [],
        "confirmed_preferences": confirmed_preferences or [],
    }
    if parsed_query is not None:
        state["parsed_query"] = parsed_query
    return state
