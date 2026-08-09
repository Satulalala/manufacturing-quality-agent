"""X-bar control chart limits and out-of-control point detection."""

from __future__ import annotations

import math
from typing import Iterable


def _sample_std(values: list[float]) -> float:
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def spc_control_limits(
    values: Iterable[float],
    min_samples: int = 10,
) -> dict[str, object]:
    """Compute mean +/- 3 sample-sigma control lines and flag excursions."""

    samples = [float(value) for value in values]
    if len(samples) < min_samples:
        return {
            "status": "insufficient",
            "sample_count": len(samples),
            "out_of_control": [],
            "evidence": f"样本不足（{len(samples)} < {min_samples}），不绘制控制线。",
        }

    mean = sum(samples) / len(samples)
    std = _sample_std(samples)
    ucl = mean + 3 * std
    lcl = mean - 3 * std

    out_of_control = [
        {
            "index": index,
            "value": value,
            "side": "upper" if value > ucl else "lower",
        }
        for index, value in enumerate(samples)
        if value > ucl or value < lcl
    ]

    status = "success" if out_of_control else "in_control"
    return {
        "status": status,
        "sample_count": len(samples),
        "mean": mean,
        "std": std,
        "ucl": ucl,
        "lcl": lcl,
        "out_of_control": out_of_control,
        "evidence": (
            f"控制线：{lcl:.3f} ~ {ucl:.3f}（均值 {mean:.3f} ± 3σ，σ={std:.3f}）；"
            f"超限点 {len(out_of_control)} 个。"
        ),
    }
