import random
import unittest

from analytics.anomaly_detection import detect_anomalies


def make_records(count: int, outlier_indices: set[int] = frozenset()) -> list[dict]:
    rng = random.Random(42)
    records: list[dict] = []
    for index in range(count):
        outlier = index in outlier_indices
        temperature = 60.0 if outlier else 22.0
        records.append(
            {
                "record_id": f"R-{index:05d}",
                "timestamp": f"2026-01-{(index % 28) + 1:02d} 10:00:00",
                "production_line": "A",
                "workstation": "W-07" if outlier else "W-01",
                "shift": "Day",
                "supplier_id": "S-01",
                "batch_id": "B-001",
                "temperature": temperature + rng.gauss(0, 0.5),
                "pressure": 100.0 + rng.gauss(0, 0.5),
                "torque": 45.0 + rng.gauss(0, 0.5),
                "result": "OK",
            }
        )
    return records


class AnomalyDetectionTests(unittest.TestCase):
    def test_detects_injected_outliers(self):
        outlier_ids = {5, 60, 120, 180, 250}
        records = make_records(400, outlier_ids)

        result = detect_anomalies(records, contamination=0.05)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["sample_count"], 400)
        detected_ids = {row["record_id"] for row in result["anomalies"]}
        self.assertTrue(detected_ids.issuperset({f"R-{index:05d}" for index in outlier_ids}))
        self.assertGreaterEqual(result["anomaly_count"], len(outlier_ids))

    def test_result_is_deterministic(self):
        records = make_records(200, {7, 99})

        first = detect_anomalies(records)
        second = detect_anomalies(records)

        self.assertEqual(first["anomalies"], second["anomalies"])

    def test_insufficient_data_returns_status(self):
        result = detect_anomalies(make_records(20), min_samples=50)

        self.assertEqual(result["status"], "insufficient_data")
        self.assertEqual(result["sample_count"], 20)
        self.assertEqual(result["anomalies"], [])

    def test_output_includes_structure_and_evidence(self):
        result = detect_anomalies(make_records(100, {3}))

        self.assertIn("anomaly_rate_percent", result)
        self.assertIn("evidence", result)
        row = result["anomalies"][0]
        self.assertIn("record_id", row)
        self.assertIn("timestamp", row)
        self.assertIn("production_line", row)
        self.assertIn("workstation", row)
        self.assertIn("temperature", row)


if __name__ == "__main__":
    unittest.main()
