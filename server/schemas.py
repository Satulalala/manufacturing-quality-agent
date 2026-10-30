"""Stable request and response contracts for the local workbench API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SourceDTO(BaseModel):
    source_id: str
    name: str
    kind: Literal["demo", "upload"]
    record_count: int
    data_version: str


class SourcePreviewDTO(BaseModel):
    source_id: str
    offset: int
    limit: int
    total: int
    columns: list[str]
    records: list[dict[str, Any]]


class SourceDimensionsDTO(BaseModel):
    source_id: str
    production_lines: list[str]
    vehicle_models: list[str]
    workstations: list[str]


class SessionCreateRequest(BaseModel):
    source_id: str = Field(min_length=1, max_length=128)
    title: str = Field(default="新会话", max_length=80)


class SessionRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=80)


class SessionSourcesRequest(BaseModel):
    source_ids: list[str] = Field(max_length=8)


class MemorySaveRequest(BaseModel):
    memory_type: Literal["preference", "specification", "investigation"]
    memory_key: str = Field(min_length=1, max_length=120)
    content: dict[str, Any]
    scope: dict[str, Any] = Field(default_factory=dict)
    unit: str = Field(default="", max_length=32)
    source: str = Field(min_length=1, max_length=500)
    confirmed: bool = False


class SessionDTO(BaseModel):
    session_id: str
    title: str
    source_id: str
    data_version: str
    data_sources: list[dict[str, str]] = Field(default_factory=list)
    status: str
    last_question: str
    created_at: str
    updated_at: str


class MessageDTO(BaseModel):
    message_id: str
    session_id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: str
    run_id: str | None = None
    report: dict[str, Any] | None = None
    data_sources: list[dict[str, Any]] = Field(default_factory=list)


class MessagePageDTO(BaseModel):
    session_id: str
    offset: int
    limit: int
    total: int
    messages: list[MessageDTO]


class RunCreateRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    submission_id: str = Field(min_length=36, max_length=36)
    source_ids: list[str] | None = Field(default=None, max_length=8)
    use_decision_loop: bool = True


class RunDTO(BaseModel):
    run_id: str
    session_id: str
    source_id: str
    source_ids: list[str] = Field(default_factory=list)
    submission_id: str
    question: str
    status: str
    created_at: str
    updated_at: str
    report: dict[str, Any] | None = None


class ComparisonCreateRequest(BaseModel):
    comparison_id: str = Field(min_length=36, max_length=36)
    question: str = Field(min_length=1, max_length=4000)
    source_ids: list[str] = Field(min_length=2, max_length=8)
    parent_session_id: str | None = Field(default=None, min_length=36, max_length=36)
    session_ids: dict[str, str] = Field(default_factory=dict)
    use_decision_loop: bool = True


class ComparisonChildDTO(BaseModel):
    source_id: str
    source_name: str
    session_id: str
    run_id: str
    status: str
    report: dict[str, Any] | None = None


class ComparisonDTO(BaseModel):
    comparison_id: str
    question: str
    source_ids: list[str]
    parent_session_id: str | None = None
    status: str
    created_at: str
    updated_at: str
    children: list[ComparisonChildDTO]


class CancelDTO(BaseModel):
    run_id: str
    status: str


class HealthDTO(BaseModel):
    status: Literal["ok"]
    app: str
    model_provider: str
    model_name: str


class ModelHealthDTO(BaseModel):
    status: Literal["available", "model_missing", "unavailable"]
    model_name: str
    message: str


class APIErrorDTO(BaseModel):
    error: dict[str, Any]
