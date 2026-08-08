"""State definition for the LangGraph quality workflow."""

from __future__ import annotations

from typing import TypedDict


class TraceStep(TypedDict):
    tool: str
    detail: str


class QualityState(TypedDict, total=False):
    records: list[dict[str, object]]
    question: str
    filters: dict[str, str | None]
    filtered_records: list[dict[str, object]]
    baseline: dict[str, float | int]
    candidates: list[dict[str, object]]
    knowledge: dict[str, object]
    trace: list[TraceStep]
    report: dict[str, object]


def initial_state(records: list[dict[str, object]], question: str) -> QualityState:
    return {
        "records": records,
        "question": question,
        "trace": [],
    }
