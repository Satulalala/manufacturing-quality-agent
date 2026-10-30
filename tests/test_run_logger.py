import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.workflow import QualityAgent
from data.demo_data import generate_records
from agent.run_logger import log_execution_event, log_run


def fixed_query(question):
    year = "2027" if "2027" in question else "2026"
    start_day = "01-01" if year == "2026" else "01-01"
    end_day = "01-02" if year == "2027" else "01-31"
    return {
        "task": "quality_analysis",
        "start_date": f"{year}-{start_day}",
        "end_date": f"{year}-{end_day}",
        "date_filter_requested": True,
        "date_scope": "range",
        "production_line": ["A"],
        "vehicle_model": "",
        "workstation": [],
        "shift": [],
        "supplier_id": [],
        "batch_id": [],
        "defect_type": [],
        "field": "",
        "usl": None,
        "lsl": None,
        "unit": "",
        "numeric_fields": [],
        "clarification_needed": False,
        "interpretation": question,
    }


class RunLoggerTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.log_dir = Path(self._tmpdir.name)
        self._env = patch.dict("os.environ", {"QUALITY_AGENT_LANGCHAIN": "0"})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmpdir.cleanup()

    def _agent(self):
        return QualityAgent(
            generate_records(2400, seed=42),
            log_dir=self.log_dir,
            parse_fn=fixed_query,
        )

    def test_answer_writes_log_file_with_expected_fields(self):
        agent = self._agent()
        agent.answer("请分析 2026-01-01 到 2026-01-31 A产线的不良率异常")

        files = list(self.log_dir.glob("run_*.json"))
        self.assertEqual(len(files), 1)
        entry = json.loads(files[0].read_text(encoding="utf-8"))

        self.assertEqual(entry["question"], "请分析 2026-01-01 到 2026-01-31 A产线的不良率异常")
        self.assertEqual(entry["provider"], "ollama")
        self.assertEqual(entry["status"], "success")
        self.assertIn("timestamp", entry)
        self.assertIn("filters", entry)
        self.assertIn("defect_rate_percent", entry)
        self.assertGreater(entry["defect_rate_percent"], 0)
        self.assertTrue(entry["top_factors"])
        self.assertEqual(entry["steps"][0]["tool"], "ollama_understand_question")
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

    def test_execution_event_logs_ids_version_latency_and_retry_without_result_bodies(self):
        event_path = self.log_dir / "events.jsonl"
        report = {
            "status": "success",
            "task": "quality_analysis",
            "run_id": "run-1",
            "source_id": "source-a",
            "elapsed_ms": 24.5,
            "baseline": {"secret": "not logged"},
            "decision_loop": {
                "tool_call_count": 1,
                "tool_execution_count": 1,
                "retry_count": 1,
                "stop_reason": "finished",
                "events": [{"tool_call_id": "run-1:tool:1", "tool": "quality_summary"}],
                "observations": [{"result": {"secret": "not logged"}}],
            },
        }
        log_execution_event(
            report,
            session_id="session-a",
            task_id="task-a",
            data_version="sha256:version-a",
            recovery_event="session_resumed",
            event_log=event_path,
        )
        event = json.loads(event_path.read_text(encoding="utf-8"))

        self.assertEqual(event["session_id"], "session-a")
        self.assertEqual(event["run_id"], "run-1")
        self.assertEqual(event["task_id"], "task-a")
        self.assertEqual(event["data_version"], "sha256:version-a")
        self.assertEqual(event["tool_call_ids"], ["run-1:tool:1"])
        self.assertEqual(event["latency_ms"], 24.5)
        self.assertEqual(event["retry_count"], 1)
        self.assertEqual(event["recovery_event"], "session_resumed")
        self.assertNotIn("secret", str(event))


class ReviewFlagTests(unittest.TestCase):
    def test_success_report_requires_human_review(self):
        with patch.dict("os.environ", {"QUALITY_AGENT_LANGCHAIN": "0"}):
            agent = QualityAgent(
                generate_records(400, seed=42), log_dir=tempfile.mkdtemp(), parse_fn=fixed_query
            )

            report = agent.answer("请分析 2026-01-01 到 2026-01-31 A产线")

        self.assertEqual(report["status"], "success")
        self.assertTrue(report["requires_human_review"])

    def test_no_data_report_does_not_require_review(self):
        with patch.dict("os.environ", {"QUALITY_AGENT_LANGCHAIN": "0"}):
            agent = QualityAgent(
                generate_records(400, seed=42), log_dir=tempfile.mkdtemp(), parse_fn=fixed_query
            )

            report = agent.answer("请分析 2027-01-01 到 2027-01-02 A产线")

        self.assertEqual(report["status"], "no_data")
        self.assertFalse(report["requires_human_review"])


if __name__ == "__main__":
    unittest.main()
