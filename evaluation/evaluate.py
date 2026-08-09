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

VALID_SQL = [
    "SELECT production_line, COUNT(*) AS n FROM production_records GROUP BY production_line",
    "SELECT result, COUNT(*) AS n FROM production_records GROUP BY result",
    "SELECT * FROM production_records LIMIT 3",
]
MALICIOUS_SQL = [
    "DROP TABLE production_records",
    "DELETE FROM production_records",
    "SELECT * FROM read_csv_auto('secrets.csv')",
]


def load_cases(path: str | Path = DEFAULT_CASES_PATH) -> list[dict[str, object]]:
    """Load the fixed question set as a list of case dicts."""

    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    cases = data.get("cases", []) if isinstance(data, dict) else data
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases.json must contain a non-empty 'cases' list")
    return [dict(case) for case in cases]


def _factor_hit_rate(details: list[dict[str, object]]) -> float:
    """Fraction of dimension-asserted cases whose expected factors were hit."""

    checked = [item for item in details if item.get("expected_dimensions")]
    if not checked:
        return 1.0
    hits = sum(1 for item in checked if "expected_dimensions" not in item.get("failed_checks", []))
    return round(hits / len(checked), 6)


def _citation_accuracy(reports: list[Mapping[str, object]], documents: list[dict[str, str]]) -> float:
    """Fraction of knowledge refs whose (doc, section) really exists in the corpus."""

    valid = {(document["doc"], document["section"]) for document in documents}
    total = 0
    valid_count = 0
    for report in reports:
        for reference in report.get("knowledge_refs") or []:
            total += 1
            if (reference["doc"], reference["section"]) in valid:
                valid_count += 1
    return round(valid_count / total, 6) if total else 1.0


def _sql_success_rate(csv_path: str | Path | None) -> tuple[float, int]:
    """Fraction of fixed legal queries succeeding plus malicious ones rejected."""

    if csv_path is None:
        return "skipped", 0
    from tools.sql_tool import run_readonly_query

    success = 0
    for sql in VALID_SQL:
        try:
            run_readonly_query(csv_path, sql)
            success += 1
        except Exception:
            pass
    for sql in MALICIOUS_SQL:
        try:
            run_readonly_query(csv_path, sql)
        except ValueError:
            success += 1
        except Exception:
            pass
    total = len(VALID_SQL) + len(MALICIOUS_SQL)
    return round(success / total, 6), total


def _review_stats(reports: list[Mapping[str, object]]) -> tuple[int, int]:
    """(cases requiring review, cases passing review) under the simulated rule."""

    required = sum(1 for report in reports if report.get("requires_human_review"))
    passed = sum(
        1
        for report in reports
        if report.get("requires_human_review") and report.get("top_factors")
    )
    return required, passed


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
        "expected_dimensions": bool(case.get("expected_dimensions")),
        "report": report,
        "accuracy_checked": bool(
            case.get("expected_line")
            or case.get("expected_start_date")
            or case.get("expected_end_date")
            or case.get("expected_vehicle_model")
            or case.get("expected_dimensions")
        ),
    }


def run_evaluation(
    agent,
    cases: Iterable[Mapping[str, object]],
    sql_csv: str | Path | None = None,
    documents: list[dict[str, str]] | None = None,
) -> dict[str, object]:
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

    reports = [item["report"] for item in details]
    from rag.ingest import load_documents

    resolved_documents = documents if documents is not None else load_documents()
    citation_accuracy = _citation_accuracy(reports, resolved_documents)
    required_reviews, passed_reviews = _review_stats(reports)
    sql_rate, sql_checked = _sql_success_rate(sql_csv)

    return {
        "total": total,
        "completion_count": completion_count,
        "completion_rate": round(completion_count / total, 6) if total else 0.0,
        "accuracy_checked": len(accuracy_items),
        "accuracy_pass": accuracy_pass,
        "accuracy_rate": round(accuracy_pass / len(accuracy_items), 6) if accuracy_items else 0.0,
        "factor_hit_rate": _factor_hit_rate(details),
        "citation_accuracy": citation_accuracy,
        "sql_success_rate": sql_rate,
        "sql_checked": sql_checked,
        "review_required_count": required_reviews,
        "review_pass_count": passed_reviews,
        "review_pass_rate": round(passed_reviews / required_reviews, 6) if required_reviews else 1.0,
        "avg_response_time_ms": round(total_ms / total, 2) if total else 0.0,
        "status_counts": status_counts,
        "details": details,
    }


def _rerun_reports(agent, cases: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    """Fallback for callers that did not attach reports to details."""

    return [dict(agent.answer(str(case["question"]))) for case in cases]


def main() -> None:
    """Command-line entry point: run the fixed question set and print metrics."""

    import argparse

    from agent.workflow import QualityAgent
    from data.demo_data import generate_records, load_records, write_records

    parser = argparse.ArgumentParser(description="运行固定问题集评测")
    parser.add_argument("--data", default="data/demo_records.csv", help="CSV 数据路径")
    parser.add_argument("--provider", default="mock", help="LLM 解析后端：mock/ollama/glm")
    args = parser.parse_args()

    data_path = Path(args.data)
    if data_path.exists():
        records = load_records(data_path)
    else:
        records = generate_records()
        write_records(records, data_path)

    cases = load_cases()
    metrics = run_evaluation(
        QualityAgent(records, llm_provider=args.provider),
        cases,
        sql_csv=data_path,
    )

    print(f"问题总数：{metrics['total']}")
    print(f"任务完成率：{metrics['completion_count']}/{metrics['total']} = {metrics['completion_rate'] * 100:.1f}%")
    print(
        f"数值准确率：{metrics['accuracy_pass']}/{metrics['accuracy_checked']} "
        f"= {metrics['accuracy_rate'] * 100:.1f}%"
    )
    print(f"候选因素命中率：{metrics['factor_hit_rate'] * 100:.1f}%")
    print(f"引用准确率：{metrics['citation_accuracy'] * 100:.1f}%")
    sql_text = metrics["sql_success_rate"]
    if isinstance(sql_text, float):
        print(f"SQL 成功率：{metrics['sql_checked']} 条检查 = {sql_text * 100:.1f}%")
    else:
        print(f"SQL 成功率：{sql_text}")
    print(
        f"人工审核通过率：{metrics['review_pass_count']}/{metrics['review_required_count']} "
        f"= {metrics['review_pass_rate'] * 100:.1f}%"
    )
    print(f"平均响应时间：{metrics['avg_response_time_ms']} ms")
    print(f"状态分布：{metrics['status_counts']}")
    for item in metrics["details"]:
        if not item["ok"]:
            print(f"  失败：{item['question']}（{item['status']}，{item['failed_checks']}）")


if __name__ == "__main__":
    main()
