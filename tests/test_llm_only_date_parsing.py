from __future__ import annotations

import unittest
from unittest.mock import Mock

from agent.graph import parse_node
from agent.state import initial_state


class LlmOnlyDateParsingTests(unittest.TestCase):
    def test_even_a_simple_date_phrase_is_sent_to_ollama_with_year_context(self):
        records = [
            {"timestamp": "2026-01-01 08:00:00"},
            {"timestamp": "2026-01-31 20:00:00"},
        ]
        parsed = {
            "task": "quality_analysis",
            "start_date": "2026-01-01",
            "end_date": "2026-01-10",
            "date_filter_requested": True,
            "date_scope": "range",
            "clarification_needed": False,
            "interpretation": "分析2026年1月上旬质量",
        }
        parse_fn = Mock(return_value=parsed)

        result = parse_node(
            initial_state(records, "请分析一月上旬的质量"),
            parse_fn,
        )

        parse_fn.assert_called_once()
        model_input = parse_fn.call_args.args[0]
        self.assertIn("用户问题：请分析一月上旬的质量", model_input)
        self.assertIn("数据涉及年份：2026", model_input)
        self.assertNotIn("2026-01-31", model_input)
        self.assertEqual(result["filters"]["start_date"], "2026-01-01")
        self.assertEqual(result["filters"]["end_date"], "2026-01-10")
        self.assertEqual(result["task"], "quality_analysis")

    def test_requested_range_is_not_clipped_to_available_records(self):
        parse_fn = Mock(return_value={
            "task": "quality_analysis", "start_date": "2026-01-01",
            "end_date": "2026-04-30", "date_filter_requested": True,
            "date_scope": "range", "clarification_needed": False,
        })
        result = parse_node(initial_state(
            [{"timestamp": "2026-01-15 08:00:00"}], "分析一月到四月的质量"
        ), parse_fn)
        self.assertEqual(result["filters"]["end_date"], "2026-04-30")
        self.assertEqual(result["missing_inputs"], [])


if __name__ == "__main__":
    unittest.main()
