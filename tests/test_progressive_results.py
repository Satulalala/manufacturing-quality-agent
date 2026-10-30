from __future__ import annotations

import unittest
from unittest.mock import patch

from agent.graph import build_graph
from agent.state import initial_state


class ProgressiveResultTests(unittest.TestCase):
    def test_statistics_callback_runs_before_knowledge_and_model_explanation(self):
        events: list[tuple[str, object]] = []
        records = [
            {
                "timestamp": "2026-01-01",
                "result": "NG" if index < 2 else "OK",
                "workstation": "W-01",
                "shift": "Day",
                "batch_id": "B-01",
            }
            for index in range(20)
        ]

        def retrieve(*_args, **_kwargs):
            events.append(("knowledge", None))
            return {"status": "no_results", "results": [], "metadata": {}}

        def explain(_request):
            events.append(("explain", None))
            return {"text": "本次统计已经完成。"}

        def show_partial(result):
            events.append(("partial", result["baseline"]["total_count"]))

        parsed = {
            "task": "quality_analysis",
            "start_date": None,
            "end_date": None,
            "date_filter_requested": False,
            "date_scope": "all_data",
            "production_line": [],
            "clarification_needed": False,
        }
        graph = build_graph(parse_fn=lambda _question: parsed)

        with patch("tools.knowledge_tool.retrieve_quality_documents", side_effect=retrieve):
            state = graph.invoke(
                initial_state(
                    records,
                    "分析质量",
                    model_fn=explain,
                    partial_report_fn=show_partial,
                )
            )

        self.assertEqual(events[0], ("partial", 20))
        self.assertEqual([event[0] for event in events], ["partial", "knowledge", "explain"])
        self.assertEqual(state["report"]["status"], "success")
        self.assertEqual(state["report"]["explanation_source"], "model")


if __name__ == "__main__":
    unittest.main()
