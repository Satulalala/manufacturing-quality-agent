"""Deterministic chart payloads for quality analysis reports."""

from __future__ import annotations

from analytics.pareto import pareto_analysis
from analytics.trend_analysis import detect_trend_change


def quality_chart_data(records: list[dict[str, object]]) -> dict[str, object]:
    daily_rates = detect_trend_change(records, min_daily_samples=1)["daily_rates"]
    monthly = len(daily_rates) > 366
    buckets: dict[str, list[int]] = {}
    points: list[dict[str, object]] = []
    for row in daily_rates:
        period = str(row["date"])[:7] if monthly else str(row["date"])
        if monthly:
            bucket = buckets.setdefault(period, [0, 0])
            bucket[0] += int(row["total"])
            bucket[1] += int(row["defect_count"])
        else:
            total = int(row["total"])
            defects = int(row["defect_count"])
            points.append({
                "period": period,
                "total": total,
                "defect_count": defects,
                "defect_rate_percent": round(defects / total * 100, 4) if total else 0.0,
            })
    if monthly:
        for period, (total, defects) in sorted(buckets.items()):
            points.append({
                "period": period,
                "total": total,
                "defect_count": defects,
                "defect_rate_percent": round(defects / total * 100, 4) if total else 0.0,
            })
    return {
        "defect_trend": {
            "status": "success" if points else "no_data",
            "period_unit": "month" if monthly else "day",
            "points": points,
        },
        "defect_pareto": pareto_analysis(records),
    }
