import unittest

from data.demo_data import generate_records
from tools.capability_tool import analyze_pareto, analyze_process_capability, analyze_spc


class CapabilityToolTests(unittest.TestCase):
    def test_default_torque_specs_are_positive_cpk(self):
        result = analyze_process_capability(generate_records(500, seed=42), field="torque")

        self.assertEqual(result["status"], "not_capable")
        self.assertGreater(result["cpk"], 0)
        self.assertLess(result["cpk"], 1.0)
        self.assertEqual(result["usl"], 50.0)
        self.assertEqual(result["lsl"], 40.0)

    def test_pareto_tool_returns_recommendation(self):
        result = analyze_pareto(generate_records(500, seed=42))

        self.assertEqual(result["status"], "success")
        self.assertIn("recommendation", result)
        self.assertTrue(result["items"])

    def test_spc_tool_on_demo_pressure(self):
        result = analyze_spc(generate_records(500, seed=42), field="pressure")

        self.assertIn(result["status"], {"success", "in_control", "insufficient"})
        self.assertIn("recommendation", result)

    def test_unknown_field_requests_specs(self):
        result = analyze_process_capability(generate_records(100, seed=42), field="flow_rate")

        self.assertEqual(result["status"], "missing_specs")


if __name__ == "__main__":
    unittest.main()
