"""Verify source identity and independent multi-source analysis helpers."""

import unittest
from pathlib import Path

from data.source_manager import source_from_csv
from agent.workflow import QualityAgent
import tempfile
import pandas as pd

HEADER = "timestamp,production_line,workstation,shift,supplier_id,result\n"


def csv_source(result):
    return (HEADER + f"2026-01-01 08:00:00,A,W1,day,S1,{result}\n").encode()


class DataSourceTests(unittest.TestCase):
    def test_content_identity_detects_same_size_file_changes_and_duplicates(self):
        first_id, _ = source_from_csv("same.csv", csv_source("OK"))
        second_id, _ = source_from_csv("same.csv", csv_source("NG"))
        duplicate_id, _ = source_from_csv("copy.csv", csv_source("OK"))
        self.assertNotEqual(first_id, second_id)
        self.assertEqual(first_id, duplicate_id)

    def test_invalid_and_empty_csv_rejected(self):
        for content in (b"foo\n1\n", HEADER.encode()):
            with self.subTest(content=content), self.assertRaises(ValueError):
                source_from_csv("bad.csv", content)

    def test_sql_queries_each_source_without_mixing_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            for index, result in enumerate(("NG", "OK")):
                _, source = source_from_csv(f"{index}.csv", csv_source(result))
                path = Path(directory) / f"{index}.csv"
                pd.DataFrame(source["records"]).to_csv(path, index=False)
                report = QualityAgent(source["records"], llm_provider="mock", csv_path=path, log_dir=Path(directory) / "logs").answer("SQL 查询 A产线的生产记录")
                self.assertEqual(report["task"], "sql")
                self.assertEqual(report["tool_result"]["records_preview"][0]["result"], result)

if __name__ == "__main__":
    unittest.main()
