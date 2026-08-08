import unittest

from data.demo_data import generate_records
from tools.quality_tools import filter_records


class DemoDataTests(unittest.TestCase):
    def test_generation_is_deterministic_and_contains_expected_fields(self):
        first = generate_records(200, seed=7)
        second = generate_records(200, seed=7)

        self.assertEqual(first, second)
        self.assertEqual(len(first), 200)
        self.assertTrue({"timestamp", "production_line", "workstation", "result"}.issubset(first[0]))

    def test_filter_records_filters_date_and_line(self):
        records = generate_records(300, seed=7)

        filtered = filter_records(
            records,
            start_date="2026-01-01",
            end_date="2026-01-10",
            production_line="A",
        )

        self.assertTrue(filtered)
        self.assertTrue(all(item["production_line"] == "A" for item in filtered))
        self.assertTrue(all("2026-01-01" <= item["timestamp"][:10] <= "2026-01-10" for item in filtered))

    def test_filter_records_rejects_invalid_or_reversed_dates(self):
        records = generate_records(10, seed=7)

        with self.assertRaises(ValueError):
            filter_records(records, start_date="2026/01/01")
        with self.assertRaises(ValueError):
            filter_records(records, start_date="2026-01-10", end_date="2026-01-01")


if __name__ == "__main__":
    unittest.main()
