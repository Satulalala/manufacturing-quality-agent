"""Deterministic trend-change detection for daily defect rates.

Compares, for each day, the mean defect rate of the ``window`` days before it
with the ``window`` days from it onward. The day with the largest positive
change is the candidate change point. Days below ``min_daily_samples`` are
excluded so that tiny samples cannot create false alarms.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Mapping


Record = Mapping[str, object]


def _is_defect(record: Record) -> bool:
    result = record.get("result")
    if isinstance(result, bool):
        return not result
    return str(result).strip().upper() in {"NG", "FAIL", "DEFECT", "NOK"}


def _aggregate_daily(records: list[Record], min_daily_samples: int) -> list[dict[str, int | str]]:
    per_day: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for record in records:
        day = str(record.get("timestamp", ""))[:10]
        if not day:
            continue
        per_day[day][0] += 1
        if _is_defect(record):
            per_day[day][1] += 1

    daily: list[dict[str, int | str]] = []
    for day in sorted(per_day):
        total, defects = per_day[day]
        if total >= min_daily_samples:
            daily.append({"date": day, "total": total, "defect_count": defects})
    return daily


def detect_trend_change(
    records: Iterable[Record],
    window: int = 7,
    min_daily_samples: int = 10,
) -> dict[str, object]:
    """Find the date where the daily defect rate jumps most between windows."""

    records = list(records)
    daily = _aggregate_daily(records, min_daily_samples)
    for row in daily:
        total = int(row["total"])
        row["defect_rate_percent"] = round(int(row["defect_count"]) / total * 100, 6)

    best: dict[str, object] | None = None
    for index in range(window, len(daily) - window + 1):
        before = daily[index - window : index]
        after = daily[index : index + window]
        before_rate = sum(float(row["defect_rate_percent"]) for row in before) / window
        after_rate = sum(float(row["defect_rate_percent"]) for row in after) / window
        change = after_rate - before_rate
        if best is None or change > float(best["change_percent"]):
            best = {
                "change_date": daily[index]["date"],
                "before_rate_percent": round(before_rate, 6),
                "after_rate_percent": round(after_rate, 6),
                "change_percent": round(change, 6),
            }

    if best is None or float(best["change_percent"]) <= 0:
        return {
            "status": "no_change",
            "change_date": None,
            "before_rate_percent": None,
            "after_rate_percent": None,
            "change_percent": 0.0,
            "window": window,
            "daily_rates": daily,
            "evidence": "未检测到明显的不良率趋势跳变。",
        }

    before_index = daily.index(next(row for row in daily if row["date"] == best["change_date"]))
    before_start = daily[before_index - window]["date"]
    after_end = daily[before_index + window - 1]["date"]
    return {
        "status": "change_detected",
        "change_date": best["change_date"],
        "before_rate_percent": best["before_rate_percent"],
        "after_rate_percent": best["after_rate_percent"],
        "change_percent": best["change_percent"],
        "window": window,
        "daily_rates": daily,
        "evidence": (
            f"前{window}天（{before_start}~{best['change_date']}）不良率均值 "
            f"{best['before_rate_percent']:.2f}%，后{window}天（{best['change_date']}~{after_end}）"
            f"{best['after_rate_percent']:.2f}%，跳变 {best['change_percent']:+.2f} 个百分点。"
        ),
    }
