import unittest

from agent.workflow import QualityAgent
from data.demo_data import generate_records
from tests.agent_test_utils import scripted_quality_decision


class ControlledLoopWorkflowTests(unittest.TestCase):
    def test_analysis_uses_loop_even_when_legacy_flag_is_false(self):
        records = generate_records(2400, seed=42)
        parsed = {
            "task": "quality_analysis",
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "date_filter_requested": True,
            "date_scope": "range",
            "production_line": ["A"],
            "vehicle_model": "",
            "workstation": [],
            "shift": [],
            "supplier_id": [],
            "batch_id": [],
            "defect_type": [],
            "clarification_needed": False,
            "interpretation": "一月 A 产线质量",
        }
        agent = QualityAgent(
            records,
            parse_fn=lambda _question: parsed,
            decision_fn=scripted_quality_decision,
            use_decision_loop=False,
        )

        report = agent.answer("分析 2026 年 1 月 A 产线质量")

        self.assertEqual(report["status"], "success")
        self.assertEqual(report["decision_loop"]["status"], "success")
        self.assertEqual(report["decision_loop"]["tool_execution_count"], 1)
        self.assertGreater(report["baseline"]["total_count"], 0)
        self.assertEqual(report["filters"]["production_line"], ["A"])
        self.assertIn("limitations", report)

    def test_no_data_stops_with_an_explicit_status(self):
        records = generate_records(2400, seed=42)
        parsed = {
            "task": "quality_analysis", "start_date": "2027-01-01", "end_date": "2027-01-02",
            "date_filter_requested": True, "date_scope": "range", "production_line": ["A"],
            "vehicle_model": "", "workstation": [], "shift": [], "supplier_id": [],
            "batch_id": [], "defect_type": [], "clarification_needed": False,
            "interpretation": "无数据范围",
        }
        agent = QualityAgent(records, parse_fn=lambda _question: parsed, decision_fn=scripted_quality_decision)

        report = agent.answer("分析 2027 年 1 月 A 产线质量")

        self.assertEqual(report["status"], "no_data")
        self.assertEqual(report["top_factors"], [])


if __name__ == "__main__":
    unittest.main()
