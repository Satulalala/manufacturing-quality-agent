"""Small, deterministic quality-analysis primitives.

The Agent calls these functions as tools. Keeping the calculations independent
from the LLM makes the important numbers reproducible and testable.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable, Mapping


Record = Mapping[str, object]


def _is_defect(record: Record) -> bool:
    result = record.get("result")
    if isinstance(result, bool):
        return not result
    return str(result).strip().upper() in {"NG", "FAIL", "DEFECT", "NOK"}


def calculate_defect_rate(records: Iterable[Record]) -> dict[str, float | int]:
    """Return counts and defect rate for a collection of production records."""

    records = list(records)
    total_count = len(records)
    defect_count = sum(1 for record in records if _is_defect(record))
    defect_rate = defect_count / total_count if total_count else 0.0

    return {
        "total_count": total_count,
        "defect_count": defect_count,
        "defect_rate": defect_rate,
        "defect_rate_percent": defect_rate * 100,
    }


def compare_groups(records: Iterable[Record], group_by: str) -> list[dict[str, object]]:
    """Compare defect rates for one categorical dimension."""

    groups: dict[str, list[Record]] = defaultdict(list)
    for record in records:
        value = record.get(group_by)
        if value is not None and str(value).strip():
            groups[str(value)].append(record)

    results: list[dict[str, object]] = []
    for group_value, group_records in groups.items():
        stats = calculate_defect_rate(group_records)
        results.append(
            {
                "group_by": group_by,
                "group_value": group_value,
                **stats,
            }
        )

    return sorted(
        results,
        key=lambda item: (-float(item["defect_rate"]), -int(item["total_count"]), str(item["group_value"])),
    )


def rank_candidate_causes(
    records: Iterable[Record],
    dimensions: tuple[str, ...] = ("workstation", "shift", "supplier_id", "batch_id"),
    min_samples: int = 20,
) -> list[dict[str, object]]:
    """Rank groups with unusually high defect rates.

    This is a prioritization heuristic, not causal inference. The sample-size
    factor prevents tiny groups from dominating the ranking.
    """

    records = list(records)
    baseline = calculate_defect_rate(records)
    baseline_rate = float(baseline["defect_rate"])
    candidates: list[dict[str, object]] = []

    for dimension in dimensions:
        for group in compare_groups(records, dimension):
            sample_count = int(group["total_count"])
            if sample_count < min_samples:
                continue

            rate = float(group["defect_rate"])
            rate_difference = rate - baseline_rate
            lift = rate / baseline_rate if baseline_rate else (math.inf if rate else 0.0)
            evidence = (
                f"{dimension}={group['group_value']} has "
                f"{rate * 100:.2f}% defects across {sample_count} records; "
                f"overall rate is {baseline_rate * 100:.2f}%"
            )
            candidates.append(
                {
                    "dimension": dimension,
                    "value": group["group_value"],
                    "sample_count": sample_count,
                    "defect_count": int(group["defect_count"]),
                    "defect_rate": rate,
                    "defect_rate_percent": rate * 100,
                    "baseline_defect_rate": baseline_rate,
                    "rate_difference": rate_difference,
                    "lift": lift,
                    "priority_score": rate_difference * math.sqrt(sample_count),
                    "evidence": evidence,
                }
            )

    return sorted(
        candidates,
        key=lambda item: (
            -float(item["priority_score"]),
            -float(item["defect_rate"]),
            -int(item["sample_count"]),
            str(item["dimension"]),
            str(item["value"]),
        ),
    )
