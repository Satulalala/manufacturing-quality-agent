import unittest

from analytics.trend_analysis import detect_trend_change


def make_daily_records(start_date: str, days: int, per_day: int, defect_counts: list[int]) -> list[dict]:
    """Build deterministic records where each day has a fixed defect count."""

    from datetime import date, timedelta

    start = date.fromisoformat(start_date)
    records: list[dict] = []
    for offset in range(days):
        current = start + timedelta(days=offset)
        date_str = current.isoformat()
        defect_count = defect_counts[offset % len(defect_counts)]
        for index in range(per_day):
            records.append(
                {
                    "record_id": f"R-{offset}-{index}",
                    "timestamp": f"{date_str} 10:00:00",
                    "production_line": "A",
                    "workstation": "W-01",
                    "shift": "Day",
                    "supplier_id": "S-01",
                    "batch_id": "B-001",
                    "temperature": 22.0,
                    "pressure": 100.0,
                    "torque": 45.0,
                    "result": "NG" if index < defect_count else "OK",
                }
            )
    return records


class TrendChangeTests(unittest.TestCase):
    def test_detects_jump_between_low_and_high_windows(self):
        # 30 days at 2%, then 30 days at 8%: the change point is day 31.
        defect_counts = [2] * 30 + [8] * 30
        records = make_daily_records("2026-01-01", 60, 100, defect_counts)

        result = detect_trend_change(records, window=7)

        self.assertEqual(result["status"], "change_detected")
        self.assertEqual(result["change_date"], "2026-01-31")
        self.assertAlmostEqual(result["before_rate_percent"], 2.0, places=6)
        self.assertAlmostEqual(result["after_rate_percent"], 8.0, places=6)
        self.assertAlmostEqual(result["change_percent"], 6.0, places=6)
        self.assertEqual(result["window"], 7)
        self.assertEqual(len(result["daily_rates"]), 60)

    def test_flat_data_reports_no_change(self):
        records = make_daily_records("2026-01-01", 40, 100, [2] * 40)

        result = detect_trend_change(records, window=7)

        self.assertEqual(result["status"], "no_change")
        self.assertIsNone(result["change_date"])
        self.assertAlmostEqual(result["change_percent"], 0.0)

    def test_too_few_days_reports_no_change(self):
        records = make_daily_records("2026-01-01", 5, 100, [2, 8, 2, 8, 2])

        result = detect_trend_change(records, window=7)

        self.assertEqual(result["status"], "no_change")

    def test_low_sample_spike_does_not_cause_false_alarm(self):
        # A single day with 3 records at 100% NG must not look like a trend jump.
        normal = make_daily_records("2026-01-01", 14, 100, [2])
        spike_day = make_daily_records("2026-01-15", 1, 3, [3])
        tail = make_daily_records("2026-01-16", 14, 100, [2])
        records = normal + spike_day + tail

        result = detect_trend_change(records, window=7)

        self.assertEqual(result["status"], "no_change")
        self.assertNotIn("2026-01-15", [row["date"] for row in result["daily_rates"]])


if __name__ == "__main__":
    unittest.main()
