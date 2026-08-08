"""Deterministic anomaly detection over numeric process parameters.

Uses an Isolation Forest with a fixed random seed so repeated runs produce
identical results. Records without valid numeric values for every requested
field are skipped; tiny inputs are reported as ``insufficient_data`` instead
of producing noisy signals.
"""

from __future__ import annotations

from typing import Iterable, Mapping

from sklearn.ensemble import IsolationForest


Record = Mapping[str, object]
DEFAULT_NUMERIC_FIELDS = ("temperature", "pressure", "torque")


def _extract_matrix(
    records: list[Record],
    numeric_fields: tuple[str, ...],
) -> tuple[list[dict[str, object]], list[list[float]]]:
    rows: list[dict[str, object]] = []
    matrix: list[list[float]] = []
    for record in records:
        values: list[float] = []
        valid = True
        for field in numeric_fields:
            raw = record.get(field)
            try:
                values.append(float(raw))
            except (TypeError, ValueError):
                valid = False
                break
        if valid:
            rows.append(record)
            matrix.append(values)
    return rows, matrix


def detect_anomalies(
    records: Iterable[Record],
    numeric_fields: tuple[str, ...] = DEFAULT_NUMERIC_FIELDS,
    contamination: float = 0.05,
    min_samples: int = 50,
) -> dict[str, object]:
    """Flag records whose numeric parameters look like outliers."""

    records = list(records)
    rows, matrix = _extract_matrix(records, numeric_fields)

    base = {
        "status": "insufficient_data",
        "sample_count": len(rows),
        "anomaly_count": 0,
        "anomaly_rate_percent": 0.0,
        "anomalies": [],
        "evidence": f"样本不足（{len(rows)} < {min_samples}），不进行异常检测。",
    }
    if len(rows) < min_samples:
        return base

    model = IsolationForest(contamination=contamination, random_state=42)
    flags = model.fit_predict(matrix)
    anomalies = [
        {
            "record_id": str(record["record_id"]),
            "timestamp": str(record.get("timestamp", "")),
            "production_line": str(record.get("production_line", "")),
            "workstation": str(record.get("workstation", "")),
            **{field: matrix[index][field_index] for field_index, field in enumerate(numeric_fields)},
        }
        for index, (record, flag) in enumerate(zip(rows, flags))
        if int(flag) == -1
    ]
    anomalies.sort(key=lambda row: row["record_id"])

    return {
        "status": "success",
        "sample_count": len(rows),
        "anomaly_count": len(anomalies),
        "anomaly_rate_percent": round(len(anomalies) / len(rows) * 100, 6),
        "anomalies": anomalies,
        "evidence": (
            f"Isolation Forest 检出 {len(anomalies)}/{len(rows)} 条参数异常记录，"
            f"字段：{', '.join(numeric_fields)}。"
        ),
    }
