"""Regression coverage for Ollama question parsing under local-model timeouts."""

from __future__ import annotations

import os
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from agent.graph import build_graph, parse_node
from agent.llm_parser import _call_ollama, llm_timeout_seconds, parse_query_with_model
from agent.model_adapter import create_langchain_model_fn
from agent.state import initial_state
from agent.workflow import QualityAgent


class OllamaTimeoutTests(unittest.TestCase):
    def test_parser_uses_bounded_native_ollama_request(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"message": {"content": '{"task":"quality_analysis"}'}},
        ).encode("utf-8")
        with patch.dict(
            os.environ,
            {
                "OLLAMA_BASE_URL": "http://localhost:11434/v1",
            },
        ), patch("agent.llm_parser.urllib.request.urlopen", return_value=response) as urlopen:
            result = _call_ollama("分析 2026 年 1 月上旬", timeout=10)

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "http://localhost:11434/api/chat")
        self.assertEqual(payload["model"], "qwen3:4b-q4_K_M")
        self.assertEqual(result["task"], "quality_analysis")
        self.assertFalse(payload["stream"])
        self.assertEqual(
            payload["format"]["required"],
            [
                "task",
                "start_date",
                "end_date",
                "date_filter_requested",
                "date_scope",
                "production_line",
                "unit",
                "clarification_needed",
            ],
        )
        self.assertTrue(
            set(payload["format"]["required"]).issubset(
                payload["format"]["properties"]
            )
        )
        self.assertFalse(payload["format"]["additionalProperties"])
        self.assertEqual(payload["keep_alive"], "10m")
        self.assertEqual(payload["options"]["num_ctx"], 2048)
        self.assertEqual(payload["options"]["num_predict"], 128)

    def test_parser_default_timeout_allows_cold_local_model_startup(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            "agent.llm_parser._call_ollama",
            return_value={"task": "quality_analysis", "date_scope": "all_data"},
        ) as call_ollama:
            parse_query_with_model("分析质量")

        self.assertEqual(call_ollama.call_args.args[1], 60.0)

    def test_timeout_configuration_is_shared_and_bounded(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(llm_timeout_seconds(), 60.0)
        with patch.dict(os.environ, {"QUALITY_LLM_TIMEOUT": "90"}, clear=True):
            self.assertEqual(llm_timeout_seconds(), 90.0)
        with patch.dict(os.environ, {"QUALITY_LLM_TIMEOUT": "300"}, clear=True):
            self.assertEqual(llm_timeout_seconds(), 120.0)
        with patch.dict(os.environ, {"QUALITY_LLM_TIMEOUT": "invalid"}, clear=True):
            self.assertEqual(llm_timeout_seconds(), 60.0)

    def test_controlled_loop_honors_timeout_override_above_ten_seconds(self):
        received_timeouts = []

        def parse(_question, timeout=None):
            received_timeouts.append(timeout)
            return {
                "task": "quality_analysis",
                "start_date": None,
                "end_date": None,
                "date_filter_requested": True,
                "date_scope": "unclear",
                "production_line": [],
                "clarification_needed": False,
            }

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"QUALITY_LLM_TIMEOUT": "90"}, clear=True
        ), patch("agent.run_logger.log_execution_event"):
            agent = QualityAgent(
                [{"timestamp": "2026-01-05", "result": "OK"}],
                parse_fn=parse,
                model_fn=lambda _payload: {},
                use_decision_loop=True,
                result_store_path=Path(directory) / "results.sqlite3",
                memory_store_path=Path(directory) / "memory.sqlite3",
                event_log_path=Path(directory) / "events.jsonl",
            )
            report = agent.answer("分析最近质量")

        self.assertEqual(received_timeouts, [90.0])
        self.assertEqual(report["status"], "needs_input")

    def test_explanation_model_uses_the_same_cold_start_timeout(self):
        chat_model = Mock()
        chat_model.with_structured_output.return_value = object()
        langchain_ollama = types.ModuleType("langchain_ollama")
        langchain_ollama.ChatOllama = Mock(return_value=chat_model)

        with patch.dict(os.environ, {}, clear=True), patch.dict(
            sys.modules, {"langchain_ollama": langchain_ollama}
        ):
            create_langchain_model_fn("ollama")

        self.assertEqual(
            langchain_ollama.ChatOllama.call_args.kwargs["client_kwargs"]["timeout"],
            60.0,
        )
        self.assertEqual(langchain_ollama.ChatOllama.call_args.kwargs["model"], "qwen3:4b-q4_K_M")

    def test_timeout_explains_local_model_delay_and_fails_closed(self):
        state = initial_state([], "计算压力的 Cpk")

        result = parse_node(state, lambda _question: (_ for _ in ()).throw(TimeoutError()))

        self.assertEqual(result["parse_error"], "TimeoutError")
        self.assertIn("超时", result["clarification"])
        self.assertIn("未执行筛选或统计", result["clarification"])
        self.assertIn("question_parse", result["missing_inputs"])
        self.assertEqual(result["filters"], {})

        graph_state = build_graph(
            parse_fn=lambda _question: (_ for _ in ()).throw(TimeoutError())
        ).invoke(
            initial_state(
                [{"timestamp": "2026-01-05", "result": "NG"}],
                "计算压力的 Cpk",
            )
        )
        report = graph_state["report"]
        self.assertEqual(report["status"], "needs_input")
        self.assertEqual(report["baseline"]["total_count"], 0)
        self.assertIn("超时", report["summary"])

    def test_malformed_model_json_is_reported_as_a_parse_output_error(self):
        state = initial_state([], "分析质量")

        def fail_with_json_error(_question):
            raise json.JSONDecodeError("Expecting value", "", 0)

        result = parse_node(state, fail_with_json_error)

        self.assertIn("JSON", result["clarification"])
        self.assertIn("未执行筛选或统计", result["clarification"])
        self.assertNotIn("检查 Ollama 服务和模型名称", result["clarification"])


if __name__ == "__main__":
    unittest.main()
