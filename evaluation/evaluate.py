"""Evaluation harness for the quality Agent's fixed question set.

Runs every case in ``cases.json`` through the Agent and aggregates the
metrics defined in ``tasks/plan.md``: task completion rate, numerical
accuracy (line/dimension assertions), and average response time.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Iterable, Mapping

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DEFAULT_CASES_PATH = Path(__file__).resolve().parent / "cases.json"


def load_cases(path: str | Path = DEFAULT_CASES_PATH) -> list[dict[str, object]]:
    """Load the fixed question set as a list of case dicts."""

    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    cases = data.get("cases", []) if isinstance(data, dict) else data
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases.json must contain a non-empty 'cases' list")
    return [dict(case) for case in cases]


def run_case(agent, case: Mapping[str, object]) -> dict[str, object]:
    """Run one case and evaluate its assertions.

    Returns status, elapsed time, failed checks, and overall ok flag.
    A case completes when its status matches ``expected_status`` (default
    ``success``); extra assertions (``expected_line``, ``expected_dimensions``)
    contribute to numerical accuracy.
    """

    started = time.perf_counter()
    report = agent.answer(str(case["question"]))
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)

    expected_status = str(case.get("expected_status", "success"))
    status_ok = report["status"] == expected_status

    failed_checks: list[str] = []
    filters = report["filters"]
    line_value = filters.get("production_line")
    if "expected_line" in case:
        if isinstance(line_value, list):
            line_matches = str(case["expected_line"]) in [str(item) for item in line_value]
        else:
            line_matches = str(line_value) == str(case["expected_line"])
        if not line_matches:
            failed_checks.append("expected_line")
    if "expected_start_date" in case and str(filters.get("start_date")) != str(case["expected_start_date"]):
        failed_checks.append("expected_start_date")
    if "expected_end_date" in case and str(filters.get("end_date")) != str(case["expected_end_date"]):
        failed_checks.append("expected_end_date")
    if "expected_vehicle_model" in case and str(filters.get("vehicle_model")) != str(case["expected_vehicle_model"]):
        failed_checks.append("expected_vehicle_model")
    expected_dimensions = case.get("expected_dimensions")
    if expected_dimensions:
        actual = {str(factor["dimension"]) for factor in report["top_factors"]}
        missing = set(expected_dimensions) - actual
        if missing:
            failed_checks.append("expected_dimensions")

    return {
        "question": str(case["question"]),
        "status": report["status"],
        "elapsed_ms": elapsed_ms,
        "failed_checks": failed_checks,
        "ok": status_ok and not failed_checks,
        "accuracy_checked": bool(
            case.get("expected_line")
            or case.get("expected_start_date")
            or case.get("expected_end_date")
            or case.get("expected_vehicle_model")
            or case.get("expected_dimensions")
        ),
    }


def run_evaluation(agent, cases: Iterable[Mapping[str, object]]) -> dict[str, object]:
    """Run all cases and aggregate completion, accuracy, and timing metrics."""

    details = [run_case(agent, case) for case in cases]
    total = len(details)
    completion_count = sum(1 for item in details if item["ok"])
    status_counts: dict[str, int] = {}
    for item in details:
        status_counts[item["status"]] = status_counts.get(item["status"], 0) + 1

    accuracy_items = [item for item in details if item["accuracy_checked"]]
    accuracy_pass = sum(1 for item in accuracy_items if item["ok"])
    total_ms = sum(float(item["elapsed_ms"]) for item in details)

    return {
        "total": total,
        "completion_count": completion_count,
        "completion_rate": round(completion_count / total, 6) if total else 0.0,
        "accuracy_checked": len(accuracy_items),
        "accuracy_pass": accuracy_pass,
        "accuracy_rate": round(accuracy_pass / len(accuracy_items), 6) if accuracy_items else 0.0,
        "avg_response_time_ms": round(total_ms / total, 2) if total else 0.0,
        "status_counts": status_counts,
        "details": details,
    }


def main() -> None:
    """Command-line entry point: run the fixed question set and print metrics."""

    import argparse

    from agent.workflow import QualityAgent
    from data.demo_data import generate_records, load_records, write_records

    parser = argparse.ArgumentParser(description="运行固定问题集评测")
    parser.add_argument("--data", default="data/demo_records.csv", help="CSV 数据路径")
    args = parser.parse_args()

    data_path = Path(args.data)
    if data_path.exists():
        records = load_records(data_path)
    else:
        records = generate_records()
        write_records(records, data_path)

    cases = load_cases()
    metrics = run_evaluation(
        QualityAgent(records, llm_provider="mock"),
        cases,
    )

    print(f"问题总数：{metrics['total']}")
    print(f"任务完成率：{metrics['completion_count']}/{metrics['total']} = {metrics['completion_rate'] * 100:.1f}%")
    print(
        f"数值准确率：{metrics['accuracy_pass']}/{metrics['accuracy_checked']} "
        f"= {metrics['accuracy_rate'] * 100:.1f}%"
    )
    print(f"平均响应时间：{metrics['avg_response_time_ms']} ms")
    print(f"状态分布：{metrics['status_counts']}")
    for item in metrics["details"]:
        if not item["ok"]:
            print(f"  失败：{item['question']}（{item['status']}，{item['failed_checks']}）")


if __name__ == "__main__":
    main()
