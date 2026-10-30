import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.memory_store import MemoryStore
from agent.workflow import QualityAgent
from data.demo_data import generate_records
from data.source_manager import records_content_hash


class MemoryStoreTests(unittest.TestCase):
    def test_rejects_unconfirmed_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(Path(directory) / "memory.sqlite3")
            with self.assertRaisesRegex(ValueError, "用户明确确认"):
                store.save_confirmed(
                    owner_id="local",
                    memory_type="preference",
                    memory_key="report_style",
                    content={"value": "conclusion_first"},
                    source="model suggestion",
                )
            self.assertEqual(store.list_memories("local"), [])

    def test_preferences_are_confirmed_versioned_and_owner_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(Path(directory) / "memory.sqlite3")
            first = store.save_confirmed(
                owner_id="local",
                memory_type="preference",
                memory_key="report_style",
                content={"value": "conclusion_first"},
                source="用户在记忆管理界面确认",
                confirmed=True,
            )
            second = store.save_confirmed(
                owner_id="local",
                memory_type="preference",
                memory_key="report_style",
                content={"value": "standard"},
                source="用户修改偏好",
                confirmed=True,
            )

            self.assertEqual(second["version"], 2)
            self.assertEqual(store.confirmed_preferences("local"), [second])
            history = store.list_memories("local", include_history=True)
            self.assertEqual({item["status"] for item in history}, {"active", "superseded"})
            self.assertEqual(store.confirmed_preferences("another-user"), [])
            self.assertTrue(store.delete(second["memory_id"], owner_id="local"))
            self.assertEqual(store.confirmed_preferences("local"), [])
            self.assertEqual(store.list_memories("local", include_history=True)[0]["status"], "deleted")
            self.assertEqual(first["status"], "active")

    def test_cpk_specification_requires_exact_scope_and_deleted_specs_stop_reusing(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"QUALITY_AGENT_LANGCHAIN": "0"}
        ):
            root = Path(directory)
            store = MemoryStore(root / "memory.sqlite3")
            scope = {
                "source_id": "source-a",
                "data_version": "version-a",
                "production_line": "A",
                "vehicle_model": "M1",
                "workstation": "W-01",
                "field": "torque",
            }
            memory = store.save_confirmed(
                owner_id="local",
                memory_type="specification",
                memory_key="cpk_specification",
                content={"field": "torque", "lsl": 9, "usl": 11, "unit": "N·m"},
                scope=scope,
                unit="N·m",
                source="confirmed specification",
                confirmed=True,
            )
            agent = QualityAgent(
                [],
                source_id="source-a",
                data_version="version-a",
                memory_store_path=root / "memory.sqlite3",
            )
            query = {
                "task": "cpk", "production_line": ["A"], "vehicle_model": "M1",
                "workstation": ["W-01"], "field": "torque", "lsl": None, "usl": None, "unit": "",
            }
            matched = agent._apply_confirmed_specification(query)
            wrong_scope = agent._apply_confirmed_specification({**query, "workstation": ["W-02"]})
            store.delete(memory["memory_id"], owner_id="local")
            deleted = agent._apply_confirmed_specification({
                **query, "lsl": 9, "usl": 11, "unit": "N·m", "spec_memory_id": memory["memory_id"]
            })

        self.assertEqual((matched["lsl"], matched["usl"], matched["unit"]), (9.0, 11.0, "N·m"))
        self.assertEqual(matched["spec_source"], "confirmed_memory")
        self.assertIsNone(wrong_scope["lsl"])
        self.assertNotIn("spec_memory_id", wrong_scope)
        self.assertIsNone(deleted["lsl"])
        self.assertEqual(deleted["unit"], "")
        self.assertNotIn("spec_memory_id", deleted)

    def test_expired_specification_is_not_returned(self):
        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(Path(directory) / "memory.sqlite3")
            store.save_confirmed(
                owner_id="local",
                memory_type="specification",
                memory_key="cpk_specification",
                content={"lsl": 9, "usl": 11, "unit": "N·m"},
                scope={"field": "torque"},
                unit="N·m",
                source="user confirmed",
                valid_until="2020-01-01T00:00:00+00:00",
                confirmed=True,
            )
            matches = store.find_confirmed(
                owner_id="local",
                memory_type="specification",
                memory_key="cpk_specification",
                scope={"field": "torque"},
            )

        self.assertEqual(matches, [])

    def test_confirmed_exact_specification_is_applied_by_the_analysis_workflow(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"QUALITY_AGENT_LANGCHAIN": "0"}
        ):
            records = generate_records(2400, seed=42)
            for record in records:
                record["vehicle_model"] = "M1"
                record["workstation"] = "W-01"
            data_version = records_content_hash(records)
            store = MemoryStore(Path(directory) / "memory.sqlite3")
            store.save_confirmed(
                owner_id="local",
                memory_type="specification",
                memory_key="cpk_specification",
                content={"field": "torque", "lsl": 9, "usl": 11, "unit": "N·m"},
                scope={
                    "source_id": "source-a", "data_version": data_version,
                    "production_line": "A", "vehicle_model": "M1",
                    "workstation": "W-01", "field": "torque",
                },
                unit="N·m",
                source="用户确认的工艺规格",
                confirmed=True,
            )
            parsed = {
                "task": "cpk", "start_date": None, "end_date": None,
                "date_filter_requested": False, "date_scope": "all_data",
                "production_line": ["A"], "vehicle_model": "M1",
                "workstation": ["W-01"], "shift": [], "supplier_id": [],
                "batch_id": [], "defect_type": [], "field": "torque",
                "usl": None, "lsl": None, "unit": "", "numeric_fields": [],
                "clarification_needed": False, "interpretation": "计算精确范围的扭矩 Cpk",
            }
            agent = QualityAgent(
                records,
                parse_fn=lambda _: parsed,
                source_id="source-a",
                data_version=data_version,
                memory_store_path=Path(directory) / "memory.sqlite3",
            )
            report = agent.answer("计算 M1 车型 W-01 工位 A 产线扭矩 Cpk")

        self.assertEqual(report["task"], "cpk")
        self.assertEqual(report["status"], "success")
        self.assertEqual(report["tool_result"]["unit"], "N·m")
        self.assertNotIn("unit", report["missing_inputs"])


if __name__ == "__main__":
    unittest.main()
