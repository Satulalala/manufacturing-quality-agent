import tempfile
import unittest
from pathlib import Path

from data.demo_data import generate_records, write_records
from tools.quality_tools import filter_records
from tools.sql_tool import query_quality_data, run_readonly_query


class SqlToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.records = generate_records(300, seed=7)
        cls.csv_path = write_records(cls.records, Path(cls._tmpdir.name) / "records.csv")

    @classmethod
    def tearDownClass(cls):
        cls._tmpdir.cleanup()

    def test_query_filters_match_python_filter_records(self):
        result = query_quality_data(
            self.csv_path,
            start_date="2026-01-01",
            end_date="2026-01-10",
            production_line="A",
        )
        expected = filter_records(
            self.records,
            start_date="2026-01-01",
            end_date="2026-01-10",
            production_line="A",
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["row_count"], len(expected))
        self.assertEqual(
            sorted(row["record_id"] for row in result["records"]),
            sorted(row["record_id"] for row in expected),
        )

    def test_query_filters_by_vehicle_model_and_returns_structure(self):
        result = query_quality_data(self.csv_path, vehicle_model="ID.4")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["row_count"], len(result["records"]))
        self.assertTrue(result["records"])
        self.assertTrue(all(row["vehicle_model"] == "ID.4" for row in result["records"]))
        self.assertEqual(result["filters"]["vehicle_model"], "ID.4")
        self.assertIn("production_records", result["evidence"])

    def test_query_respects_limit(self):
        result = query_quality_data(self.csv_path, limit=5)
        self.assertEqual(result["row_count"], 5)

    def test_query_rejects_unknown_columns_and_bad_dates(self):
        with self.assertRaises(ValueError):
            query_quality_data(self.csv_path, columns=["record_id", "password"])
        with self.assertRaises(ValueError):
            query_quality_data(self.csv_path, start_date="2026/01/01")
        with self.assertRaises(ValueError):
            query_quality_data(self.csv_path, start_date="2026-01-10", end_date="2026-01-01")

    def test_readonly_query_runs_plain_select(self):
        result = run_readonly_query(
            self.csv_path,
            "SELECT production_line, COUNT(*) AS n FROM production_records GROUP BY production_line",
        )
        self.assertEqual(result["status"], "success")
        self.assertTrue(all("production_line" in row and "n" in row for row in result["records"]))

    def test_readonly_query_supports_cte(self):
        result = run_readonly_query(
            self.csv_path,
            "WITH a_line AS (SELECT * FROM production_records WHERE production_line = 'A') "
            "SELECT COUNT(*) AS n FROM a_line",
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["row_count"], 1)

    def test_readonly_query_rejects_writes_and_dangerous_sql(self):
        malicious = [
            "DROP TABLE production_records",
            "DELETE FROM production_records",
            "UPDATE production_records SET result = 'OK'",
            "INSERT INTO production_records VALUES (1)",
            "CREATE TABLE x (a INT)",
            "ATTACH 'other.db'",
            "COPY production_records TO 'out.csv'",
            "PRAGMA database_list",
            "SELECT * FROM production_records; DROP TABLE production_records",
            "SHOW TABLES",
        ]
        for sql in malicious:
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                run_readonly_query(self.csv_path, sql)

    def test_readonly_query_rejects_arbitrary_file_reads(self):
        for sql in [
            "SELECT * FROM read_csv_auto('secrets.csv')",
            "SELECT * FROM read_parquet('x.parquet')",
            "SELECT * FROM glob('*')",
        ]:
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                run_readonly_query(self.csv_path, sql)

    def test_readonly_query_rejects_unknown_tables(self):
        with self.assertRaises(ValueError):
            run_readonly_query(self.csv_path, "SELECT * FROM maintenance_cases")


if __name__ == "__main__":
    unittest.main()
