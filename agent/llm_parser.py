"""Ollama-based understanding for manufacturing quality questions."""

from __future__ import annotations

import json
import math
import os
import re
import urllib.request
from datetime import datetime

from tools.retry import with_retry


DEFAULT_LLM_TIMEOUT_SECONDS = 60.0
MAX_LLM_TIMEOUT_SECONDS = 120.0


def llm_timeout_seconds(timeout: float | None = None) -> float:
    """Return a bounded Ollama timeout, honoring the shared environment setting."""

    raw_timeout = (
        os.environ.get("QUALITY_LLM_TIMEOUT", str(DEFAULT_LLM_TIMEOUT_SECONDS))
        if timeout is None
        else timeout
    )
    try:
        configured = float(raw_timeout)
    except (TypeError, ValueError):
        configured = DEFAULT_LLM_TIMEOUT_SECONDS
    if not math.isfinite(configured):
        configured = DEFAULT_LLM_TIMEOUT_SECONDS
    return max(1.0, min(MAX_LLM_TIMEOUT_SECONDS, configured))


_QUERY_PROMPT = (
    "你是制造质量分析 Agent 的唯一问题解析器。理解用户意图并提取条件，不计算结果、不编造条件。只输出 JSON。"
    "必需字段 task，可选值 quality_analysis/sql/cpk/spc/anomaly/knowledge。默认用 quality_analysis；"
    "只有用户明确要求 SQL 查询、Cpk/能力指数、SPC/控制图、异常检测、知识库案例时才选对应工具。"
    "普通的质量、不良率、缺陷、产线问题都用 quality_analysis。例：分析2026年1月上旬的质量 -> quality_analysis。"
    "日期字段使用 YYYY-MM-DD，范围两端都包含。单独的年月表示整月；上旬为1-10日，中旬为11-20日，下旬为21日至月末。"
    "某日之前/早于该日不含当天，只给 end_date=前一天；之后/晚于该日不含当天，只给 start_date=后一天；"
    "截至/及以前包含当天。不得自行补起始日期。"
    "date_filter_requested 表示用户是否提到时间；date_scope 只能为 range/all_data/unclear。无时间用 all_data。"
    "有时间但缺少年份时，仅当提供的数据日期上下文只涉及一个年份，才用该年份补全；否则用 unclear 并询问。"
    "用户明确给了日期范围时，start_date/end_date 必须填实际边界，不得返回 null。"
    "跨月范围必须保留两个端点：从某月到某月，开始为首月1日，结束为末月最后一天。"
    "并列月份不得遗漏：2026年7月和8月表示2026-07-01至2026-08-31；7、8、9月同理。"
    "不连续月份不能转换成包含中间月份的连续范围，应请求明确；多年份数据中未指定年份也应请求明确。"
    "数据覆盖范围不等于用户请求范围，即使没有相应记录也不能缩短日期条件。"
    "例：参考年份2026，分析一月到四月的质量 -> start_date=2026-01-01,end_date=2026-04-30。"
    "例：分析2026年1月上旬质量 -> start_date=2026-01-01,end_date=2026-01-10,date_scope=range。"
    "task=cpk 时，field 只能为 torque/pressure/temperature；只使用用户提供的 USL/LSL 和 unit，不得采用内置/演示规格。"
    "task=cpk 缺任一规格边界或 unit 时必须留空对应字段并请求补充；USL 必须大于 LSL。unit 原样记录，计算不做单位换算。"
    "task=spc 时，field 只能为 torque/pressure/temperature。"
    "production_line 输出大写字母数组，如A产线为[\"A\"]，不可遗漏；车型原样输出。明确提到的工位、班次、供应商、批次、缺陷类型也原样输出为数组，未提到时返回空数组。"
    "workstation、shift、supplier_id、batch_id、defect_type 都是等值筛选；不得把风险排名或推测值伪装成用户筛选条件。numeric_fields 只含 torque/pressure/temperature。"
    "production_line 必须返回，未指定产线时为[]。其余可选字段只返回与问题相关的值；可用字段：task,start_date,end_date,date_filter_requested,date_scope,"
    "production_line,vehicle_model,workstation,shift,supplier_id,batch_id,defect_type,field,usl,lsl,unit,numeric_fields,clarification_needed。"
    "clarification_needed 为布尔值。禁止生成 SQL、解释或额外文字。"
)

_QUERY_SCHEMA = {
    "type": "object",
    "properties": {
        "task": {
            "type": "string",
            "enum": ["quality_analysis", "sql", "cpk", "spc", "anomaly", "knowledge"],
        },
        "start_date": {"type": ["string", "null"]},
        "end_date": {"type": ["string", "null"]},
        "date_filter_requested": {"type": "boolean"},
        "date_scope": {"type": "string", "enum": ["range", "all_data", "unclear"]},
        "production_line": {"type": "array", "items": {"type": "string"}},
        "vehicle_model": {"type": "string"},
        "workstation": {"type": "array", "items": {"type": "string"}},
        "shift": {"type": "array", "items": {"type": "string"}},
        "supplier_id": {"type": "array", "items": {"type": "string"}},
        "batch_id": {"type": "array", "items": {"type": "string"}},
        "defect_type": {"type": "array", "items": {"type": "string"}},
        "field": {"type": "string", "enum": ["torque", "pressure", "temperature", ""]},
        "usl": {"type": ["number", "null"]},
        "lsl": {"type": ["number", "null"]},
        "unit": {"type": "string"},
        "numeric_fields": {
            "type": "array",
            "items": {"type": "string", "enum": ["torque", "pressure", "temperature"]},
        },
        "clarification_needed": {"type": "boolean"},
    },
    "required": [
        "task",
        "start_date",
        "end_date",
        "date_filter_requested",
        "date_scope",
        "production_line",
        "unit",
        "clarification_needed",
    ],
    "additionalProperties": False,
}


def _call_http(
    url: str,
    question: str,
    model: str,
    timeout: float,
    system_prompt: str = _QUERY_PROMPT,
) -> dict[str, object]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ],
        "format": _QUERY_SCHEMA,
        "stream": False,
        "think": False,
        "keep_alive": "10m",
        "options": {
            "temperature": 0,
            "num_ctx": 2048,
            "num_predict": 128,
        },
    }
    headers = {"Content-Type": "application/json"}
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    content = body["message"]["content"]
    return json.loads(content)


def _call_ollama(
    question: str,
    timeout: float,
    system_prompt: str = _QUERY_PROMPT,
    attempts: int = 2,
) -> dict[str, object]:
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    base_url = base_url.rstrip("/")
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]
    elif base_url.endswith("/api"):
        base_url = base_url[:-4]
    model = os.environ.get("QUALITY_LLM_MODEL", "qwen3:4b-q4_K_M")
    return with_retry(
        lambda: _call_http(f"{base_url}/api/chat", question, model, timeout, system_prompt),
        attempts=attempts,
    )[0]


def _sanitize_llm_filters(raw: object) -> dict[str, object]:
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
            lines = [
                str(item).strip().upper()
                for item in value
                if re.fullmatch(r"[A-Z]", str(item).strip(), re.IGNORECASE)
            ]
            return sorted(set(lines)) or None
        if re.fullmatch(r"[A-Z]", str(value).strip(), re.IGNORECASE):
            return [str(value).strip().upper()]
        return None

    def clean_model(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text if text else None

    def clean_values(value: object) -> list[str]:
        candidates = value if isinstance(value, list) else ([value] if isinstance(value, str) else [])
        result = []
        for item in candidates[:32]:
            if not isinstance(item, str):
                continue
            text = item.strip()
            if text and len(text) <= 100 and not any(ord(character) < 32 for character in text):
                result.append(text)
        return list(dict.fromkeys(result))

    return {
        "start_date": clean_date(raw.get("start_date")),
        "end_date": clean_date(raw.get("end_date")),
        "production_line": clean_line(raw.get("production_line")),
        "vehicle_model": clean_model(raw.get("vehicle_model")),
        "workstation": clean_values(raw.get("workstation")),
        "shift": clean_values(raw.get("shift")),
        "supplier_id": clean_values(raw.get("supplier_id")),
        "batch_id": clean_values(raw.get("batch_id")),
        "defect_type": clean_values(raw.get("defect_type")),
    }


def _sanitize_llm_query(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ValueError("Ollama 没有返回 JSON 对象")
    task = raw.get("task")
    if task not in {"quality_analysis", "sql", "cpk", "spc", "anomaly", "knowledge"}:
        raise ValueError("Ollama 返回了不支持的任务类型")

    filters = _sanitize_llm_filters(raw)
    field = raw.get("field")
    if field not in {"torque", "pressure", "temperature", ""}:
        field = ""
    numeric_fields = raw.get("numeric_fields")
    if not isinstance(numeric_fields, list):
        numeric_fields = []
    numeric_fields = [
        value for value in numeric_fields
        if value in {"torque", "pressure", "temperature"}
    ]

    def clean_number(value: object) -> float | None:
        if value is None or value == "":
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    raw_lines = filters["production_line"]
    lines = raw_lines if isinstance(raw_lines, list) else ([raw_lines] if raw_lines else [])
    return {
        "task": task,
        "start_date": filters["start_date"],
        "end_date": filters["end_date"],
        "date_filter_requested": raw.get("date_filter_requested") is True,
        "date_scope": raw.get("date_scope") if raw.get("date_scope") in {"range", "all_data", "unclear"} else "unclear",
        "production_line": lines,
        "vehicle_model": filters["vehicle_model"] or "",
        "workstation": filters["workstation"],
        "shift": filters["shift"],
        "supplier_id": filters["supplier_id"],
        "batch_id": filters["batch_id"],
        "defect_type": filters["defect_type"],
        "field": field,
        "usl": clean_number(raw.get("usl")),
        "lsl": clean_number(raw.get("lsl")),
        "unit": str(raw.get("unit") or "").strip()[:32],
        "numeric_fields": numeric_fields,
        "clarification_needed": raw.get("clarification_needed") is True,
        "clarification": str(raw.get("clarification") or "").strip(),
        "interpretation": str(raw.get("interpretation") or "").strip()[:240],
    }


def parse_query_with_model(question: str, timeout: float | None = None) -> dict[str, object]:
    """Use local Ollama as the sole natural-language parser."""

    timeout = llm_timeout_seconds(timeout)
    raw = _call_ollama(question, timeout, _QUERY_PROMPT, attempts=1)
    return _sanitize_llm_query(raw)


def parse_with_llm(question: str, timeout: float | None = None) -> dict[str, object]:
    """Compatibility wrapper returning Ollama's parsed filters only."""

    return {
        key: value
        for key, value in parse_query_with_model(question, timeout).items()
        if key in {"start_date", "end_date", "production_line", "vehicle_model"}
    }


def make_parse_fn(provider: str | None = None) -> object:
    """Return the Ollama ``(question) -> structured parse`` callable."""

    resolved = provider or "ollama"
    if resolved != "ollama":
        raise ValueError(f"仅支持 Ollama 问题解析，当前配置为：{resolved}")
    return parse_query_with_model
