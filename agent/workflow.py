"""A deterministic local quality Agent workflow.

This is intentionally LLM-free in the first milestone. It establishes the
tool contract and report shape before adding model-based question parsing.
The workflow is orchestrated by the LangGraph state machine in ``agent.graph``;
this module keeps the public ``QualityAgent`` and text rendering API stable.
"""

from __future__ import annotations

import re
from typing import Iterable, Mapping

from agent.graph import build_graph
from agent.state import initial_state


Record = Mapping[str, object]

_DATE_PATTERN = re.compile(r"20\d{2}-\d{2}-\d{2}")
_LINE_PATTERNS = (
    re.compile(r"([A-Z])\s*产线", re.IGNORECASE),
    re.compile(r"产线\s*([A-Z])", re.IGNORECASE),
    re.compile(r"line\s*([A-Z])", re.IGNORECASE),
)


def parse_question(question: str) -> dict[str, str | None]:
    """Extract the limited filter vocabulary supported by the MVP."""

    dates = _DATE_PATTERN.findall(question)
    production_line = None
    for pattern in _LINE_PATTERNS:
        match = pattern.search(question)
        if match:
            production_line = match.group(1).upper()
            break

    return {
        "start_date": dates[0] if dates else None,
        "end_date": dates[1] if len(dates) > 1 else (dates[0] if dates else None),
        "production_line": production_line,
    }


def _recommendation(dimension: str) -> str:
    recommendations = {
        "workstation": "优先检查该工位的设备参数、工装状态和最近换型记录。",
        "shift": "对比该班次的交接班记录、人员配置和作业参数。",
        "supplier_id": "核查该供应商批次、来料检验记录和近期变更。",
        "batch_id": "追溯该批次的原料、工艺参数和维修记录。",
    }
    return recommendations.get(dimension, "结合现场记录进行人工确认。")


class QualityAgent:
    """Coordinate deterministic quality tools and produce an evidence report."""

    def __init__(self, records: Iterable[Record], llm_provider: str | None = None):
        self.records = [dict(record) for record in records]
        if llm_provider is not None:
            from agent.llm_parser import make_parse_fn

            self.graph = build_graph(parse_fn=make_parse_fn(llm_provider))
        else:
            self.graph = build_graph()

    def answer(self, question: str, top_n: int = 3) -> dict[str, object]:
        state = self.graph.invoke(
            initial_state(self.records, question),
            config={"recursion_limit": 20},
        )
        report = state["report"]
        if report["status"] == "success":
            report["top_factors"] = report["top_factors"][:top_n]
        report["trace"] = state["trace"]
        return report


def render_text_report(report: Mapping[str, object]) -> str:
    """Render a report for the command line and README screenshots."""

    lines = [f"状态：{report['status']}", f"结论：{report['summary']}"]
    baseline = report["baseline"]
    lines.append(
        f"数据：{baseline['total_count']} 条，缺陷 {baseline['defect_count']} 条，"
        f"不良率 {float(baseline['defect_rate_percent']):.2f}%"
    )
    factors = report["top_factors"]
    if factors:
        lines.append("候选因素：")
        for index, factor in enumerate(factors, start=1):
            lines.append(
                f"{index}. {factor['dimension']}={factor['value']}，"
                f"不良率 {float(factor['defect_rate_percent']):.2f}%，"
                f"样本 {factor['sample_count']}；{factor['recommendation']}"
            )
            lines.append(f"   证据：{factor['evidence']}")
    for limitation in report.get("limitations", []):
        lines.append(f"提示：{limitation}")
    if report.get("knowledge_refs"):
        lines.append("知识库引用：")
        for item in report["knowledge_refs"]:
            lines.append(f"- {item['doc']}（{item['section']}）")
    elif report.get("knowledge_summary"):
        lines.append(f"知识库：{report['knowledge_summary']}")
    if report.get("trace"):
        lines.append("调用链：" + " → ".join(step["tool"] for step in report["trace"]))
    return "\n".join(lines)
