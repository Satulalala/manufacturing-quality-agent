"""Generate deterministic, synthetic production-quality records.

The injected patterns make the demo useful for testing root-cause ranking while
keeping the data clearly synthetic and safe to publish.
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path


FIELDNAMES = [
    "record_id",
    "timestamp",
    "vehicle_model",
    "production_line",
    "workstation",
    "shift",
    "supplier_id",
    "batch_id",
    "temperature",
    "pressure",
    "torque",
    "result",
    "defect_type",
]


def generate_records(count: int = 2400, seed: int = 42) -> list[dict[str, object]]:
    """Return deterministic records with a few known quality anomalies."""

    rng = random.Random(seed)
    start = date(2026, 1, 1)
    models = ("ID.4", "ID.7", "ID.BUZZ")
    lines = ("A", "B")
    workstations = tuple(f"W-{index:02d}" for index in range(1, 9))
    shifts = ("Day", "Night")
    suppliers = ("S-01", "S-02", "S-03", "S-04")
    defect_types = ("torque_low", "pressure_high", "temperature_drift")
    records: list[dict[str, object]] = []

    for index in range(count):
        current_date = start + timedelta(days=index % 31)
        workstation = rng.choice(workstations)
        shift = rng.choice(shifts)
        supplier = rng.choice(suppliers)
        line = rng.choice(lines)

        defect_probability = 0.025
        if workstation == "W-07":
            defect_probability += 0.13
        if shift == "Night":
            defect_probability += 0.045
        if supplier == "S-03":
            defect_probability += 0.035
        if current_date.day >= 24 and line == "A":
            defect_probability += 0.03

        is_defect = rng.random() < defect_probability
        defect_type = rng.choice(defect_types) if is_defect else ""
        records.append(
            {
                "record_id": f"R-{index + 1:05d}",
                "timestamp": f"{current_date.isoformat()} {rng.randrange(6, 22):02d}:{rng.randrange(60):02d}:00",
                "vehicle_model": rng.choice(models),
                "production_line": line,
                "workstation": workstation,
                "shift": shift,
                "supplier_id": supplier,
                "batch_id": f"B-{index // 40 + 1:03d}",
                "temperature": round(rng.gauss(22, 2.2), 2),
                "pressure": round(rng.gauss(100, 4.5), 2),
                "torque": round(rng.gauss(45, 3.0), 2),
                "result": "NG" if is_defect else "OK",
                "defect_type": defect_type,
            }
        )

    return records


def write_records(records: list[dict[str, object]], path: str | Path) -> Path:
    """Write records to CSV and return the resolved path."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(records)
    return destination.resolve()


def load_records(path: str | Path) -> list[dict[str, str]]:
    """Load CSV records as dictionaries."""

    with Path(path).open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
