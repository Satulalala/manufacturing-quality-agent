import unittest

from agent.workflow import QualityAgent, parse_question
from data.demo_data import generate_records


class AgentWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = generate_records(2400, seed=42)
        cls.agent = QualityAgent(cls.records)

    def test_parse_question_extracts_line_and_dates(self):
        parsed = parse_question("请分析 2026-01-01 到 2026-01-15 A产线的不良率异常")

        self.assertEqual(parsed["production_line"], "A")
        self.assertEqual(parsed["start_date"], "2026-01-01")
        self.assertEqual(parsed["end_date"], "2026-01-15")

    def test_answer_returns_evidence_and_candidate_factors(self):
        report = self.agent.answer("请分析 2026-01-01 到 2026-01-31 A产线的不良率异常")

        self.assertEqual(report["status"], "success")
        self.assertGreater(report["baseline"]["total_count"], 0)
        self.assertLessEqual(len(report["top_factors"]), 3)
        self.assertTrue(report["top_factors"])
        self.assertTrue(all(item["evidence"] for item in report["top_factors"]))
        self.assertIn("候选因素", report["summary"])

    def test_answer_reports_no_data_without_fabricating_results(self):
        report = self.agent.answer("请分析 2027-01-01 到 2027-01-02 A产线")

        self.assertEqual(report["status"], "no_data")
        self.assertEqual(report["top_factors"], [])
        self.assertIn("没有符合条件", report["summary"])


if __name__ == "__main__":
    unittest.main()
