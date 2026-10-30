"""Generate deterministic, multi-year synthetic automotive quality datasets.

The records are fictional training data. Their fields model common production
traceability and quality-control concepts; they are not OEM records or a claim
of IATF 16949 certification.
"""

from __future__ import annotations

import csv
import random
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "data" / "datasets"
AS_OF = date(2026, 10, 18)
ROWS_BY_YEAR = {2022: 6000, 2023: 6000, 2024: 6000, 2025: 6000, 2026: 4500}

FIELDNAMES = [
    "record_id", "timestamp", "plant_code", "production_line", "workstation",
    "operation_code", "inspection_stage", "vehicle_model", "part_number",
    "serial_number", "shift", "operator_id", "equipment_id",
    "measurement_tool_id", "supplier_id", "supplier_lot", "batch_id",
    "control_plan_id", "control_plan_revision", "characteristic_id",
    "characteristic_name", "characteristic_class", "sampling_plan",
    "torque", "torque_unit", "torque_lsl", "torque_usl",
    "pressure", "pressure_unit", "pressure_lsl", "pressure_usl",
    "temperature", "temperature_unit", "temperature_lsl", "temperature_usl",
    "result", "defect_type", "defect_code", "severity", "disposition",
    "rework_flag", "reaction_plan_code", "traceability_status",
]

MODELS = {
    "M01-EV": "ASSY-M01-001",
    "M02-EV": "ASSY-M02-001",
    "M03-PHEV": "ASSY-M03-001",
}
SUPPLIERS = tuple(f"SUP-{index:03d}" for index in range(1, 9))
STATIONS = tuple(f"W-{index:02d}" for index in range(1, 13))
DEFECT_CODES = {
    "torque_low": "DF-TQ-L",
    "torque_high": "DF-TQ-H",
    "pressure_low": "DF-PR-L",
    "pressure_high": "DF-PR-H",
    "temperature_drift": "DF-TM-D",
    "weld_pore": "DF-WD-P",
    "seal_leak": "DF-SL-L",
    "electrical_open": "DF-EL-O",
}
BASE_DEFECT_RATE = {2022: 0.030, 2023: 0.026, 2024: 0.023, 2025: 0.020, 2026: 0.018}


def _date_range(year: int) -> tuple[date, date]:
    return date(year, 1, 1), min(date(year, 12, 31), AS_OF)


def _defect_type(
    rng: random.Random,
    *,
    year: int,
    day: date,
    workstation: str,
    shift: str,
    supplier_id: str,
    batch_sequence: int,
    model: str,
) -> str:
    calibration_event = workstation == "W-07" and (
        year <= 2024 or (year == 2025 and day.month <= 3) or (year == 2026 and day.month in {3, 4})
    )
    supplier_event = supplier_id == "SUP-007" and day.isocalendar().week in {8, 9, 10, 11}
    batch_event = batch_sequence % 37 == 11
    hot_weather_event = day.month in {6, 7, 8} and workstation in {"W-08", "W-10"}

    if calibration_event and rng.random() < 0.58:
        return "torque_low"
    if supplier_event and rng.random() < 0.52:
        return "pressure_high"
    if hot_weather_event and rng.random() < 0.44:
        return "temperature_drift"
    if workstation in {"W-01", "W-02"} and rng.random() < 0.32:
        return "weld_pore"
    if workstation in {"W-08", "W-09"} and rng.random() < 0.34:
        return "seal_leak"
    if model == "M03-PHEV" and shift == "Night" and rng.random() < 0.28:
        return "electrical_open"
    if batch_event and rng.random() < 0.46:
        return "pressure_low"
    return rng.choices(
        ("torque_low", "pressure_high", "temperature_drift", "weld_pore", "seal_leak", "electrical_open"),
        weights=(28, 18, 14, 13, 17, 10),
        k=1,
    )[0]


def _measurements(rng: random.Random, *, year: int, day: date, workstation: str, supplier_id: str, defect: str) -> tuple[float, float, float]:
    torque_mean = 45.0
    pressure_mean = 100.0
    temperature_mean = 20.0
    if workstation == "W-07" and year <= 2024:
        torque_mean -= 0.8
    elif workstation == "W-07" and year == 2026 and day.month in {3, 4}:
        torque_mean -= 0.55
    if supplier_id == "SUP-007" and day.isocalendar().week in {8, 9, 10, 11}:
        pressure_mean += 1.5
    if day.month in {6, 7, 8}:
        temperature_mean += 0.45

    torque = rng.gauss(torque_mean, 1.15)
    pressure = rng.gauss(pressure_mean, 3.2)
    temperature = rng.gauss(temperature_mean, 1.0)
    if defect == "torque_low":
        torque = rng.uniform(37.8, 39.9)
    elif defect == "torque_high":
        torque = rng.uniform(50.1, 52.2)
    elif defect == "pressure_low":
        pressure = rng.uniform(78.0, 84.9)
    elif defect == "pressure_high":
        pressure = rng.uniform(115.1, 122.0)
    elif defect == "temperature_drift":
        temperature = rng.uniform(23.1, 26.0)

    return round(torque, 2), round(pressure, 2), round(temperature, 2)


def _classify_measurement(torque: float, pressure: float, temperature: float) -> str:
    if torque < 40:
        return "torque_low"
    if torque > 50:
        return "torque_high"
    if pressure < 85:
        return "pressure_low"
    if pressure > 115:
        return "pressure_high"
    if temperature < 17 or temperature > 23:
        return "temperature_drift"
    return ""


def generate_year_records(year: int, count: int | None = None, seed: int | None = None) -> list[dict[str, object]]:
    """Return one year's deterministic unit-level quality snapshots."""

    if year not in ROWS_BY_YEAR:
        raise ValueError(f"不支持的数据年份：{year}")
    row_count = count if count is not None else ROWS_BY_YEAR[year]
    if row_count <= 0:
        raise ValueError("记录数必须大于 0")

    start, end = _date_range(year)
    day_count = (end - start).days + 1
    rng = random.Random(seed if seed is not None else year * 7919)
    records: list[dict[str, object]] = []

    for index in range(row_count):
        current_date = start + timedelta(days=(index * 131) % day_count)
        line = rng.choice(("A", "B", "C"))
        workstation = rng.choice(STATIONS)
        model = rng.choices(tuple(MODELS), weights=(45, 35, 20), k=1)[0]
        shift = rng.choice(("Day", "Night"))
        supplier = rng.choice(SUPPLIERS)
        batch_sequence = index // 150 + 1
        batch_id = f"BAT-{year}-{line}-{batch_sequence:04d}"

        defect_rate = BASE_DEFECT_RATE[year]
        calibration_event = workstation == "W-07" and (
            year <= 2024 or (year == 2025 and current_date.month <= 3) or (year == 2026 and current_date.month in {3, 4})
        )
        supplier_event = supplier == "SUP-007" and current_date.isocalendar().week in {8, 9, 10, 11}
        if calibration_event:
            defect_rate += 0.045
        if shift == "Night":
            defect_rate += 0.006
        if supplier_event:
            defect_rate += 0.032
        if batch_sequence % 37 == 11:
            defect_rate += 0.035
        if current_date.month in {6, 7, 8} and workstation in {"W-08", "W-10"}:
            defect_rate += 0.012

        defect = _defect_type(
            rng,
            year=year,
            day=current_date,
            workstation=workstation,
            shift=shift,
            supplier_id=supplier,
            batch_sequence=batch_sequence,
            model=model,
        ) if rng.random() < defect_rate else ""
        torque, pressure, temperature = _measurements(
            rng,
            year=year,
            day=current_date,
            workstation=workstation,
            supplier_id=supplier,
            defect=defect,
        )
        if not defect:
            defect = _classify_measurement(torque, pressure, temperature)

        if shift == "Day":
            clock_time = time(rng.randrange(6, 18), rng.randrange(60), tzinfo=timezone(timedelta(hours=8)))
        else:
            hour = rng.choice((*range(0, 6), *range(18, 24)))
            clock_time = time(hour, rng.randrange(60), tzinfo=timezone(timedelta(hours=8)))
        timestamp = datetime.combine(current_date, clock_time).isoformat(timespec="minutes")

        station_number = int(workstation[-2:])
        operation = f"OP-{station_number:02d}0"
        characteristic = (
            "torque" if station_number in {3, 6, 7, 11} else
            "pressure" if station_number in {4, 8, 9} else
            "temperature" if station_number in {5, 10} else "visual"
        )
        characteristic_code = {"torque": "SC-TQ-001", "pressure": "SC-PR-001", "temperature": "SC-TM-001", "visual": "CC-VS-001"}[characteristic]
        severity = rng.choices(("P1", "P2", "P3"), weights=(4, 24, 72), k=1)[0] if defect else ""
        disposition = rng.choices(("返工", "隔离待评审", "报废"), weights=(61, 30, 9), k=1)[0] if defect else "放行"
        rework = "Y" if disposition == "返工" else "N"

        records.append({
            "record_id": f"Q-{year}-{index + 1:06d}",
            "timestamp": timestamp,
            "plant_code": "PLANT-01",
            "production_line": line,
            "workstation": workstation,
            "operation_code": operation,
            "inspection_stage": "EOL" if station_number >= 10 else "IPQC",
            "vehicle_model": model,
            "part_number": MODELS[model],
            "serial_number": f"SIM-{year}-{line}-{index + 1:07d}",
            "shift": shift,
            "operator_id": f"OPR-{rng.randrange(1, 81):03d}",
            "equipment_id": f"EQ-{line}-{station_number:02d}",
            "measurement_tool_id": f"GAGE-{characteristic_code[3:5]}-{station_number:02d}",
            "supplier_id": supplier,
            "supplier_lot": f"LOT-{supplier}-{year}-W{current_date.isocalendar().week:02d}",
            "batch_id": batch_id,
            "control_plan_id": f"CP-{line}-{operation}",
            "control_plan_revision": "R01" if year <= 2022 else "R02" if year <= 2024 else "R03",
            "characteristic_id": characteristic_code,
            "characteristic_name": characteristic,
            "characteristic_class": "SC" if characteristic != "visual" else "CC",
            "sampling_plan": "EOL-100%" if station_number >= 10 else "IPQC-1/20",
            "torque": torque,
            "torque_unit": "N·m",
            "torque_lsl": 40.0,
            "torque_usl": 50.0,
            "pressure": pressure,
            "pressure_unit": "kPa",
            "pressure_lsl": 85.0,
            "pressure_usl": 115.0,
            "temperature": temperature,
            "temperature_unit": "°C",
            "temperature_lsl": 17.0,
            "temperature_usl": 23.0,
            "result": "NG" if defect else "OK",
            "defect_type": defect,
            "defect_code": DEFECT_CODES.get(defect, ""),
            "severity": severity,
            "disposition": disposition,
            "rework_flag": rework,
            "reaction_plan_code": "RP-CONTAIN-01" if defect else "RP-STD-01",
            "traceability_status": "complete",
        })

    return records


def write_year_datasets(output_dir: str | Path = OUTPUT_DIR) -> list[Path]:
    """Write the standard five-year synthetic dataset pack."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for year, count in ROWS_BY_YEAR.items():
        path = destination / f"quality_records_{year}.csv"
        records = generate_year_records(year, count=count)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDNAMES, extrasaction="raise")
            writer.writeheader()
            writer.writerows(records)
        written.append(path.resolve())
    return written


if __name__ == "__main__":
    for dataset_path in write_year_datasets():
        print(dataset_path)
