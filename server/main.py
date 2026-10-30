"""FastAPI entry point for the local quality Agent workbench."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from analytics.quality_charts import quality_chart_data
from agent.result_store import ResultStore
from agent.memory_store import MemoryStore
from tools.quality_tools import filter_records
from server.schemas import (
    CancelDTO,
    ComparisonCreateRequest,
    ComparisonDTO,
    HealthDTO,
    MessagePageDTO,
    MemorySaveRequest,
    ModelHealthDTO,
    RunCreateRequest,
    RunDTO,
    SessionCreateRequest,
    SessionDTO,
    SessionRenameRequest,
    SessionSourcesRequest,
    SourceDTO,
    SourceDimensionsDTO,
    SourcePreviewDTO,
)
from server.services.conversations import ConversationService
from server.services.comparisons import ComparisonService
from server.services.runs import RunManager
from server.services.speech import MAX_AUDIO_BYTES, InvalidAudio, SpeechModelUnavailable, SpeechRecognitionError, speech_status, transcribe_audio
from server.services.sources import MAX_CSV_BYTES, PROJECT_ROOT, SourceRegistry


app = FastAPI(title="制造质量 Agent 工作台", version="1.0.0", docs_url="/api/docs", redoc_url=None)
sources = SourceRegistry()
conversations = ConversationService()
runs = RunManager(sources, conversations)
comparisons = ComparisonService(sources, conversations, runs)


@app.get("/api/v1/speech/status")
def get_speech_status() -> dict[str, str]:
    return speech_status()


@app.post("/api/v1/speech/transcribe")
async def speech_transcribe(file: UploadFile = File(...)) -> dict[str, str | float]:
    allowed_types = {"audio/webm", "audio/ogg", "audio/wav", "audio/x-wav", "audio/mp4", "audio/mpeg", "audio/mp3"}
    content_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    extension = Path(file.filename or "").suffix.lower()
    allowed_extensions = {".webm", ".ogg", ".wav", ".mp4", ".m4a", ".mp3"}
    if content_type not in allowed_types and extension not in allowed_extensions:
        await file.close()
        raise HTTPException(status_code=415, detail="仅支持 WebM、OGG、WAV、MP4 或 MP3 录音格式。")
    content_length = file.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > MAX_AUDIO_BYTES:
        await file.close()
        raise HTTPException(status_code=413, detail="单次录音不能超过 12 MB。")
    try:
        audio = await file.read(MAX_AUDIO_BYTES + 1)
        if len(audio) > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail="单次录音不能超过 12 MB。")
        try:
            return await run_in_threadpool(transcribe_audio, audio)
        except SpeechModelUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except InvalidAudio as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except SpeechRecognitionError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
    finally:
        await file.close()


def _error_code(status_code: int) -> str:
    return {
        400: "BAD_REQUEST",
        404: "NOT_FOUND",
        409: "CONFLICT",
        413: "PAYLOAD_TOO_LARGE",
        422: "VALIDATION_ERROR",
    }.get(status_code, "REQUEST_ERROR" if status_code < 500 else "INTERNAL_ERROR")


@app.exception_handler(HTTPException)
async def http_error_handler(_: Request, error: HTTPException) -> JSONResponse:
    detail = error.detail if isinstance(error.detail, str) else "请求失败"
    return JSONResponse(
        status_code=error.status_code,
        content={"error": {"code": _error_code(error.status_code), "message": detail}},
        headers=error.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, error: RequestValidationError) -> JSONResponse:
    issues = [
        {"field": ".".join(str(part) for part in item.get("loc", ())[1:]), "message": item.get("msg", "输入无效")}
        for item in error.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "VALIDATION_ERROR", "message": "请求内容不符合要求", "details": issues}},
    )


def _raise_service_error(error: Exception) -> None:
    if isinstance(error, KeyError):
        raise HTTPException(status_code=404, detail=str(error).strip("'\"")) from error
    if isinstance(error, RuntimeError):
        raise HTTPException(status_code=409, detail=str(error)) from error
    if isinstance(error, ValueError):
        raise HTTPException(status_code=422, detail=str(error)) from error
    raise error


@app.get("/api/v1/health", response_model=HealthDTO)
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "app": "quality-agent-workbench",
        "model_provider": "ollama",
        "model_name": os.getenv("QUALITY_LLM_MODEL", "qwen3:4b-q4_K_M"),
    }


@app.get("/api/v1/health/model", response_model=ModelHealthDTO)
def model_health() -> dict[str, str]:
    model_name = os.getenv("QUALITY_LLM_MODEL", "qwen3:4b-q4_K_M")
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=1.2) as response:
            body = json.loads(response.read(1_000_000).decode("utf-8"))
        installed = {
            str(item.get("name", ""))
            for item in body.get("models", [])
            if isinstance(item, dict)
        }
        if model_name not in installed:
            return {"status": "model_missing", "model_name": model_name, "message": "Ollama 已响应，但配置模型未出现在本机模型列表中。"}
        return {"status": "available", "model_name": model_name, "message": "配置的 Ollama 模型可用。"}
    except (OSError, urllib.error.URLError, TimeoutError, ValueError, UnicodeDecodeError):
        return {"status": "unavailable", "model_name": model_name, "message": "无法连接本地 Ollama；工作台仍可打开，提交分析前需启动模型服务。"}


@app.get("/api/v1/sources", response_model=list[SourceDTO])
def list_sources() -> list[dict[str, object]]:
    return sources.list()


@app.post("/api/v1/sources/upload", response_model=SourceDTO, status_code=201)
async def upload_source(file: UploadFile = File(...)) -> dict[str, object]:
    if file.filename and len(file.filename) > 500:
        raise HTTPException(status_code=422, detail="文件名长度无效")
    content_length = file.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > MAX_CSV_BYTES + 1024 * 1024:
        raise HTTPException(status_code=413, detail="CSV 文件不能超过 20 MB")
    content = await file.read(MAX_CSV_BYTES + 1)
    if len(content) > MAX_CSV_BYTES:
        raise HTTPException(status_code=413, detail="CSV 文件不能超过 20 MB")
    try:
        source = sources.add_csv(file.filename or "production-data.csv", content)
    except (ValueError, UnicodeDecodeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        await file.close()
    return source.public()


@app.get("/api/v1/sources/{source_id}/preview", response_model=SourcePreviewDTO)
def preview_source(
    source_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    search: str = Query(default="", max_length=200),
    filters: str = Query(default="", max_length=4096),
) -> dict[str, Any]:
    source = sources.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="数据源不存在")
    columns = list(source.records[0].keys()) if source.records else []
    try:
        filter_rules = json.loads(filters) if filters else []
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=422, detail="筛选条件格式无效") from error
    if not isinstance(filter_rules, list) or len(filter_rules) > 12:
        raise HTTPException(status_code=422, detail="最多支持 12 个筛选条件")

    validated_filters: list[tuple[str, str, str]] = []
    for rule in filter_rules:
        if not isinstance(rule, dict):
            raise HTTPException(status_code=422, detail="筛选条件格式无效")
        field = rule.get("field")
        value = rule.get("value")
        match = rule.get("match", "contains")
        if (
            not isinstance(field, str)
            or field not in columns
            or not isinstance(value, str)
            or not isinstance(match, str)
            or match not in {"contains", "equals"}
            or len(value) > 200
        ):
            raise HTTPException(status_code=422, detail="筛选字段或匹配方式无效")
        value = value.strip()
        if value:
            validated_filters.append((field, value.casefold(), match))

    needle = search.strip().casefold()
    matched_records = [
        record
        for record in source.records
        if (not needle or any(needle in str(value).casefold() for value in record.values()))
        and all(
            (str(record.get(field, "")).strip().casefold() == value)
            if match == "equals"
            else value in str(record.get(field, "")).casefold()
            for field, value, match in validated_filters
        )
    ]
    return {
        "source_id": source.source_id,
        "offset": offset,
        "limit": limit,
        "total": len(matched_records),
        "columns": columns,
        "records": matched_records[offset : offset + limit],
    }


@app.get("/api/v1/sources/{source_id}/dimensions", response_model=SourceDimensionsDTO)
def source_dimensions(source_id: str) -> dict[str, object]:
    try:
        return sources.dimensions(source_id)
    except Exception as error:
        _raise_service_error(error)
        raise


@app.get("/api/v1/sessions", response_model=list[SessionDTO])
def list_sessions(source_id: str | None = None) -> list[dict[str, object]]:
    try:
        return conversations.list_sessions(source_id)
    except Exception as error:
        _raise_service_error(error)
        raise


@app.post("/api/v1/sessions", response_model=SessionDTO, status_code=201)
def create_session(request: SessionCreateRequest) -> dict[str, object]:
    source = sources.get(request.source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="数据源不存在")
    try:
        return conversations.create_session(source, request.title)
    except Exception as error:
        _raise_service_error(error)
        raise


@app.get("/api/v1/sessions/{session_id}", response_model=SessionDTO)
def get_session(session_id: str) -> dict[str, object]:
    try:
        session = conversations.get_session(session_id)
    except Exception as error:
        _raise_service_error(error)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


@app.patch("/api/v1/sessions/{session_id}", response_model=SessionDTO)
def rename_session(session_id: str, request: SessionRenameRequest) -> dict[str, object]:
    try:
        session = conversations.rename_session(session_id, request.title)
    except Exception as error:
        _raise_service_error(error)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


@app.put("/api/v1/sessions/{session_id}/sources", response_model=SessionDTO)
def update_session_sources(session_id: str, request: SessionSourcesRequest) -> dict[str, object]:
    selected = []
    for source_id in dict.fromkeys(request.source_ids):
        source = sources.get(source_id)
        if source is None:
            raise HTTPException(status_code=404, detail=f"数据源不存在：{source_id}")
        selected.append(source)
    try:
        session = conversations.set_sources(session_id, selected)
    except Exception as error:
        _raise_service_error(error)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


@app.delete("/api/v1/sessions/{session_id}")
def delete_session(session_id: str) -> dict[str, bool]:
    try:
        deleted = comparisons.delete_session(session_id)
    except Exception as error:
        _raise_service_error(error)
        raise
    if not deleted:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"deleted": True}


@app.get("/api/v1/sessions/{session_id}/messages", response_model=MessagePageDTO)
def list_messages(
    session_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
) -> dict[str, Any]:
    try:
        messages = conversations.messages(session_id)
    except Exception as error:
        _raise_service_error(error)
    return {
        "session_id": session_id,
        "offset": offset,
        "limit": limit,
        "total": len(messages),
        "messages": messages[offset : offset + limit],
    }


@app.post("/api/v1/sessions/{session_id}/runs", response_model=RunDTO, status_code=202)
def create_run(session_id: str, request: RunCreateRequest) -> dict[str, Any]:
    session = conversations.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    try:
        return runs.start(
            session_id,
            str(session["source_id"]),
            request.question,
            request.submission_id,
            request.use_decision_loop,
            request.source_ids,
        )
    except Exception as error:
        _raise_service_error(error)
        raise


@app.get("/api/v1/runs/{run_id}", response_model=RunDTO)
def get_run(run_id: str) -> dict[str, Any]:
    run = runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    report = run.get("report")
    if (
        isinstance(report, dict)
        and report.get("task") == "quality_analysis"
        and report.get("status") == "success"
        and not report.get("charts")
    ):
        version = str(report.get("data_version") or "")
        source_id = str(run.get("source_id") or "")
        refs = report.get("data_sources")
        selected_sources = []
        if isinstance(refs, list) and refs:
            for ref in refs:
                if not isinstance(ref, dict):
                    selected_sources = []
                    break
                selected = sources.get(str(ref.get("source_id", "")))
                if selected is None or selected.data_version != str(ref.get("data_version", "")):
                    selected_sources = []
                    break
                selected_sources.append(selected)
        else:
            source = sources.get(source_id) if source_id else None
            if source is not None and source.data_version == version:
                selected_sources = [source]
        report_source_id = report.get("source_id")
        filters = report.get("filters")
        refs_valid = isinstance(refs, list) and bool(refs) and len(selected_sources) == len(refs)
        legacy_valid = not refs and bool(selected_sources) and (not report_source_id or str(report_source_id) == source_id)
        if (refs_valid or legacy_valid) and isinstance(filters, dict):
            allowed_filters = {
                key: filters[key]
                for key in (
                    "start_date", "end_date", "production_line", "vehicle_model", "workstation",
                    "shift", "supplier_id", "batch_id", "defect_type",
                )
                if key in filters
            }
            try:
                records = [record for selected in selected_sources for record in selected.records]
                filtered_records = filter_records(records, **allowed_filters)
                run = {**run, "report": {**report, "charts": quality_chart_data(filtered_records)}}
            except (TypeError, ValueError):
                run = {**run, "report": {**report, "charts_recovery_status": "unavailable"}}
        else:
            run = {**run, "report": {**report, "charts_recovery_status": "unavailable"}}
    return run


@app.get("/api/v1/sessions/{session_id}/runs", response_model=list[RunDTO])
def list_session_runs(session_id: str, limit: int = Query(default=10, ge=1, le=50)) -> list[dict[str, Any]]:
    if conversations.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    try:
        return runs.list_for_session(session_id, limit)
    except Exception as error:
        _raise_service_error(error)
        raise


@app.get("/api/v1/runs/{run_id}/events")
def run_events(
    run_id: str,
    request: Request,
    last_event_id: int = Query(default=0, ge=0),
) -> StreamingResponse:
    run = runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    header_value = request.headers.get("last-event-id", "")
    try:
        cursor = max(last_event_id, int(header_value or 0))
    except ValueError:
        cursor = last_event_id

    def stream():
        for item in runs.stream(run_id, cursor):
            if item is None:
                yield ": keep-alive\n\n"
            else:
                yield f"id: {item['id']}\ndata: {json.dumps(item['data'], ensure_ascii=False, separators=(',', ':'), default=str)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/v1/runs/{run_id}/cancel", response_model=CancelDTO)
def cancel_run(run_id: str) -> dict[str, str]:
    run = runs.cancel(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return {"run_id": str(run["run_id"]), "status": str(run["status"])}


@app.get("/api/v1/comparisons", response_model=list[ComparisonDTO])
def list_comparisons(limit: int = Query(default=30, ge=1, le=100)) -> list[dict[str, Any]]:
    return comparisons.list(limit)


@app.post("/api/v1/comparisons", response_model=ComparisonDTO, status_code=202)
def create_comparison(request: ComparisonCreateRequest) -> dict[str, Any]:
    try:
        return comparisons.create(
            request.comparison_id,
            request.question,
            request.source_ids,
            session_ids=request.session_ids,
            parent_session_id=request.parent_session_id,
            use_decision_loop=request.use_decision_loop,
        )
    except Exception as error:
        _raise_service_error(error)
        raise


@app.get("/api/v1/comparisons/{comparison_id}", response_model=ComparisonDTO)
def get_comparison(comparison_id: str) -> dict[str, Any]:
    comparison = comparisons.get(comparison_id)
    if comparison is None:
        raise HTTPException(status_code=404, detail="比较记录不存在")
    return comparison


@app.post("/api/v1/comparisons/{comparison_id}/cancel", response_model=ComparisonDTO)
def cancel_comparison(comparison_id: str) -> dict[str, Any]:
    comparison = comparisons.cancel(comparison_id)
    if comparison is None:
        raise HTTPException(status_code=404, detail="比较记录不存在")
    return comparison


@app.get("/api/v1/runs/{run_id}/artifacts")
def run_artifacts(run_id: str) -> dict[str, Any]:
    run = runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    report = run.get("report")
    if not isinstance(report, dict):
        return {"run_id": run_id, "status": run["status"], "artifacts": []}
    artifacts = []
    for key, label in (("baseline", "统计摘要"), ("top_factors", "候选因素"), ("tool_result", "工具结果"), ("evidence_refs", "证据引用"), ("trace", "执行记录")):
        value = report.get(key)
        if value:
            artifacts.append({"artifact_id": f"{run_id}:{key}", "kind": key, "label": label, "data": value})
    return {"run_id": run_id, "status": run["status"], "artifacts": artifacts}


@app.get("/api/v1/sessions/{session_id}/evidence/{evidence_id}")
def get_evidence(session_id: str, evidence_id: str) -> dict[str, Any]:
    try:
        evidence = ResultStore().get(evidence_id, session_id=session_id)
    except (ValueError, KeyError) as error:
        raise HTTPException(status_code=404, detail="证据不存在") from error
    if evidence is None:
        raise HTTPException(status_code=404, detail="证据不存在")
    return evidence


@app.get("/api/v1/memories")
def list_memories(include_history: bool = False) -> list[dict[str, object]]:
    return MemoryStore().list_memories("local", include_history=include_history)


@app.post("/api/v1/memories", status_code=201)
def save_memory(request: MemorySaveRequest) -> dict[str, object]:
    try:
        return MemoryStore().save_confirmed(
            owner_id="local",
            memory_type=request.memory_type,
            memory_key=request.memory_key,
            content=request.content,
            scope=request.scope,
            unit=request.unit,
            source=request.source,
            confirmed=request.confirmed,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.delete("/api/v1/memories/{memory_id}")
def delete_memory(memory_id: str) -> dict[str, bool]:
    return {"deleted": MemoryStore().delete(memory_id, owner_id="local")}


dist_dir = PROJECT_ROOT / "frontend" / "dist"
if dist_dir.is_dir():
    app.mount("/", StaticFiles(directory=dist_dir, html=True), name="frontend")
else:
    @app.get("/", include_in_schema=False, response_class=HTMLResponse)
    def frontend_not_built() -> str:
        return "<h1>前端尚未构建</h1><p>进入 frontend 目录运行 npm install 和 npm run build。</p>"
