"""Agent-facing wrappers for Pareto, Cpk, and SPC analytics.

Each tool returns the analysis result plus a Chinese inspection
recommendation, matching the style of the other Agent tools.
"""

from __future__ import annotations

from typing import Iterable, Mapping

from analytics.pareto import pareto_analysis
from analytics.process_capability import calculate_cpk
from analytics.spc_analysis import spc_control_limits


Record = Mapping[str, object]

CAPABILITY_SPECS = {
    "temperature": (23.0, 17.0),
    "pressure": (115.0, 85.0),
    "torque": (50.0, 40.0),
}


def analyze_pareto(records: Iterable[Record], defect_field: str = "defect_type") -> dict[str, object]:
    """Rank defect types by count and attach a recommendation."""

    result = pareto_analysis(records, defect_field=defect_field)
    if result["status"] == "success":
        top = str(result["items"][0]["defect_type"])
        result["recommendation"] = (
            f"优先排查占比最高的缺陷类型「{top}」，结合缺陷代码手册定位根因；"
            "对累计占比前 80% 的类型做专项改善。"
        )
    else:
        result["recommendation"] = "暂无缺陷数据，无需 Pareto 分析。"
    return result


def analyze_process_capability(
    records: Iterable[Record],
    field: str = "torque",
    usl: float | None = None,
    lsl: float | None = None,
) -> dict[str, object]:
    """Compute Cpk for one process parameter and attach a recommendation."""

    resolved_usl, resolved_lsl = CAPABILITY_SPECS.get(field, (None, None))
    if usl is None:
        usl = resolved_usl
    if lsl is None:
        lsl = resolved_lsl
    if usl is None or lsl is None:
        return {
            "status": "missing_specs",
            "evidence": f"参数「{field}」没有默认规格，请传入 usl/lsl。",
            "recommendation": "提供规格上下限后重新计算。",
        }

    values = []
    for record in records:
        raw = record.get(field)
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            continue

    result = calculate_cpk(values, usl=usl, lsl=lsl)
    recommendations = {
        "capable": "工艺能力充分（Cpk≥1.33），维持现状并持续监控。",
        "marginal": "工艺能力临界（1.0≤Cpk<1.33），建议收紧过程控制、排查波动来源。",
        "not_capable": "工艺能力不足（Cpk<1.0），需立即排查设备、工装或参数偏移。",
        "constant": "数据无波动，先确认采集是否正常。",
        "insufficient": "样本不足，补充数据后再评估。",
    }
    result["recommendation"] = recommendations.get(result["status"], "结合现场确认。")
    return result


def analyze_spc(records: Iterable[Record], field: str = "pressure") -> dict[str, object]:
    """Build control limits for one parameter and flag excursions."""

    values = []
    for record in records:
        raw = record.get(field)
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            continue

    result = spc_control_limits(values)
    if result["status"] == "success":
        points = len(result["out_of_control"])
        result["recommendation"] = (
            f"检出 {points} 个超控制线点，建议按时间顺序回溯对应工位、批次与设备状态；"
            "确认是否为持续偏移（排查参数漂移）或偶发扰动（排查来料/换型）。"
        )
    elif result["status"] == "in_control":
        result["recommendation"] = "过程在控制状态内，无超限点，持续监控即可。"
    else:
        result["recommendation"] = "样本不足，补充数据后重新计算。"
    return result
