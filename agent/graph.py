"""LangGraph orchestration for the quality Agent.

Nodes call the deterministic tools from ``analytics`` and ``tools`` and append
one ``TraceStep`` to ``state["trace"]`` per tool call, making the execution
order auditable. ``parse_question`` stays deterministic in this milestone;
a model-based parser can replace it without touching the graph shape.
"""

from __future__ import annotations

from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from analytics.quality_analysis import calculate_defect_rate, rank_candidate_causes
from tools.quality_tools import filter_records

from .state import QualityState


def _trace(state: QualityState, tool: str, detail: str) -> None:
    state["trace"].append({"tool": tool, "detail": detail})


def parse_node(state: QualityState) -> dict[str, object]:
    from agent.workflow import parse_question

    filters = parse_question(state["question"])
    _trace(state, "parse_question", str(filters))
    return {"filters": filters}


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
    return {"baseline": baseline, "candidates": ranked}


def knowledge_node(state: QualityState) -> dict[str, object]:
    from tools.knowledge_tool import retrieve_quality_documents

    dimensions = " ".join(str(factor["dimension"]) for factor in state.get("candidates", []))
    search_text = f"{state['question']} {dimensions}"
    result = retrieve_quality_documents(search_text, top_k=3)
    _trace(state, "retrieve_quality_documents", f"{len(result['results'])} refs")
    return {"knowledge": result}


def report_node(state: QualityState) -> dict[str, object]:
    from agent.workflow import _recommendation

    filtered = state["filtered_records"]
    if not filtered:
        report = {
            "status": "no_data",
            "question": state["question"],
            "filters": state["filters"],
            "baseline": calculate_defect_rate([]),
            "top_factors": [],
            "knowledge_refs": [],
            "knowledge_summary": "未检索到与问题相关的知识库文档，不编造来源。",
            "summary": "没有符合条件的生产记录，无法生成质量结论。",
        }
        _trace(state, "generate_report", "no_data")
        return {"report": report}

    baseline = state["baseline"]
    top_n = 3
    factors = [
        {**factor, "recommendation": _recommendation(str(factor["dimension"]))}
        for factor in state["candidates"][:top_n]
    ]
    factor_text = "；".join(f"{item['dimension']}={item['value']}" for item in factors)
    summary = (
        f"共分析 {baseline['total_count']} 条记录，不良率为 "
        f"{float(baseline['defect_rate_percent']):.2f}%。"
    )
    if factor_text:
        summary += f" 候选因素：{factor_text}。"
    else:
        summary += " 当前数据没有满足最小样本量的候选因素。"

    report = {
        "status": "success",
        "question": state["question"],
        "filters": state["filters"],
        "baseline": baseline,
        "top_factors": factors,
        "limitations": [
            "候选因素基于统计差异排序，不等同于已证明的因果关系。",
            "建议结合现场设备、工艺和维修记录进行人工确认。",
        ],
        "summary": summary,
    }
    knowledge = state.get("knowledge") or {"status": "no_results", "results": []}
    report["knowledge_refs"] = knowledge.get("results", [])
    if knowledge["status"] == "success":
        report["knowledge_summary"] = (
            "知识库引用：" + "、".join(f"{item['doc']}（{item['section']}）" for item in knowledge["results"])
        )
    else:
        report["knowledge_summary"] = "未检索到与问题相关的知识库文档，以下结论仅基于数据分析。"
    _trace(state, "generate_report", "success")
    return {"report": report}


def has_data(state: QualityState) -> Literal["report", "analyze"]:
    return "report" if not state.get("filtered_records") else "analyze"


def build_graph():
    """Build and compile the quality workflow graph."""

    graph = StateGraph(QualityState)
    graph.add_node("parse", parse_node)
    graph.add_node("query", query_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("knowledge", knowledge_node)
    graph.add_node("report", report_node)
    graph.add_edge(START, "parse")
    graph.add_edge("parse", "query")
    graph.add_conditional_edges("query", has_data, {"report": "report", "analyze": "analyze"})
    graph.add_edge("analyze", "knowledge")
    graph.add_edge("knowledge", "report")
    graph.add_edge("report", END)
    return graph.compile()
