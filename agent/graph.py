"""Shared parsing/report helpers and legacy graph compatibility for quality questions."""

from __future__ import annotations

import json
import re
import time
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Callable, Literal

from analytics.anomaly_detection import detect_anomalies
from analytics.quality_analysis import calculate_defect_rate, rank_candidate_causes
from analytics.quality_charts import quality_chart_data
from tools.capability_tool import analyze_process_capability, analyze_spc
from tools.quality_tools import filter_records

from .state import QualityState

TASK_LABELS = {
    "quality_analysis": "质量分析",
    "sql": "SQL 数据查询",
    "cpk": "Cpk 工艺能力",
    "spc": "SPC 过程控制",
    "anomaly": "异常检测",
    "knowledge": "知识检索",
}


def _trace(state: QualityState, tool: str, detail: str) -> None:
    state["trace"].append({"tool": tool, "detail": detail})


def _question_with_data_date_context(question: str, records: list[dict[str, object]]) -> str:
    dates = []
    for record in records:
        try:
            dates.append(date.fromisoformat(str(record.get("timestamp", ""))[:10]))
        except ValueError:
            continue
    if not dates:
        return question
    years = ", ".join(str(year) for year in sorted({value.year for value in dates}))
    return (
        f"用户问题：{question}\n"
        f"补全年份的参考信息：数据涉及年份：{years}。仅用于用户未给年份时补全年份，不能限制用户请求的日期范围。"
    )


def parse_node(
    state: QualityState,
    parse_fn: Callable,
    memory_lookup_fn: Callable[[dict[str, object]], dict[str, object]] | None = None,
) -> dict[str, object]:
    question = str(state.get("question", ""))
    records = state.get("records", [])
    try:
        parsed = state.get("parsed_query")
        if parsed is None:
            parsed = parse_fn(_question_with_data_date_context(question, records))
        else:
            _trace(state, "apply_conversation_context", "using validated session conditions")
        if not isinstance(parsed, dict):
            raise ValueError("Ollama 没有返回结构化解析结果")
        if memory_lookup_fn is not None:
            parsed = memory_lookup_fn(parsed)
            if not isinstance(parsed, dict):
                raise ValueError("记忆查询没有返回有效任务参数")
        from .conversation import validate_requested_scope

        # A merged follow-up already carries the session's reference year. A new
        # question may infer a year only from a source with exactly one year.
        reference = parsed if state.get("parsed_query") is not None else {}
        if not (reference.get("start_date") or reference.get("end_date")):
            years = {str(record.get("timestamp", ""))[:4] for record in records
                     if re.match(r"\d{4}-\d{2}-\d{2}", str(record.get("timestamp", "")))}
            if len(years) == 1:
                year = next(iter(years))
                reference = {"start_date": f"{year}-01-01", "end_date": f"{year}-12-31"}
        parsed = validate_requested_scope(question, parsed, reference)
        task = parsed.get("task")
        if task not in TASK_LABELS:
            raise ValueError("Ollama 返回了不支持的分析任务")

        filters, date_issues = _strict_task_filters(
            {
                "start_date": parsed.get("start_date") or None,
                "end_date": parsed.get("end_date") or None,
                "production_line": parsed.get("production_line") or None,
                "vehicle_model": parsed.get("vehicle_model") or None,
                "workstation": parsed.get("workstation") or None,
                "shift": parsed.get("shift") or None,
                "supplier_id": parsed.get("supplier_id") or None,
                "batch_id": parsed.get("batch_id") or None,
                "defect_type": parsed.get("defect_type") or None,
            },
        )
        missing = list(date_issues)
        if task != "knowledge" and (
            parsed.get("date_scope") == "unclear"
            or (
                parsed.get("date_scope") == "range"
                and not (filters.get("start_date") or filters.get("end_date"))
            )
            or (
                parsed.get("date_filter_requested")
                and not (filters.get("start_date") or filters.get("end_date"))
            )
        ):
            missing.append("date_range")
        if parsed.get("clarification_needed"):
            missing.append("question_clarification")

        field = parsed.get("field") or None
        usl, lsl = parsed.get("usl"), parsed.get("lsl")
        unit = str(parsed.get("unit") or "").strip()
        numeric_fields = parsed.get("numeric_fields") or []
        if task in {"cpk", "spc"} and field not in {"torque", "pressure", "temperature"}:
            missing.append("field")
        if task == "cpk":
            if not unit:
                missing.append("unit")
            if usl is None:
                missing.append("usl")
            if lsl is None:
                missing.append("lsl")
            if usl is not None and lsl is not None and float(usl) <= float(lsl):
                missing.extend(("usl", "lsl"))
        if task == "sql" and not state.get("csv_path"):
            missing.append("csv_path")

        args = {
            "task": task,
            "field": field,
            "usl": usl,
            "lsl": lsl,
            "unit": unit,
            "numeric_fields": numeric_fields,
        }
        missing = list(dict.fromkeys(missing))
        args["missing_inputs"] = missing
        # The model need not spend tokens paraphrasing; keep the original user
        # wording visible when the compact parse schema omits interpretation.
        interpretation = str(parsed.get("interpretation") or question)
        _trace(state, "ollama_understand_question", f"{task}; {filters}")
        return {
            "task": task,
            "task_args": args,
            "missing_inputs": missing,
            "filters": filters,
            "interpretation": interpretation,
            "clarification": str(parsed.get("clarification") or ""),
            "date_filter_requested": bool(parsed.get("date_filter_requested")),
            "parsed_query": parsed,
        }
    except Exception as error:
        _trace(state, "ollama_understand_question", f"failed: {type(error).__name__}")
        timed_out = isinstance(error, TimeoutError) or isinstance(
            getattr(error, "reason", None), TimeoutError
        )
        clarification = (
            "本地 Ollama 解析超时，本次未执行筛选或统计。请检查模型响应和设备负载，"
            "或提高 QUALITY_LLM_TIMEOUT 后重试。"
            if timed_out
            else (
                "本地 Ollama 返回的解析 JSON 不完整或格式无效，本次未执行筛选或统计。"
                "请重新提交；若重复出现，请检查模型输出长度。"
                if isinstance(error, json.JSONDecodeError)
                else "Ollama 问题解析失败，本次未执行筛选或统计。请重新提交问题。"
            )
        )
        return {
            "task": "quality_analysis",
            "task_args": {"task": "quality_analysis", "missing_inputs": ["question_parse"]},
            "missing_inputs": ["question_parse"],
            "filters": {},
            "interpretation": "等待 Ollama 返回问题解析结果时超时；未确认筛选条件。"
            if timed_out
            else "Ollama 未能可靠解析问题；本次没有执行统计。",
            "clarification": clarification,
            "parse_error": type(error).__name__,
        }


def _strict_task_filters(parsed: dict | None = None) -> tuple[dict[str, object], list[str]]:
    filters: dict[str, object] = dict(parsed or {})
    missing: list[str] = []
    # Reject calendar-invalid ISO strings instead of allowing a downstream exception.
    for key in ("start_date", "end_date"):
        value = filters.get(key)
        if value:
            try:
                from datetime import datetime

                datetime.strptime(str(value), "%Y-%m-%d")
            except ValueError:
                filters[key] = None
                missing.append(key)
    if filters.get("start_date") and filters.get("end_date"):
        if str(filters["start_date"]) > str(filters["end_date"]):
            filters["start_date"] = None
            filters["end_date"] = None
            missing.extend(["date_range", "start_date", "end_date"])
    return filters, missing


def query_node(state: QualityState) -> dict[str, object]:
    filtered = filter_records(state["records"], **state["filters"])
    _trace(state, "filter_records", f"{len(filtered)} records")
    return {"filtered_records": filtered}


def analyze_node(state: QualityState) -> dict[str, object]:
    filtered = state["filtered_records"]
    baseline = calculate_defect_rate(filtered)
    ranked = rank_candidate_causes(
        filtered,
        min_samples=max(10, min(20, len(filtered) // 20)),
    )
    _trace(state, "rank_candidate_causes", f"{len(ranked)} candidates")
    return {
        "baseline": baseline,
        "candidates": ranked,
        "tool_result": {
            "status": "success",
            "evidence": (
                f"分析 {baseline['total_count']} 条记录；不良 {baseline['defect_count']} 条；"
                f"不良率 {float(baseline['defect_rate_percent']):.2f}%"
            ),
        },
    }


def task_tool_node(state: QualityState) -> dict[str, object]:
    task = state["task"]
    records = state["filtered_records"]
    args = state["task_args"]
    if task == "cpk":
        result = analyze_process_capability(
            records,
            field=str(args["field"]),
            usl=float(args["usl"]),
            lsl=float(args["lsl"]),
            unit=str(args["unit"]),
        )
        tool_name = "analyze_process_capability"
    elif task == "spc":
        result = analyze_spc(records, field=str(args["field"]))
        tool_name = "analyze_spc"
    else:
        fields = tuple(args.get("numeric_fields") or ())
        result = detect_anomalies(records, numeric_fields=fields or ("temperature", "pressure", "torque"))
        tool_name = "detect_anomalies"
    _trace(state, tool_name, str(result.get("status", "unknown")))
    return {
        "baseline": calculate_defect_rate(records),
        "candidates": [],
        "tool_result": result,
    }


def sql_node(state: QualityState) -> dict[str, object]:
    from tools.sql_tool import query_quality_data

    filters = state["filters"]
    kwargs = {
        "start_date": filters.get("start_date"),
        "end_date": filters.get("end_date"),
        "vehicle_model": filters.get("vehicle_model"),
    }
    try:
        line = filters.get("production_line")
        if isinstance(line, list):
            results = [
                query_quality_data(state["csv_path"], production_line=item, **kwargs)
                for item in line
            ]
            records = [record for item in results for record in item.get("records", [])]
            result: dict[str, object] = {
                "status": "success",
                "row_count": len(records),
                "records": records,
                "evidence": "; ".join(str(item.get("evidence", "")) for item in results),
            }
        else:
            result = query_quality_data(
                state["csv_path"],
                production_line=line,
                **kwargs,
            )
            records = list(result.get("records", []))
    except Exception as error:
        result = {"status": "error", "error": f"只读数据查询失败：{type(error).__name__}"}
        records = []
    result["records_preview"] = records[:20]
    result.pop("records", None)
    baseline = calculate_defect_rate(records)
    result["baseline"] = baseline
    _trace(state, "query_quality_data", f"{len(records)} records; parameterized filters")
    return {
        "filtered_records": records,
        "baseline": baseline,
        "candidates": [],
        "tool_result": result,
    }


def knowledge_node(state: QualityState) -> dict[str, object]:
    from tools.knowledge_tool import retrieve_quality_documents

    dimensions = " ".join(str(factor["dimension"]) for factor in state.get("candidates", []))
    search_text = f"{state['question']} {dimensions}"
    try:
        result = retrieve_quality_documents(search_text, top_k=3, rerank=True)
    except Exception as error:
        result = {
            "status": "no_results",
            "results": [],
            "metadata": {
                "retrieval_mode": "unavailable",
                "fallback_reason": type(error).__name__,
            },
        }
    _trace(state, "retrieve_quality_documents", f"{len(result.get('results', []))} refs")
    return {"knowledge": result}


def has_data(state: QualityState) -> Literal["report", "analyze", "task_tool"]:
    if not state.get("filtered_records"):
        return "report"
    return "analyze" if state["task"] == "quality_analysis" else "task_tool"


def _initial_baseline(state: QualityState) -> dict[str, float | int]:
    return state.get("baseline") or calculate_defect_rate([])


def _evidence_refs(report: dict[str, object]) -> list[str]:
    refs: list[str] = []
    result = report.get("tool_result") or {}
    if result.get("evidence"):
        refs.append("tool_result.evidence")
    baseline = report.get("baseline") or {}
    for key in ("total_count", "defect_count", "defect_rate_percent"):
        if key in baseline:
            refs.append(f"baseline.{key}")
    for index, factor in enumerate(report.get("top_factors", [])):
        if factor.get("evidence"):
            refs.append(f"top_factors[{index}].evidence")
    for index, item in enumerate(report.get("knowledge_refs", [])):
        if isinstance(item, dict) and item.get("doc") and item.get("section"):
            refs.append(f"knowledge_refs[{index}]")
    return refs


def _number_tokens(value: object) -> set[Decimal]:
    if isinstance(value, bool) or value is None:
        return set()
    if isinstance(value, (int, float)):
        number = Decimal(str(value))
        return _rounded_numbers(number)
    if isinstance(value, dict):
        return set().union(*(_number_tokens(item) for item in value.values())) if value else set()
    if isinstance(value, (list, tuple)):
        return set().union(*(_number_tokens(item) for item in value)) if value else set()
    numbers: set[Decimal] = set()
    for token in re.findall(r"[-+]?\d+(?:\.\d+)?", str(value)):
        try:
            numbers.update(_rounded_numbers(Decimal(token)))
        except InvalidOperation:
            continue
    return numbers


def _rounded_numbers(number: Decimal) -> set[Decimal]:
    accepted = {number.normalize()}
    for places in range(0, 7):
        quantizer = Decimal(1).scaleb(-places)
        accepted.add(number.quantize(quantizer, rounding=ROUND_HALF_UP).normalize())
    return accepted


def _explanation_evidence(report: dict[str, object]) -> dict[str, object]:
    """Keep the model prompt small and express every rate with an explicit unit."""

    baseline = report.get("baseline") or {}
    baseline_fields = ("total_count", "defect_count", "defect_rate_percent")
    compact_baseline = {key: baseline[key] for key in baseline_fields if key in baseline}

    compact_factors = []
    # The report still shows three deterministic candidates; one is enough for
    # a concise model explanation and substantially limits generation time.
    for factor in report.get("top_factors", [])[:1]:
        item = {
            key: factor[key]
            for key in ("dimension", "value", "sample_count", "defect_count", "defect_rate_percent", "evidence")
            if key in factor
        }
        if "rate_difference" in factor:
            item["rate_difference_percentage_points"] = round(
                float(factor["rate_difference"]) * 100, 2
            )
        compact_factors.append(item)

    tool_result = report.get("tool_result") or {}
    tool_fields = (
        "status", "evidence", "row_count", "result_count", "sample_count", "anomaly_count",
        "anomaly_rate_percent", "mean", "std", "cp", "cpk", "cpu", "cpl", "usl", "lsl",
        "ucl", "lcl", "total_defects", "change_date", "before_rate_percent",
        "after_rate_percent", "change_percent", "window",
    )
    compact_tool_result = {key: tool_result[key] for key in tool_fields if key in tool_result}
    if isinstance(tool_result.get("items"), list):
        compact_tool_result["items"] = [
            {key: item[key] for key in ("defect_type", "count", "percent", "cumulative_percent") if key in item}
            for item in tool_result["items"][:3]
        ]

    compact_knowledge = []
    is_quality_analysis = report.get("task") == "quality_analysis"
    knowledge_limit = 1 if is_quality_analysis else 2
    snippet_limit = 220 if is_quality_analysis else 500
    for item in report.get("knowledge_refs", [])[:knowledge_limit]:
        snippet = item.get("snippet") or item.get("text") or ""
        compact_knowledge.append({
            "doc": item.get("doc"),
            "section": item.get("section"),
            "snippet": str(snippet)[:snippet_limit],
        })

    return {
        "filters": report.get("filters", {}),
        "data_scope": report.get("data_scope", {}),
        "baseline": compact_baseline,
        "tool_result": compact_tool_result,
        "top_factors": compact_factors,
        "knowledge_refs": compact_knowledge,
    }


def _default_explanation_citations(report: dict[str, object], allowed: list[str]) -> list[str]:
    """Select citations deterministically; small local models need not emit IDs."""

    preferred = []
    if report.get("task") == "quality_analysis":
        preferred.extend(("baseline.total_count", "baseline.defect_rate_percent"))
        if report.get("top_factors"):
            preferred.append("top_factors[0].evidence")
    else:
        preferred.append("tool_result.evidence")
        preferred.extend(ref for ref in allowed if ref.startswith("knowledge_refs["))
    preferred.extend(allowed)
    return list(dict.fromkeys(ref for ref in preferred if ref in allowed))[:3]


def _fallback_explanation(report: dict[str, object]) -> str:
    if report.get("status") == "needs_input":
        return "需要补充：" + "、".join(report.get("missing_inputs", [])) + "。"
    result = report.get("tool_result") or {}
    evidence = result.get("evidence")
    if evidence:
        return str(evidence)
    task = str(report.get("task", "quality_analysis"))
    baseline = report.get("baseline") or {}
    if task == "quality_analysis" and baseline.get("total_count"):
        return (
            f"共分析 {baseline['total_count']} 条记录，不良率为 "
            f"{float(baseline['defect_rate_percent']):.2f}%。"
        )
    if task == "knowledge":
        refs = report.get("knowledge_refs", [])
        if refs:
            return "检索到知识库条目，请按引用核对原文。"
        return str(report.get("knowledge_summary", "未检索到知识库引用。"))
    return str(report.get("summary", "没有足够证据生成解释。"))


def _explain(
    report: dict[str, object],
    model_fn: object,
    trace_fn: Callable | None = None,
) -> tuple[str, list[str], str, str | None]:
    allowed = _evidence_refs(report)
    if callable(model_fn) and report.get("status") != "needs_input":
        try:
            request = {
                "stage": "explain",
                "task": report.get("task"),
                "question": report.get("question"),
                "evidence": _explanation_evidence(report),
                "response_style": report.get("response_style", "standard"),
                "allowed_citations": allowed,
            }
            invoke = trace_fn("quality_agent_explanation", model_fn) if trace_fn else model_fn
            answer = invoke(request)
            if not isinstance(answer, dict):
                raise ValueError("model response must be an object")
            text = answer.get("text", answer.get("explanation"))
            citations = answer.get("citations")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("model explanation is empty")
            normalized_citations = []
            if citations:
                if not isinstance(citations, list):
                    raise ValueError("model citations must be a list")
                for item in citations:
                    if not isinstance(item, str):
                        raise ValueError("model cited evidence outside the report")
                    parent = next(
                        (
                            ref for ref in allowed
                            if item == ref or item.startswith((f"{ref}.", f"{ref}["))
                        ),
                        None,
                    )
                    if parent is None:
                        raise ValueError("model cited evidence outside the report")
                    normalized_citations.append(parent)
            if not normalized_citations:
                normalized_citations = _default_explanation_citations(report, allowed)
            supported_numbers = _number_tokens(
                {
                    "baseline": report.get("baseline"),
                    "tool_result": report.get("tool_result"),
                    "top_factors": report.get("top_factors"),
                    "knowledge_refs": report.get("knowledge_refs"),
                }
            )
            supported_numbers.update(_number_tokens(report.get("question")))
            supported_numbers.update(_number_tokens(report.get("filters")))
            # Candidate rate differences are stored as proportions; allow the
            # same deterministic difference when the explanation states points.
            for factor in report.get("top_factors", []):
                try:
                    supported_numbers.update(
                        _number_tokens(float(factor["rate_difference"]) * 100)
                    )
                except (KeyError, TypeError, ValueError):
                    continue
            stated_numbers = {
                Decimal(token).normalize()
                for token in re.findall(r"[-+]?\d+(?:\.\d+)?", text)
            }
            if not stated_numbers.issubset(supported_numbers):
                raise ValueError("model explanation contains unsupported numbers")
            from .conversation import explicit_filter_patch

            filters = report.get("filters") or {}
            mentioned_scope = explicit_filter_patch(text, filters)
            for key, exceeds in (("start_date", lambda stated, bound: stated < bound),
                                 ("end_date", lambda stated, bound: stated > bound)):
                stated, bound = mentioned_scope.get(key), filters.get(key)
                if stated and bound and exceeds(str(stated), str(bound)):
                    raise ValueError("model explanation exceeds the applied date range")
            lines = filters.get("production_line") or []
            lines = lines if isinstance(lines, list) else [lines]
            if lines and not set(mentioned_scope.get("production_line") or []).issubset(lines):
                raise ValueError("model explanation exceeds the applied production lines")
            return text.strip(), list(dict.fromkeys(normalized_citations)), "model", None
        except Exception as error:
            return (
                _fallback_explanation(report),
                [],
                "fallback",
                f"explanation fallback: {type(error).__name__}: {str(error)[:200]}",
            )
    return (
        _fallback_explanation(report),
        [
            ref
            for ref in allowed
            if ref.startswith(("tool_result", "baseline", "knowledge_refs"))
        ][:3],
        "deterministic",
        None,
    )


def report_node(state: QualityState, trace_fn: Callable | None = None) -> dict[str, object]:
    from agent.workflow import _recommendation

    task = state.get("task", "quality_analysis")
    filtered = state.get("filtered_records", [])
    baseline = _initial_baseline(state)
    candidates = state.get("candidates", [])
    factors = [
        {**factor, "recommendation": _recommendation(str(factor["dimension"]))}
        for factor in candidates[:3]
    ]
    knowledge = state.get("knowledge") or {"status": "no_results", "results": [], "metadata": {}}
    refs = knowledge.get("results", [])
    if knowledge.get("status") == "success":
        knowledge_summary = "知识库引用：" + "、".join(
            f"{item['doc']}（{item['section']}）" for item in refs
        )
    else:
        knowledge_summary = "未检索到与问题相关的知识库文档，以下结论仅基于数据分析。"

    missing = state.get("missing_inputs", [])
    tool_result = state.get("tool_result") or {}
    if task == "knowledge" and not missing:
        tool_result = {
            "status": knowledge.get("status", "no_results"),
            "result_count": len(refs),
            "evidence": knowledge_summary,
            "references": refs,
        }
    if missing:
        status = "needs_input"
        if state.get("parse_error"):
            summary = state.get("clarification") or (
                "Ollama 未能可靠解析问题，本次没有执行统计。请确认本地模型可用后重试。"
            )
        else:
            summary = "缺少完成该任务所需的输入：" + "、".join(missing) + "。"
        if not state.get("preserve_partial_evidence"):
            tool_result = {"status": "needs_input", "missing_inputs": missing}
            baseline = calculate_defect_rate([])
            factors = []
    elif task == "quality_analysis" and not filtered:
        status = "no_data"
        summary = "没有符合条件的生产记录，无法生成质量结论。"
    elif task == "sql" and tool_result.get("status") == "error":
        status = "error"
        summary = str(tool_result.get("error", "只读数据查询失败。"))
    elif task == "sql" and not tool_result.get("row_count"):
        status = "no_data"
        summary = "只读查询没有返回符合条件的生产记录。"
    elif task != "knowledge" and not filtered:
        status = "no_data"
        summary = "没有符合条件的生产记录，无法生成质量结论。"
    elif task == "quality_analysis":
        status = "success"
        factor_text = "；".join(f"{item['dimension']}={item['value']}" for item in factors)
        summary = (
            f"共分析 {baseline['total_count']} 条记录，不良率为 "
            f"{float(baseline['defect_rate_percent']):.2f}%。"
        )
        summary += f" 候选因素：{factor_text}。" if factor_text else " 当前数据没有满足最小样本量的候选因素。"
    else:
        status = "success"
        summary = str(tool_result.get("evidence") or f"{TASK_LABELS.get(task, task)}已完成。")

    response_style = "standard"
    for preference in state.get("confirmed_preferences", []):
        if not isinstance(preference, dict) or preference.get("memory_key") != "report_style":
            continue
        content = preference.get("content")
        value = content.get("value") if isinstance(content, dict) else None
        if value in {"conclusion_first", "standard"}:
            response_style = str(value)
            break

    report: dict[str, object] = {
        "status": status,
        "question": state["question"],
        "filters": state.get("filters", {}),
        "baseline": baseline,
        "top_factors": factors,
        "requires_human_review": status == "success" and task in {"quality_analysis", "cpk", "spc", "anomaly"},
        "summary": summary,
        "task": task,
        "task_label": TASK_LABELS.get(task, task),
        "response_style": response_style,
        "tool_result": tool_result,
        "missing_inputs": missing,
        "interpretation": state.get("interpretation", ""),
        "clarification": state.get("clarification", ""),
        "parse_error": state.get("parse_error"),
        "date_filter_requested": state.get("date_filter_requested", False),
        "knowledge_refs": refs,
        "knowledge_summary": knowledge_summary,
        "knowledge_metadata": knowledge.get("metadata", {}),
        "llm_status": state.get("llm_status", "disabled"),
        "tracing_status": state.get("tracing_status", "disabled"),
    }
    if task != "knowledge":
        scope_records = filtered
        if not scope_records and not missing:
            try:
                scope_records = filter_records(state.get("records", []), **state.get("filters", {}))
            except (TypeError, ValueError):
                scope_records = filtered
        dates = []
        for record in scope_records:
            try:
                dates.append(date.fromisoformat(str(record.get("timestamp", ""))[:10]))
            except (AttributeError, TypeError, ValueError):
                continue
        report["data_scope"] = {
            "matched_count": len(scope_records),
            "source_count": len(state.get("records", [])),
            "actual_start_date": min(dates).isoformat() if dates else None,
            "actual_end_date": max(dates).isoformat() if dates else None,
        }
    if task == "quality_analysis" and status == "success":
        report["charts"] = quality_chart_data(filtered)
        report["limitations"] = [
            "候选因素基于统计差异排序，不等同于已证明的因果关系。",
            "建议结合现场设备、工艺和维修记录进行人工确认。",
        ]
    if status == "needs_input":
        explanation, citations, explanation_source, model_issue = summary, [], "deterministic", None
    else:
        explanation, citations, explanation_source, model_issue = _explain(
            report, state.get("model_fn"), trace_fn=trace_fn
        )
    report["explanation"] = explanation
    report["explanation_citations"] = citations
    report["explanation_source"] = explanation_source
    if model_issue:
        report["llm_status"] = f"{report['llm_status']}; {model_issue}"
    _trace(state, "generate_report", status)
    return {"report": report}


def next_task(state: QualityState) -> Literal["report", "sql", "knowledge", "query"]:
    if state.get("missing_inputs"):
        return "report"
    if state["task"] == "sql":
        return "sql"
    if state["task"] == "knowledge":
        return "knowledge"
    return "query"


def build_graph(
    parse_fn=None,
    trace_fn: Callable | None = None,
    memory_lookup_fn: Callable[[dict[str, object]], dict[str, object]] | None = None,
):
    """Build a graph with Ollama question parsing and deterministic tool execution."""

    from langgraph.graph import END, START, StateGraph

    from agent.llm_parser import make_parse_fn

    resolve_parse = parse_fn or make_parse_fn("ollama")

    def parse(state: QualityState) -> dict[str, object]:
        return parse_node(state, resolve_parse, memory_lookup_fn)

    def report(state: QualityState) -> dict[str, object]:
        return report_node(state, trace_fn=trace_fn)

    trace_instrument = trace_fn or (lambda _name, fn: fn)

    def instrument(name, fn):
        traced = trace_instrument(name, fn)
        def measured(state):
            progress = state.get("progress_fn")
            if callable(progress):
                progress(name, "start", None)
            started = time.perf_counter()
            result = traced(state)
            elapsed = round((time.perf_counter() - started) * 1000, 2)
            timings = {**state.get("stage_timings", {}), name: elapsed}
            result["stage_timings"] = timings
            if "report" in result:
                result["report"]["stage_timings"] = timings
            if callable(progress):
                progress(name, "complete", elapsed)
            partial_report = state.get("partial_report_fn")
            if (
                name == "quality_agent_statistics_tool"
                and state.get("task") == "quality_analysis"
                and callable(partial_report)
            ):
                partial_report(
                    {
                        "filters": state.get("filters", {}),
                        "baseline": result.get("baseline", {}),
                        "top_factors": result.get("candidates", []),
                    }
                )
            return result
        return measured

    graph = StateGraph(QualityState)
    graph.add_node("parse", instrument("quality_agent_route", parse))
    graph.add_node("query", instrument("quality_agent_filter_tool", query_node))
    graph.add_node("analyze", instrument("quality_agent_statistics_tool", analyze_node))
    graph.add_node("task_tool", instrument("quality_agent_domain_tool", task_tool_node))
    graph.add_node("sql", instrument("quality_agent_readonly_sql_tool", sql_node))
    graph.add_node("knowledge", instrument("quality_agent_retrieval", knowledge_node))
    graph.add_node("report", instrument("quality_agent_report", report))
    graph.add_edge(START, "parse")
    graph.add_conditional_edges(
        "parse",
        next_task,
        {"report": "report", "sql": "sql", "knowledge": "knowledge", "query": "query"},
    )
    graph.add_conditional_edges(
        "query",
        has_data,
        {"report": "report", "analyze": "analyze", "task_tool": "task_tool"},
    )
    graph.add_edge("analyze", "knowledge")
    graph.add_edge("task_tool", "knowledge")
    graph.add_edge("sql", "report")
    graph.add_edge("knowledge", "report")
    graph.add_edge("report", END)
    return graph.compile()
