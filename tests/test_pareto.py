import unittest

from analytics.pareto import pareto_analysis


def make_record(defect_type: str = "", result: str = "OK") -> dict:
    return {
        "record_id": "R-1",
        "timestamp": "2026-01-01 10:00:00",
        "production_line": "A",
        "workstation": "W-01",
        "shift": "Day",
        "supplier_id": "S-01",
        "batch_id": "B-001",
        "result": result,
        "defect_type": defect_type,
    }


class ParetoTests(unittest.TestCase):
    def test_ranks_defect_types_with_cumulative_percent(self):
        records = (
            [make_record("torque_low", "NG")] * 5
            + [make_record("pressure_high", "NG")] * 3
            + [make_record("temperature_drift", "NG")] * 2
        )

        result = pareto_analysis(records)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["total_defects"], 10)
        items = result["items"]
        self.assertEqual(
            [item["defect_type"] for item in items],
            ["torque_low", "pressure_high", "temperature_drift"],
        )
        self.assertEqual(items[0]["count"], 5)
        self.assertAlmostEqual(items[0]["percent"], 50.0, places=6)
        self.assertAlmostEqual(items[0]["cumulative_percent"], 50.0, places=6)
        self.assertAlmostEqual(items[1]["cumulative_percent"], 80.0, places=6)
        self.assertAlmostEqual(items[2]["cumulative_percent"], 100.0, places=6)

    def test_ignores_ok_records(self):
        records = [make_record("torque_low", "NG")] * 2 + [make_record("", "OK")] * 10

        result = pareto_analysis(records)

        self.assertEqual(result["total_defects"], 2)
        self.assertEqual(result["items"][0]["count"], 2)

    def test_no_defects_reports_honestly(self):
        result = pareto_analysis([make_record("", "OK")] * 10)

        self.assertEqual(result["status"], "no_defects")
        self.assertEqual(result["items"], [])

    def test_empty_records(self):
        result = pareto_analysis([])

        self.assertEqual(result["status"], "no_defects")


if __name__ == "__main__":
    unittest.main()
