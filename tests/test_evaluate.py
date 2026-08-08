import unittest

from agent.workflow import QualityAgent
from data.demo_data import generate_records
from evaluation.evaluate import load_cases, run_case, run_evaluation


class EvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agent = QualityAgent(generate_records(2400, seed=42), llm_provider="mock")

    def test_cases_file_has_22_cases_with_required_fields(self):
        cases = load_cases()

        self.assertEqual(len(cases), 22)
        for case in cases:
            self.assertIn("question", case)
            self.assertTrue(str(case["question"]).strip())

    def test_cases_cover_expected_scenarios(self):
        cases = load_cases()
        statuses = {str(case.get("expected_status", "success")) for case in cases}
        lines = {case.get("expected_line") for case in cases}

        self.assertEqual(statuses, {"success", "no_data"})
        self.assertTrue(any(line == "A" for line in lines if line))
        self.assertTrue(any(line == "B" for line in lines if line))

    def test_run_case_passes_for_success_case(self):
        case = load_cases()[0]
        result = run_case(self.agent, case)

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "success")
        self.assertGreaterEqual(result["elapsed_ms"], 0)

    def test_run_case_detects_status_mismatch(self):
        case = {"question": "请分析 2027-01-01 到 2027-01-02 A产线的不良率", "expected_status": "success"}
        result = run_case(self.agent, case)

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "no_data")

    def test_run_case_detects_line_mismatch(self):
        case = {"question": "请分析 2026-01-01 到 2026-01-15 A产线的不良率", "expected_line": "B"}
        result = run_case(self.agent, case)

        self.assertFalse(result["ok"])
        self.assertEqual(result["failed_checks"], ["expected_line"])

    def test_run_evaluation_reports_metrics(self):
        cases = load_cases()
        metrics = run_evaluation(self.agent, cases)

        self.assertEqual(metrics["total"], 22)
        self.assertEqual(metrics["completion_count"], 22)
        self.assertAlmostEqual(metrics["completion_rate"], 1.0, places=6)
        self.assertGreater(metrics["avg_response_time_ms"], 0)
        self.assertEqual(metrics["status_counts"]["success"], 20)
        self.assertEqual(metrics["status_counts"]["no_data"], 2)
        self.assertEqual(len(metrics["details"]), 22)

    def test_run_evaluation_is_deterministic(self):
        cases = load_cases()
        first = run_evaluation(self.agent, cases)
        second = run_evaluation(self.agent, cases)

        self.assertEqual(first["completion_rate"], second["completion_rate"])
        self.assertEqual(
            [item["status"] for item in first["details"]],
            [item["status"] for item in second["details"]],
        )


if __name__ == "__main__":
    unittest.main()
