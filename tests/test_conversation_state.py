import json
import tempfile
import unittest
import builtins
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from agent.conversation import merge_followup_query
from agent.memory_store import MemoryStore
from agent.session_store import SessionStore
from agent.workflow import QualityAgent as _QualityAgent
from data.demo_data import generate_records
from tests.agent_test_utils import scripted_quality_decision


def QualityAgent(*args, **kwargs):
    kwargs.setdefault("decision_fn", scripted_quality_decision)
    return _QualityAgent(*args, **kwargs)


def active_query(line="A"):
    return {
        "task": "quality_analysis",
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
        "date_filter_requested": True,
        "date_scope": "range",
        "production_line": [line],
        "vehicle_model": "",
        "field": "",
        "usl": None,
        "lsl": None,
        "numeric_fields": [],
        "clarification_needed": False,
        "interpretation": "分析一月份质量",
    }


class ConversationStateTests(unittest.TestCase):
    def test_new_session_json_state_does_not_import_langgraph(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session_db = root / "sessions.sqlite3"
            checkpoint_db = root / "legacy-checkpoints.sqlite3"
            original_import = builtins.__import__

            def deny_langgraph(name, *args, **kwargs):
                if name == "langgraph" or name.startswith("langgraph."):
                    raise AssertionError("normal session persistence must not import LangGraph")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=deny_langgraph):
                store = SessionStore(session_db, checkpoint_db)
                session = store.create_session("source-a", "version-a")
                store.update_state(
                    session["session_id"],
                    messages=[{"role": "user", "content": "分析 A 产线"}],
                    active_filters={"production_line": ["A"]},
                )
                restored = SessionStore(session_db, checkpoint_db).get_state(session["session_id"])

        self.assertEqual(restored["messages"][0]["content"], "分析 A 产线")
        self.assertEqual(restored["active_filters"]["production_line"], ["A"])

    def test_current_json_state_can_be_exported_for_legacy_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = SessionStore(root / "sessions.sqlite3", root / "legacy.sqlite3")
            session = store.create_session("source-a", "version-a")
            session_id = session["session_id"]
            expected = store.update_state(
                session_id,
                messages=[{"role": "user", "content": "分析 A 产线"}],
                reports=[{"summary": "状态可恢复"}],
                active_filters={"production_line": ["A"]},
                pending_task={"task": "cpk", "field": "torque"},
            )

            result = store.export_legacy_checkpoints()
            with patch.dict("os.environ", {"LANGGRAPH_STRICT_MSGPACK": "true"}):
                from agent.session_store import _open_checkpointer, _session_graph, _thread_config

                with _open_checkpointer(root / "legacy.sqlite3") as checkpointer:
                    state = _session_graph(checkpointer).get_state(_thread_config(session_id))

        self.assertEqual(result["sessions_exported"], 1)
        self.assertIsNone(result["previous_checkpoint_backup"])
        self.assertEqual(dict(state.values), expected)

    def test_followup_replaces_line_and_inherits_month(self):
        query = merge_followup_query(active_query(), "那 B 产线呢？")

        self.assertEqual(query["production_line"], ["B"])
        self.assertEqual(query["start_date"], "2026-01-01")
        self.assertEqual(query["end_date"], "2026-01-31")

    def test_explicit_condition_wins_over_model_substitution(self):
        query = merge_followup_query(
            active_query(),
            "改看 Z 产线",
            {**active_query("A"), "production_line": ["A"]},
        )

        self.assertEqual(query["production_line"], ["Z"])

    def test_all_lines_clears_line_filter(self):
        query = merge_followup_query(active_query(), "查看所有产线")

        self.assertEqual(query["production_line"], [])
        self.assertEqual(query["start_date"], "2026-01-01")

    def test_multiple_lines_are_all_preserved(self):
        query = merge_followup_query(active_query(), "比较 A 和 B 产线")

        self.assertEqual(query["production_line"], ["A", "B"])

    def test_followup_inherits_vehicle_model_unless_explicitly_changed(self):
        previous = {**active_query(), "vehicle_model": "M1"}
        inherited = merge_followup_query(previous, "那 B 产线呢？")
        replaced = merge_followup_query(previous, "改看车型 M2 的 B 产线")

        self.assertEqual(inherited["vehicle_model"], "M1")
        self.assertEqual(replaced["vehicle_model"], "M2")
        self.assertEqual(replaced["production_line"], ["B"])

    def test_clear_all_filters_resets_prior_conditions(self):
        previous = {
            **active_query(),
            "vehicle_model": "M1",
            "workstation": ["W-07"],
            "shift": ["Night"],
            "supplier_id": ["S-1"],
        }
        query = merge_followup_query(previous, "清除所有筛选条件")

        self.assertIsNone(query["start_date"])
        self.assertEqual(query["production_line"], [])
        self.assertEqual(query["vehicle_model"], "")
        self.assertEqual(query["workstation"], [])
        self.assertEqual(query["shift"], [])
        self.assertEqual(query["supplier_id"], [])

    def test_explicit_month_replaces_range(self):
        query = merge_followup_query(active_query(), "分析 2026年2月的质量")

        self.assertEqual(query["start_date"], "2026-02-01")
        self.assertEqual(query["end_date"], "2026-02-28")
        self.assertEqual(query["production_line"], ["A"])

    def test_explicit_workstation_replaces_value_and_inherits_other_dimensions(self):
        previous = {**active_query(), "workstation": ["W-01"], "shift": ["Night"]}
        query = merge_followup_query(
            previous,
            "改看 W-07 工位",
            {**previous, "workstation": ["W-01"]},
        )

        self.assertEqual(query["workstation"], ["W-07"])
        self.assertEqual(query["shift"], ["Night"])

    def test_sessions_persist_small_state_and_remain_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            metadata_path = Path(directory) / "sessions.sqlite3"
            checkpoint_path = Path(directory) / "checkpoints.sqlite3"
            first_store = SessionStore(metadata_path, checkpoint_path)
            first = first_store.create_session("source-a", "version-a")
            second = first_store.create_session("source-a", "version-a")

            first_store.update_state(
                first["session_id"],
                messages=[{"role": "user", "content": "分析 A 产线"}],
                reports=[{"question": "分析 A 产线", "status": "success"}],
                active_filters={"production_line": ["A"]},
                active_query=active_query(),
                status="completed",
            )
            first_store.update_state(
                first["session_id"],
                messages=[{"role": "assistant", "content": "A 产线结果"}],
            )

            restored = SessionStore(metadata_path, checkpoint_path)
            first_state = restored.get_state(first["session_id"])
            second_state = restored.get_state(second["session_id"])

            self.assertEqual(first_state["source_id"], "source-a")
            self.assertEqual(first_state["data_version"], "version-a")
            self.assertEqual(first_state["active_filters"]["production_line"], ["A"])
            self.assertEqual(len(first_state["messages"]), 2)
            self.assertEqual(len(first_state["reports"]), 1)
            self.assertNotIn("records", first_state)
            self.assertEqual(second_state.get("messages", []), [])

            with self.assertRaisesRegex(ValueError, "数据源不可变更"):
                restored.update_state(first["session_id"], source_id="source-b")
            with self.assertRaisesRegex(ValueError, "数据版本不可变更"):
                restored.update_state(first["session_id"], data_version="version-b")

            submission_id = str(uuid4())
            self.assertTrue(restored.claim_submission(first["session_id"], submission_id)["claimed"])
            self.assertFalse(restored.claim_submission(first["session_id"], submission_id)["claimed"])
            restored.complete_submission(
                first["session_id"], submission_id, {"status": "success", "summary": "cached"}
            )
            replay = restored.claim_submission(first["session_id"], submission_id)
            self.assertEqual(replay["report"]["summary"], "cached")
            stale_id = str(uuid4())
            restored.claim_submission(first["session_id"], stale_id)
            with restored._connect() as connection:
                connection.execute(
                    "UPDATE session_submissions SET updated_at = '2000-01-01T00:00:00+00:00' "
                    "WHERE session_id = ? AND submission_id = ?",
                    (first["session_id"], stale_id),
                )
            recovered = restored.claim_submission(first["session_id"], stale_id)
            self.assertTrue(recovered["claimed"])
            self.assertTrue(recovered["reclaimed"])
    def test_quality_agent_restores_a_to_b_session_without_changing_month(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"QUALITY_AGENT_LANGCHAIN": "0"}
        ):
            metadata_path = Path(directory) / "sessions.sqlite3"
            checkpoint_path = Path(directory) / "checkpoints.sqlite3"
            calls = []

            def parse(question):
                calls.append(question)
                return active_query("A")

            options = {
                "parse_fn": parse,
                "source_id": "demo",
                "data_version": "demo-version-1",
                "session_store_path": metadata_path,
                "checkpoint_path": checkpoint_path,
            }
            first_agent = QualityAgent(generate_records(2400, seed=42), **options)
            session = first_agent.create_session()
            first = first_agent.answer("分析 2026 年 1 月 A 产线", session_id=session["session_id"])

            restarted_agent = QualityAgent(generate_records(2400, seed=42), **options)
            second = restarted_agent.answer("那 B 产线呢？", session_id=session["session_id"])
            state = restarted_agent.get_session_state(session["session_id"])

            self.assertEqual(first["status"], "success")
            self.assertEqual(second["status"], "success")
            self.assertEqual(second["filters"]["production_line"], ["B"])
            self.assertEqual(second["filters"]["start_date"], "2026-01-01")
            self.assertEqual(second["filters"]["end_date"], "2026-01-31")
            self.assertEqual(len(state["reports"]), 2)
            self.assertEqual(len(state["messages"]), 4)
            self.assertEqual(state["active_query"]["production_line"], ["B"])
            self.assertEqual(len(calls), 1)

    def test_session_rejects_a_changed_dataset_version(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(
                Path(directory) / "sessions.sqlite3",
                Path(directory) / "checkpoints.sqlite3",
            )
            session = store.create_session("source-a", "version-a")
            with patch.dict("os.environ", {"QUALITY_AGENT_LANGCHAIN": "0"}):
                agent = QualityAgent(
                    generate_records(10, seed=42),
                    parse_fn=lambda _: active_query(),
                    source_id="source-a",
                    data_version="version-b",
                    session_store_path=Path(directory) / "sessions.sqlite3",
                    checkpoint_path=Path(directory) / "checkpoints.sqlite3",
                )
                report = agent.answer("分析 B 产线", session_id=session["session_id"])

            self.assertEqual(report["status"], "needs_input")
            self.assertIn("版本不一致", report["summary"])
            self.assertEqual(store.get_state(session["session_id"])["messages"], [])

    def test_legacy_answer_without_session_keeps_report_contract(self):
        with patch.dict("os.environ", {"QUALITY_AGENT_LANGCHAIN": "0"}):
            agent = QualityAgent(
                generate_records(2400, seed=42),
                parse_fn=lambda _: active_query(),
            )
            report = agent.answer("分析 A 产线")

        self.assertEqual(report["status"], "success")
        self.assertIn("baseline", report)
        self.assertIn("trace", report)
        self.assertIn("elapsed_ms", report)

    def test_controlled_decision_evidence_is_saved_in_session(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"QUALITY_AGENT_LANGCHAIN": "0"}
        ):
            actions = [
                {
                    "action": "call_tool",
                    "tool": "quality_summary",
                    "arguments": {},
                    "message": "",
                },
                {"action": "finish", "tool": "", "arguments": {}, "message": "已完成"},
            ]
            options = {
                "parse_fn": lambda _: active_query(),
                "decision_fn": lambda _payload, timeout_seconds=None: actions.pop(0),
                "use_decision_loop": True,
                "source_id": "demo",
                "data_version": "demo-v1",
                "session_store_path": Path(directory) / "sessions.sqlite3",
                "checkpoint_path": Path(directory) / "checkpoints.sqlite3",
                "result_store_path": Path(directory) / "results.sqlite3",
                "event_log_path": Path(directory) / "events.jsonl",
            }
            decision_payloads = []

            def decide(payload, timeout_seconds=None):
                decision_payloads.append(payload)
                return actions.pop(0)

            options["decision_fn"] = decide
            agent = QualityAgent(generate_records(2400, seed=42), **options)
            session = agent.create_session()
            report = agent.answer("分析 A 产线", session_id=session["session_id"])
            second_report = agent.answer("那 B 产线呢？", session_id=session["session_id"])
            evidence = agent.get_evidence(
                report["evidence_refs"][0]["evidence_id"], session_id=session["session_id"]
            )
            events = [
                json.loads(line)
                for line in (Path(directory) / "events.jsonl").read_text(encoding="utf-8").splitlines()
            ]

            restored = QualityAgent(generate_records(2400, seed=42), **options)
            state = restored.get_session_state(session["session_id"])

        self.assertEqual(report["decision_loop"]["status"], "success")
        self.assertEqual(state["reports"][0]["decision_loop"]["tool_call_count"], 1)
        self.assertEqual(state["reports"][0]["decision_loop"]["run_id"], report["run_id"])
        self.assertEqual(evidence["result"]["baseline"]["total_count"], report["baseline"]["total_count"])
        self.assertEqual(second_report["filters"]["production_line"], ["B"])
        second_context = decision_payloads[2]["context"]
        self.assertEqual(second_context["prior_evidence"], [])
        self.assertGreater(second_context["stale_evidence_count"], 0)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["session_id"], session["session_id"])
        self.assertEqual(events[0]["run_id"], report["run_id"])
        self.assertEqual(events[0]["tool_call_ids"], [report["decision_loop"]["events"][0]["tool_call_id"]])
        self.assertEqual(events[0]["recovery_event"], "session_started")
        self.assertEqual(events[1]["recovery_event"], "session_resumed")

    def test_cpk_pending_task_resumes_after_bounds_and_unit_confirmation(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"QUALITY_AGENT_LANGCHAIN": "0"}
        ):
            parse_calls = []

            def parse(_question):
                parse_calls.append(_question)
                return {
                    "task": "cpk",
                    "start_date": None,
                    "end_date": None,
                    "date_filter_requested": False,
                    "date_scope": "all_data",
                    "production_line": ["A"],
                    "vehicle_model": "",
                    "workstation": [],
                    "shift": [],
                    "supplier_id": [],
                    "batch_id": [],
                    "defect_type": [],
                    "field": "torque",
                    "usl": None,
                    "lsl": None,
                    "unit": "",
                    "numeric_fields": [],
                    "clarification_needed": False,
                    "interpretation": "计算 A 产线扭矩 Cpk",
                }

            options = {
                "parse_fn": parse,
                "source_id": "demo",
                "data_version": "demo-v1",
                "session_store_path": Path(directory) / "sessions.sqlite3",
                "checkpoint_path": Path(directory) / "checkpoints.sqlite3",
            }
            agent = QualityAgent(generate_records(100, seed=42), **options)
            session = agent.create_session()
            first_submission = str(uuid4())
            first = agent.answer(
                "计算 A 产线扭矩 Cpk",
                session_id=session["session_id"],
                submission_id=first_submission,
            )
            replay = agent.answer(
                "计算 A 产线扭矩 Cpk",
                session_id=session["session_id"],
                submission_id=first_submission,
            )
            bounds = agent.answer(
                "下限 9，上限 11",
                session_id=session["session_id"],
                submission_id=str(uuid4()),
            )
            state_after_bounds = agent.get_session_state(session["session_id"])
            resumed = agent.answer(
                "N·m，确认与当前数据一致",
                session_id=session["session_id"],
                submission_id=str(uuid4()),
            )
            final_state = agent.get_session_state(session["session_id"])

        self.assertEqual(first["status"], "needs_input")
        self.assertEqual(replay["run_id"], first["run_id"])
        self.assertEqual(bounds["task_id"], first["task_id"])
        self.assertEqual(bounds["status"], "needs_input")
        self.assertEqual(state_after_bounds["pending_task"]["parsed_query"]["lsl"], 9.0)
        self.assertEqual(state_after_bounds["pending_task"]["parsed_query"]["usl"], 11.0)
        self.assertEqual(len(parse_calls), 1)
        self.assertEqual(resumed["status"], "success")
        self.assertEqual(resumed["tool_result"]["unit"], "N·m")
        self.assertEqual(resumed["task_id"], first["task_id"])
        self.assertIsNone(final_state.get("pending_task"))

    def test_confirmed_response_preference_applies_across_sessions_and_delete_takes_effect(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"QUALITY_AGENT_LANGCHAIN": "0"}
        ):
            root = Path(directory)
            memory_store = MemoryStore(root / "memory.sqlite3")
            preference = memory_store.save_confirmed(
                owner_id="local",
                memory_type="preference",
                memory_key="report_style",
                content={"value": "conclusion_first"},
                source="test user confirmation",
                confirmed=True,
            )
            explanation_requests = []

            def explain(request):
                explanation_requests.append(request)
                return {"text": "首要结论已核验。"}

            options = {
                "parse_fn": lambda _: active_query(),
                "model_fn": explain,
                "source_id": "demo",
                "data_version": "demo-v1",
                "session_store_path": root / "sessions.sqlite3",
                "checkpoint_path": root / "checkpoints.sqlite3",
                "memory_store_path": root / "memory.sqlite3",
            }
            agent = QualityAgent(generate_records(2400, seed=42), **options)
            first_session = agent.create_session()
            first = agent.answer("分析 A 产线", session_id=first_session["session_id"])
            memory_store.delete(preference["memory_id"], owner_id="local")
            second_session = agent.create_session()
            second = agent.answer("分析 A 产线", session_id=second_session["session_id"])

        self.assertEqual(first["response_style"], "conclusion_first")
        self.assertEqual(second["response_style"], "standard")
        self.assertEqual(explanation_requests[0]["response_style"], "conclusion_first")
        self.assertEqual(explanation_requests[1]["response_style"], "standard")

    def test_unexpected_session_error_is_saved_and_submission_replay_is_finite(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"QUALITY_AGENT_LANGCHAIN": "0"}
        ):
            options = {
                "parse_fn": lambda _: active_query(),
                "source_id": "demo",
                "data_version": "demo-v1",
                "session_store_path": Path(directory) / "sessions.sqlite3",
                "checkpoint_path": Path(directory) / "checkpoints.sqlite3",
                "event_log_path": Path(directory) / "events.jsonl",
            }
            agent = QualityAgent(generate_records(100, seed=42), **options)
            session = agent.create_session()

            def fail(*_args, **_kwargs):
                raise RuntimeError("diagnostic detail")

            agent._invoke_controlled_loop = fail
            submission_id = str(uuid4())
            first = agent.answer(
                "分析 A 产线", session_id=session["session_id"], submission_id=submission_id
            )
            replay = agent.answer(
                "分析 A 产线", session_id=session["session_id"], submission_id=submission_id
            )
            state = agent.get_session_state(session["session_id"])

        self.assertEqual(first["status"], "error")
        self.assertEqual(replay["run_id"], first["run_id"])
        self.assertEqual(len(state["reports"]), 1)
        self.assertEqual(state["status"], "failed")

    def test_cancelling_pending_task_clears_it_without_running_cpk(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", {"QUALITY_AGENT_LANGCHAIN": "0"}
        ):
            query = {**active_query(), "task": "cpk", "field": "torque", "usl": None, "lsl": None, "unit": ""}
            options = {
                "parse_fn": lambda _: query,
                "source_id": "demo",
                "data_version": "demo-v1",
                "session_store_path": Path(directory) / "sessions.sqlite3",
                "checkpoint_path": Path(directory) / "checkpoints.sqlite3",
            }
            agent = QualityAgent(generate_records(100, seed=42), **options)
            session = agent.create_session()
            agent.answer("计算扭矩 Cpk", session_id=session["session_id"])
            cancelled = agent.answer("取消当前任务", session_id=session["session_id"])
            state = agent.get_session_state(session["session_id"])

        self.assertEqual(cancelled["status"], "success")
        self.assertIn("未运行 Cpk", cancelled["summary"])
        self.assertIsNone(state.get("pending_task"))


if __name__ == "__main__":
    unittest.main()
