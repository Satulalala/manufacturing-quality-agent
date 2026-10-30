import unittest

from agent.llm_parser import _sanitize_llm_query
from tools.quality_tools import filter_records


class QualityToolFilterTests(unittest.TestCase):
    def test_filter_records_supports_whitelisted_detail_dimensions(self):
        records = [
            {
                "timestamp": "2026-01-01 08:00:00",
                "production_line": "A",
                "vehicle_model": "M1",
                "workstation": "W-07",
                "shift": "Night",
                "supplier_id": "S-2",
                "batch_id": "B-4",
            },
            {
                "timestamp": "2026-01-01 09:00:00",
                "production_line": "A",
                "vehicle_model": "M1",
                "workstation": "W-08",
                "shift": "Day",
                "supplier_id": "S-1",
                "batch_id": "B-3",
            },
        ]

        matched = filter_records(
            records,
            production_line=["a"],
            workstation=["w-07"],
            shift=["night"],
            supplier_id=["s-2"],
            batch_id=["b-4"],
        )

        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["workstation"], "W-07")

    def test_filter_records_rejects_invalid_filter_values(self):
        with self.assertRaisesRegex(ValueError, "invalid value"):
            filter_records([], workstation=["W-\n07"])

    def test_query_parser_keeps_detail_filter_contract(self):
        parsed = _sanitize_llm_query(
            {
                "task": "quality_analysis",
                "start_date": None,
                "end_date": None,
                "date_filter_requested": False,
                "date_scope": "all_data",
                "production_line": [],
                "vehicle_model": "",
                "workstation": [" W-07 "],
                "shift": ["Night"],
                "supplier_id": ["S-2"],
                "batch_id": ["B-4"],
                "clarification_needed": False,
            }
        )

        self.assertEqual(parsed["workstation"], ["W-07"])
        self.assertEqual(parsed["shift"], ["Night"])
        self.assertEqual(parsed["supplier_id"], ["S-2"])
        self.assertEqual(parsed["batch_id"], ["B-4"])


if __name__ == "__main__":
    unittest.main()
