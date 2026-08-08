"""Pluggable LLM-based question parsing with deterministic fallback.

Three backends are supported, selected by the ``QUALITY_LLM_PROVIDER``
environment variable (default ``mock``):

- ``mock``: rule-based simulator (also handles Chinese dates, vehicle
  models, and compound production lines). Deterministic, used in dev/tests.
- ``ollama``: local Ollama via its OpenAI-compatible endpoint.
- ``glm``: Zhipu GLM via its OpenAI-compatible endpoint.

Every failure path (network error, bad JSON, invalid values) falls back to
the deterministic rule parser from ``agent.workflow``; LLM output is merged
with rule output so a missing field never gets lost.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime


DEFAULT_YEAR = "2026"
_CHINESE_DATE_RANGE = re.compile(r"(\d{1,2})月(\d{1,2})日(?:到|至)(\d{1,2})月(\d{1,2})日")
_CHINESE_DATE_SINGLE = re.compile(r"(\d{1,2})月(\d{1,2})日")
_VEHICLE_MODEL = re.compile(r"(ID\.\w+)", re.IGNORECASE)
_MULTI_LINE = re.compile(r"([A-Z])\s*产线\s*(?:和|与|及)\s*([A-Z])")
_MULTI_LINE_REVERSED = re.compile(r"产线\s*([A-Z])\s*(?:和|与|及)\s*产线?\s*([A-Z])")


def _rule_filters(question: str) -> dict[str, object]:
    """The deterministic rule parser (superset of agent.workflow.parse_question)."""

    from agent.workflow import parse_question

    filters: dict[str, object] = parse_question(question)

    chinese = _CHINESE_DATE_RANGE.search(question)
    if chinese:
        start_month, start_day, end_month, end_day = chinese.groups()
        filters["start_date"] = f"{DEFAULT_YEAR}-{int(start_month):02d}-{int(start_day):02d}"
        filters["end_date"] = f"{DEFAULT_YEAR}-{int(end_month):02d}-{int(end_day):02d}"
    elif filters["start_date"] is None:
        single = _CHINESE_DATE_SINGLE.search(question)
        if single:
            month, day = single.groups()
            filters["start_date"] = f"{DEFAULT_YEAR}-{int(month):02d}-{int(day):02d}"
            filters["end_date"] = filters["start_date"]

    model = _VEHICLE_MODEL.search(question)
    if model:
        filters["vehicle_model"] = model.group(1).upper()

    multi = _MULTI_LINE.search(question) or _MULTI_LINE_REVERSED.search(question)
    if multi:
        filters["production_line"] = sorted({multi.group(1).upper(), multi.group(2).upper()})
    elif isinstance(filters["production_line"], str):
        filters["production_line"] = [filters["production_line"]]
    return filters


def mock_parse(question: str) -> dict[str, str | list[str] | None]:
    """Simulator backend: rule-based parsing with the extended vocabulary."""

    filters = _rule_filters(question)
    return {
        "start_date": filters.get("start_date"),
        "end_date": filters.get("end_date"),
        "production_line": filters.get("production_line"),
        "vehicle_model": filters.get("vehicle_model"),
    }


_SYSTEM_PROMPT = (
    "你是制造质量分析系统的问题解析器。从用户问题中提取查询条件，"
    "只输出一个 JSON 对象，不要输出任何其他内容。格式："
    '{"start_date": "YYYY-MM-DD或null", "end_date": "YYYY-MM-DD或null", '
    '"production_line": "产线字母或null", "vehicle_model": "车型或null"}。'
    "注意：日期统一转成 YYYY-MM-DD 格式，没给年份的用 2026；"
    "产线只取 A-Z 单个字母；复合产线用列表。"
)


def _call_http(url: str, api_key: str | None, question: str, model: str, timeout: float) -> dict[str, object]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    content = body["choices"][0]["message"]["content"]
    return json.loads(content)


def _call_ollama(question: str, timeout: float) -> dict[str, object]:
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    model = os.environ.get("QUALITY_LLM_MODEL", "qwen2.5:7b")
    return _call_http(f"{base_url}/chat/completions", None, question, model, timeout)


def _call_glm(question: str, timeout: float) -> dict[str, object]:
    base_url = os.environ.get("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
    api_key = os.environ.get("GLM_API_KEY")
    if not api_key:
        raise ValueError("GLM_API_KEY is not set")
    model = os.environ.get("QUALITY_LLM_MODEL", "glm-4-flash")
    return _call_http(f"{base_url}/chat/completions", api_key, question, model, timeout)


def _sanitize_llm_filters(raw: object) -> dict[str, str | list[str] | None]:
    """Clean and type-check an LLM-produced filters dict; invalid fields become None."""

    if not isinstance(raw, dict):
        raise ValueError("LLM output is not a JSON object")

    def clean_date(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        try:
            return datetime.strptime(text, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            return None

    def clean_line(value: object) -> str | list[str] | None:
        if value is None:
            return None
        if isinstance(value, list):
            lines = [str(item).upper() for item in value if re.fullmatch(r"[A-Z]", str(item).strip())]
            return sorted(set(lines)) or None
        if re.fullmatch(r"[A-Z]", str(value).strip()):
            return [str(value).strip().upper()]
        return None

    def clean_model(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text if text else None

    return {
        "start_date": clean_date(raw.get("start_date")),
        "end_date": clean_date(raw.get("end_date")),
        "production_line": clean_line(raw.get("production_line")),
        "vehicle_model": clean_model(raw.get("vehicle_model")),
    }


def parse_with_llm(question: str, provider: str = "mock", timeout: float = 10.0) -> dict[str, object]:
    """Parse the question with the selected backend; fall back to rules on any failure."""

    rules = _rule_filters(question)
    if provider == "mock":
        return mock_parse(question)

    try:
        if provider == "ollama":
            raw = _call_ollama(question, timeout)
        elif provider == "glm":
            raw = _call_glm(question, timeout)
        else:
            raise ValueError(f"unknown provider: {provider}")
        cleaned = _sanitize_llm_filters(raw)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, urllib.error.URLError, OSError):
        cleaned = {"start_date": None, "end_date": None, "production_line": None, "vehicle_model": None}

    merged = dict(cleaned)
    for key in ("start_date", "end_date", "production_line", "vehicle_model"):
        if merged.get(key) in (None, "", []):
            merged[key] = rules.get(key)
    return merged


def make_parse_fn(provider: str | None = None) -> object:
    """Return a ``(question) -> filters`` callable for the given provider."""

    resolved = provider or os.environ.get("QUALITY_LLM_PROVIDER", "mock")

    def parse_fn(question: str) -> dict[str, object]:
        return parse_with_llm(question, provider=resolved)

    return parse_fn
