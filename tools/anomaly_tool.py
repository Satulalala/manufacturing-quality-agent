"""Agent-facing wrappers around the trend and anomaly analytics.

Each tool returns a structured dict plus a human-readable recommendation, so
a later LLM layer can attach the recommendation to its report without
re-computing anything.
"""

from __future__ import annotations

from typing import Iterable, Mapping

from analytics.anomaly_detection import DEFAULT_NUMERIC_FIELDS, detect_anomalies
from analytics.trend_analysis import detect_trend_change


Record = Mapping[str, object]


def analyze_trend(
    records: Iterable[Record],
    window: int = 7,
    min_daily_samples: int = 10,
) -> dict[str, object]:
    """Detect defect-rate trend jumps and attach an inspection recommendation."""

    result = detect_trend_change(records, window=window, min_daily_samples=min_daily_samples)
    if result["status"] == "change_detected":
        result["recommendation"] = (
            f"建议核对 {result['change_date']} 前后的换型记录、设备维护和来料变更，"
            "并对比当天各工位、班次的作业参数。"
        )
    else:
        result["recommendation"] = "当前数据未显示明显趋势跳变，无需专项排查。"
    return result


def analyze_anomalies(
    records: Iterable[Record],
    numeric_fields: tuple[str, ...] = DEFAULT_NUMERIC_FIELDS,
    contamination: float = 0.05,
    min_samples: int = 50,
    top_n: int = 10,
) -> dict[str, object]:
    """Flag numeric-parameter outliers and attach an inspection recommendation."""

    result = detect_anomalies(
        records,
        numeric_fields=numeric_fields,
        contamination=contamination,
        min_samples=min_samples,
    )
    if result["status"] == "success":
        result["anomalies"] = result["anomalies"][:max(top_n, 0)]
        top_workstations = sorted(
            {row["workstation"] for row in result["anomalies"] if row["workstation"]}
        )
        result["recommendation"] = (
            f"建议重点核查被标记记录的工位（{'、'.join(top_workstations) or '无'}）"
            "、批次和工艺参数，并与设备报警记录对照。"
        )
    else:
        result["recommendation"] = "样本不足，暂不进行参数异常检测。"
    return result
