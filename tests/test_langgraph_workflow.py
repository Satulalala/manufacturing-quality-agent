import unittest

from agent.graph import build_graph
from agent.workflow import QualityAgent
from data.demo_data import generate_records

PRESET_QUESTIONS = [
    "请分析 2026-01-01 到 2026-01-15 A产线的不良率异常",
    "请分析 2026-01-01 到 2026-01-31 的不良率",
    "请分析 2026-01-10 到 2026-01-20 B产线的质量问题",
    "2026-01-01 到 2026-01-31 A产线 W-07 工位为什么不良率高",
    "请分析 2026-03-01 到 2026-03-31 A产线的不良率",
]


class LangGraphWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = generate_records(2400, seed=42)
        cls.agent = QualityAgent(cls.records)

    def test_preset_questions_all_complete(self):
        for question in PRESET_QUESTIONS:
            with self.subTest(question=question):
                report = self.agent.answer(question)
                self.assertIn(report["status"], {"success", "no_data"})
                self.assertEqual(report["question"], question)

    def test_no_data_question_returns_no_data_status(self):
        report = self.agent.answer(PRESET_QUESTIONS[-1])
        self.assertEqual(report["status"], "no_data")
        self.assertEqual(report["top_factors"], [])

    def test_trace_records_tool_call_order(self):
        report = self.agent.answer(PRESET_QUESTIONS[0])

        self.assertIn("trace", report)
        self.assertEqual(
            [step["tool"] for step in report["trace"]],
            [
                "parse_question",
                "filter_records",
                "rank_candidate_causes",
                "retrieve_quality_documents",
                "generate_report",
            ],
        )

    def test_graph_builds_and_runs_directly(self):
        app = build_graph()
        state = app.invoke({"records": self.records, "question": PRESET_QUESTIONS[0], "trace": []})
        self.assertEqual(state["report"]["status"], "success")
        self.assertTrue(state["trace"])

    def test_answer_contract_is_unchanged(self):
        report = self.agent.answer(PRESET_QUESTIONS[0])
        for key in ("status", "question", "filters", "baseline", "top_factors", "summary"):
            self.assertIn(key, report)
        self.assertIn("limitations", report)


if __name__ == "__main__":
    unittest.main()
