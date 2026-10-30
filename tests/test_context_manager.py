import tempfile
import unittest
from pathlib import Path

from agent.context_manager import ContextBudgetError, ContextBuilder
from agent.result_store import ResultStore, evidence_staleness


class ContextManagerTests(unittest.TestCase):
    def test_keeps_exact_conditions_pending_slots_and_only_confirmed_memory(self):
        payload, metadata = ContextBuilder(token_budget=1024).build(
            "继续计算",
            {
                "task": "cpk",
                "filters": {"production_line": ["A"], "start_date": "2026-01-01"},
                "data_version": "sha256:demo",
                "pending_task": {
                    "task": "cpk",
                    "parsed_query": {"field": "torque", "lsl": 9, "usl": 11, "unit": "N·m"},
                    "missing_inputs": ["unit_confirmation"],
                    "unit_confirmed": False,
                },
                "confirmed_preferences": [{"key": "report_style", "value": "conclusion_first"}],
                "recent_messages": [{"role": "user", "content": "之前的问题"}],
            },
            [{"name": "calculate_cpk", "description": "Calculate Cpk", "parameters": {"type": "object"}}],
            [],
            3,
        )

        self.assertEqual(payload["context"]["filters"]["production_line"], ["A"])
        self.assertEqual(payload["context"]["data_version"], "sha256:demo")
        self.assertEqual(payload["context"]["pending_task"]["parsed_query"]["unit"], "N·m")
        self.assertEqual(payload["context"]["confirmed_preferences"][0]["value"], "conclusion_first")
        self.assertLessEqual(metadata["estimated_tokens"], metadata["budget_tokens"])
        self.assertEqual(metadata["estimate_method"], "json_characters_divided_by_4")

    def test_large_history_and_observations_are_bounded_without_records(self):
        payload, metadata = ContextBuilder(token_budget=1024).build(
            "q" * 2000,
            {
                "task": "quality_analysis",
                "filters": {"production_line": ["A"]},
                "data_version": "v1",
                "recent_messages": [
                    {"role": "user", "content": f"message-{index}-" + "x" * 800}
                    for index in range(20)
                ],
                "prior_evidence": [{"evidence_id": f"ev-{index}", "summary": "y" * 400} for index in range(20)],
                "records": [{"secret_row": "must not be serialized"}],
            },
            [{"name": "quality_summary", "description": "z" * 4000, "parameters": {"type": "object"}}],
            [{
                "tool": "quality_summary",
                "tool_call_id": "run:tool:1",
                "status": "success",
                "result": {
                    "baseline": {"total_count": 1000},
                    "records_preview": [{"row": index, "value": "r" * 500} for index in range(100)],
                },
            }],
            5,
        )

        self.assertLessEqual(metadata["estimated_tokens"], metadata["budget_tokens"])
        serialized = str(payload)
        self.assertNotIn("must not be serialized", serialized)
        self.assertIn("total_count", serialized)
        self.assertTrue(metadata["truncated"])

    def test_refuses_to_send_mandatory_context_over_budget(self):
        with self.assertRaisesRegex(ContextBudgetError, "未调用模型或工具"):
            ContextBuilder(token_budget=256).build(
                "question " * 1000,
                {"task": "quality_analysis", "filters": {}, "data_version": "v1"},
                [],
                [],
                1,
            )

    def test_preserves_exact_question_filters_pending_values_and_tool_schema(self):
        question = "请核查批次和供应商记录：" + "Q" * 2300
        batch_id = "BAT-2026-" + "B" * 120 + "-FINAL"
        data_version = "sha256:" + "a" * 180
        schema = {
            "type": "object",
            "properties": {"batch_id": {"type": "string", "enum": [batch_id]}},
            "required": ["batch_id"],
            "additionalProperties": False,
        }
        payload, _ = ContextBuilder(token_budget=1536).build(
            question,
            {
                "task": "quality_analysis",
                "filters": {"batch_id": [batch_id]},
                "data_version": data_version,
                "pending_task": {
                    "task": "quality_analysis",
                    "parsed_query": {"batch_id": [batch_id]},
                    "missing_inputs": [],
                },
                "prior_evidence": [{
                    "evidence_id": "evidence-1",
                    "tool": "quality_summary",
                    "tool_call_id": "run-1:tool:1",
                    "tool_version": "1",
                    "status": "success",
                    "data_version": data_version,
                    "filters": {"batch_id": [batch_id]},
                    "scope_hash": "f" * 64,
                    "summary": "历史证据摘要",
                }],
            },
            [{"name": "inspect_batch", "description": "d" * 600, "parameters": schema}],
            [],
            2,
        )

        self.assertEqual(payload["question"], question)
        self.assertEqual(payload["context"]["filters"]["batch_id"], [batch_id])
        self.assertEqual(payload["context"]["data_version"], data_version)
        self.assertEqual(payload["context"]["pending_task"]["parsed_query"]["batch_id"], [batch_id])
        self.assertEqual(payload["context"]["prior_evidence"][0]["data_version"], data_version)
        self.assertEqual(payload["context"]["prior_evidence"][0]["filters"]["batch_id"], [batch_id])
        self.assertEqual(payload["tools"][0]["parameters"], schema)

    def test_refuses_to_shorten_a_tool_schema_that_cannot_fit(self):
        schema = {
            "type": "object",
            "properties": {"batch_id": {"type": "string", "enum": ["B" * 1300]}},
            "required": ["batch_id"],
            "additionalProperties": False,
        }

        with self.assertRaisesRegex(ContextBudgetError, "未调用模型或工具"):
            ContextBuilder(token_budget=256).build(
                "查询批次",
                {"task": "quality_analysis", "filters": {}, "data_version": "v1"},
                [{"name": "inspect_batch", "description": "d" * 4000, "parameters": schema}],
                [],
                1,
            )

    def test_result_store_persists_tool_output_and_scopes_access_to_session(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ResultStore(Path(directory) / "results.sqlite3")
            reference = store.save_observation(
                {
                    "tool": "quality_summary",
                    "tool_call_id": "run-1:tool:1",
                    "status": "success",
                    "arguments": {},
                    "result": {"baseline": {"total_count": 2}, "evidence": "summary"},
                },
                session_id="session-a",
                run_id="run-1",
                filters={"production_line": ["A"]},
                data_version="version-a",
            )

            self.assertIsNotNone(reference)
            loaded = store.get(reference["evidence_id"], session_id="session-a")
            self.assertEqual(loaded["result"]["baseline"]["total_count"], 2)
            self.assertIsNone(store.get(reference["evidence_id"], session_id="session-b"))
            self.assertEqual(
                evidence_staleness(
                    reference,
                    data_version="version-a",
                    filters={"production_line": ["A"]},
                ),
                None,
            )
            self.assertEqual(
                evidence_staleness(
                    reference,
                    data_version="version-a",
                    filters={"production_line": ["B"]},
                ),
                "scope_changed",
            )
            self.assertEqual(
                evidence_staleness(
                    reference,
                    data_version="version-b",
                    filters={"production_line": ["A"]},
                ),
                "data_version_changed",
            )


if __name__ == "__main__":
    unittest.main()
