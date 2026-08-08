import unittest

from analytics.quality_analysis import (
    calculate_defect_rate,
    compare_groups,
    rank_candidate_causes,
)


class QualityAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"workstation": "W-01", "shift": "Day", "supplier_id": "S-01", "result": "OK"},
            {"workstation": "W-01", "shift": "Day", "supplier_id": "S-01", "result": "NG"},
            {"workstation": "W-02", "shift": "Night", "supplier_id": "S-02", "result": "OK"},
            {"workstation": "W-02", "shift": "Night", "supplier_id": "S-02", "result": "NG"},
            {"workstation": "W-02", "shift": "Night", "supplier_id": "S-02", "result": "NG"},
        ]

    def test_calculate_defect_rate_returns_counts_and_percentage(self):
        result = calculate_defect_rate(self.records)

        self.assertEqual(result["total_count"], 5)
        self.assertEqual(result["defect_count"], 3)
        self.assertAlmostEqual(result["defect_rate"], 0.6)
        self.assertAlmostEqual(result["defect_rate_percent"], 60.0)

    def test_empty_records_return_zero_rate(self):
        result = calculate_defect_rate([])

        self.assertEqual(result["total_count"], 0)
        self.assertEqual(result["defect_count"], 0)
        self.assertEqual(result["defect_rate"], 0.0)

    def test_compare_groups_sorts_highest_defect_rate_first(self):
        result = compare_groups(self.records, "workstation")

        self.assertEqual(result[0]["group_value"], "W-02")
        self.assertEqual(result[0]["total_count"], 3)
        self.assertAlmostEqual(result[0]["defect_rate"], 2 / 3)
        self.assertEqual(result[1]["group_value"], "W-01")

    def test_rank_candidate_causes_includes_evidence_and_baseline(self):
        result = rank_candidate_causes(self.records, dimensions=("workstation",), min_samples=2)

        self.assertEqual(result[0]["dimension"], "workstation")
        self.assertEqual(result[0]["value"], "W-02")
        self.assertIn("sample_count", result[0])
        self.assertIn("baseline_defect_rate", result[0])
        self.assertIn("evidence", result[0])


if __name__ == "__main__":
    unittest.main()
