"""Process capability index (Cp / Cpk) calculation."""

from __future__ import annotations

import math
from typing import Iterable


def _sample_std(values: list[float]) -> float:
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def calculate_cpk(
    values: Iterable[float],
    usl: float,
    lsl: float,
    min_samples: int = 5,
) -> dict[str, object]:
    """Compute Cp/Cpk and grade process capability.

    Grades: capable (>=1.33), marginal (>=1.0), not_capable (<1.0).
    """

    samples = [float(value) for value in values]
    if len(samples) < min_samples:
        return {
            "status": "insufficient",
            "sample_count": len(samples),
            "evidence": f"样本不足（{len(samples)} < {min_samples}），无法计算工艺能力。",
        }

    mean = sum(samples) / len(samples)
    std = _sample_std(samples)
    if std == 0:
        return {
            "status": "constant",
            "sample_count": len(samples),
            "mean": mean,
            "std": 0.0,
            "cp": None,
            "cpk": None,
            "evidence": "样本标准差为 0（数据恒定），工艺能力无法评估。",
        }

    cp = (float(usl) - float(lsl)) / (6 * std)
    cpu = (float(usl) - mean) / (3 * std)
    cpl = (mean - float(lsl)) / (3 * std)
    cpk = min(cpu, cpl)

    if cpk >= 1.33:
        status = "capable"
    elif cpk >= 1.0:
        status = "marginal"
    else:
        status = "not_capable"

    return {
        "status": status,
        "sample_count": len(samples),
        "mean": mean,
        "std": std,
        "cp": cp,
        "cpu": cpu,
        "cpl": cpl,
        "cpk": cpk,
        "usl": float(usl),
        "lsl": float(lsl),
        "evidence": (
            f"Cpk={cpk:.3f}（Cp={cp:.3f}，上限侧 {cpu:.3f}，下限侧 {cpl:.3f}），"
            f"均值 {mean:.2f}，标准差 {std:.3f}；判定：{status}。"
        ),
    }
