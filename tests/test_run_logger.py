import json
import tempfile
import unittest
from pathlib import Path

from agent.workflow import QualityAgent
from data.demo_data import generate_records
from agent.run_logger import log_run


class RunLoggerTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.log_dir = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _agent(self):
        return QualityAgent(
            generate_records(2400, seed=42),
            llm_provider="mock",
            log_dir=self.log_dir,
        )

    def test_answer_writes_log_file_with_expected_fields(self):
        agent = self._agent()
        agent.answer("请分析 2026-01-01 到 2026-01-31 A产线的不良率异常")

        files = list(self.log_dir.glob("run_*.json"))
        self.assertEqual(len(files), 1)
        entry = json.loads(files[0].read_text(encoding="utf-8"))

        self.assertEqual(entry["question"], "请分析 2026-01-01 到 2026-01-31 A产线的不良率异常")
        self.assertEqual(entry["provider"], "mock")
        self.assertEqual(entry["status"], "success")
        self.assertIn("timestamp", entry)
        self.assertIn("filters", entry)
        self.assertIn("defect_rate_percent", entry)
        self.assertGreater(entry["defect_rate_percent"], 0)
        self.assertTrue(entry["top_factors"])
        self.assertEqual(entry["steps"][0]["tool"], "parse_question")
        self.assertGreater(entry["total_elapsed_ms"], 0)
        self.assertTrue(entry["requires_human_review"])

    def test_no_data_report_logs_without_review_flag(self):
        agent = self._agent()
        agent.answer("请分析 2027-01-01 到 2027-01-02 A产线")

        files = list(self.log_dir.glob("run_*.json"))
        self.assertEqual(len(files), 1)
        entry = json.loads(files[0].read_text(encoding="utf-8"))

        self.assertEqual(entry["status"], "no_data")
        self.assertFalse(entry["requires_human_review"])

    def test_log_run_writes_returns_path(self):
        report = {"question": "q", "status": "success", "filters": {}, "baseline": {}, "top_factors": []}
        path = log_run(report, [{"tool": "parse_question", "detail": "x"}], provider="mock", elapsed_ms=1.2, log_dir=self.log_dir)

        self.assertTrue(path.exists())
        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved["steps"][0]["tool"], "parse_question")


class ReviewFlagTests(unittest.TestCase):
    def test_success_report_requires_human_review(self):
        agent = QualityAgent(generate_records(400, seed=42), llm_provider="mock", log_dir=tempfile.mkdtemp())

        report = agent.answer("请分析 2026-01-01 到 2026-01-31 A产线")

        self.assertEqual(report["status"], "success")
        self.assertTrue(report["requires_human_review"])

    def test_no_data_report_does_not_require_review(self):
        agent = QualityAgent(generate_records(400, seed=42), llm_provider="mock", log_dir=tempfile.mkdtemp())

        report = agent.answer("请分析 2027-01-01 到 2027-01-02 A产线")

        self.assertEqual(report["status"], "no_data")
        self.assertFalse(report["requires_human_review"])


if __name__ == "__main__":
    unittest.main()
