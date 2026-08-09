"""Pareto analysis over defect types (the 80/20 lens for quality)."""

from __future__ import annotations

from collections import Counter
from typing import Iterable, Mapping


Record = Mapping[str, object]


def _is_defect(record: Record) -> bool:
    result = record.get("result")
    if isinstance(result, bool):
        return not result
    return str(result).strip().upper() in {"NG", "FAIL", "DEFECT", "NOK"}


def pareto_analysis(
    records: Iterable[Record],
    defect_field: str = "defect_type",
) -> dict[str, object]:
    """Rank defect types by count with percent and cumulative percent."""

    counts: Counter[str] = Counter()
    for record in records:
        if not _is_defect(record):
            continue
        defect_type = str(record.get(defect_field, "")).strip() or "unknown"
        counts[defect_type] += 1

    total_defects = sum(counts.values())
    if total_defects == 0:
        return {
            "status": "no_defects",
            "total_defects": 0,
            "items": [],
            "evidence": "当前数据中没有缺陷记录，无法进行 Pareto 分析。",
        }

    items: list[dict[str, object]] = []
    running = 0
    for defect_type, count in counts.most_common():
        running += count
        items.append(
            {
                "defect_type": defect_type,
                "count": count,
                "percent": round(count / total_defects * 100, 4),
                "cumulative_percent": round(running / total_defects * 100, 4),
            }
        )

    top_types = "、".join(str(item["defect_type"]) for item in items[:3])
    return {
        "status": "success",
        "total_defects": total_defects,
        "items": items,
        "evidence": (
            f"共 {total_defects} 条缺陷；前 3 类：{top_types}。"
            f"前两类累计 {items[1]['cumulative_percent'] if len(items) > 1 else 100.0:.1f}%。"
        ),
    }
