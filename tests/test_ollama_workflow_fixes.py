"""Regression checks for local-model date filters, progress and explicit submission."""
import unittest
from unittest.mock import patch

from agent.workflow import QualityAgent as _QualityAgent, parse_question
from tests.agent_test_utils import scripted_quality_decision


def QualityAgent(*args, **kwargs):
    kwargs.setdefault("decision_fn", scripted_quality_decision)
    return _QualityAgent(*args, **kwargs)

RECORDS = [
    {"timestamp": f"2026-01-{day:02d}", "production_line": "A", "workstation": "W1", "shift": "Day", "supplier_id": "S1", "result": "NG" if day == 15 else "OK"}
    for day in (1, 14, 15, 20)
]


class OllamaWorkflowFixTests(unittest.TestCase):
    def test_chinese_before_date_filters_records_in_ollama_path(self):
        calls = []
        progress = []
        def model(payload):
            calls.append(payload["stage"])
            return {"text": "结论基于本次统计结果。", "citations": ["baseline.total_count"]}
        with patch("tools.knowledge_tool.retrieve_quality_documents", return_value={"status": "no_results", "results": []}):
            report = QualityAgent(RECORDS, llm_provider="ollama", model_fn=model, progress_fn=lambda *event: progress.append(event)).answer("请分析 2026年一月十五号之前内的产品质量")
        self.assertEqual(report["filters"]["end_date"], "2026-01-14")
        self.assertIsNone(report["filters"]["start_date"])
        self.assertEqual(report["baseline"]["total_count"], 2)
        self.assertEqual(calls, ["explain"])
        self.assertEqual(report["explanation_source"], "model")
        self.assertIn("quality_agent_retrieval", report["stage_timings"])
        self.assertTrue(any(event[0] == "quality_agent_report" and event[1] == "complete" for event in progress))

    def test_bounds_are_exclusive_and_ranges_include_explicit_year(self):
        self.assertEqual(parse_question("分析 2026-01-15 之前产品质量")["end_date"], "2026-01-14")
        self.assertEqual(parse_question("分析 2026年一月十五号之后产品质量")["start_date"], "2026-01-16")
        parsed = parse_question("2027年二月一日到二月十五日")
        self.assertEqual((parsed["start_date"], parsed["end_date"]), ("2027-02-01", "2027-02-15"))

    def test_invalid_or_unresolved_dates_never_analyze_every_record(self):
        with patch("tools.knowledge_tool.retrieve_quality_documents", return_value={"status": "no_results", "results": []}):
            agent = QualityAgent(RECORDS, llm_provider="ollama", model_fn=lambda payload: {"task": "quality_analysis"})
            for question in ("分析 2026年二月三十号的产品质量", "分析最近的产品质量", "分析一月十五号之前的产品质量", "分析 2026-01-20 到 2026-01-01 的产品质量"):
                with self.subTest(question=question):
                    self.assertEqual(agent.answer(question)["status"], "needs_input")

if __name__ == "__main__":
    unittest.main()
