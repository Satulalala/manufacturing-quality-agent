"""Scope regressions: explicit user constraints must survive model parsing and follow-ups."""
import unittest
from unittest.mock import Mock

from agent.conversation import explicit_filter_patch, merge_followup_query
from agent.graph import _explain, _explanation_evidence, parse_node
from agent.state import initial_state
from tools.quality_tools import filter_records


def july_query():
    return {"task": "quality_analysis", "start_date": "2026-07-01", "end_date": "2026-07-31",
            "date_scope": "range", "date_filter_requested": True, "production_line": ["A"],
            "clarification_needed": False}


class RequestedScopeTests(unittest.TestCase):
    def test_followup_preserves_every_named_month_despite_wrong_model_output(self):
        for question in ("B产线7月和8月的结果。", "B产线七月与八月", "B产线7、8月", "B产线七、八月"):
            with self.subTest(question=question):
                query = merge_followup_query(july_query(), question, july_query())
                self.assertEqual((query["start_date"], query["end_date"]), ("2026-07-01", "2026-08-31"))
                self.assertEqual(query["production_line"], ["B"])

    def test_followup_can_replace_line_without_losing_the_prior_month(self):
        previous = {**july_query(), "start_date": "2026-01-01", "end_date": "2026-01-31"}
        records = [
            {"timestamp": "2025-12-31", "production_line": "B", "result": "OK"},
            {"timestamp": "2026-01-01", "production_line": "B", "result": "NG"},
            {"timestamp": "2026-01-31", "production_line": "B", "result": "OK"},
            {"timestamp": "2026-02-01", "production_line": "B", "result": "OK"},
            {"timestamp": "2026-01-15", "production_line": "A", "result": "OK"},
        ]
        query = merge_followup_query(previous, "那 B 线呢", previous)
        result = parse_node(initial_state(records, "那 B 线呢", parsed_query=query), Mock())
        matched = filter_records(records, **result["filters"])

        self.assertEqual((result["filters"]["start_date"], result["filters"]["end_date"]),
                         ("2026-01-01", "2026-01-31"))
        self.assertEqual(result["filters"]["production_line"], ["B"])
        self.assertEqual(len(matched), 2)

    def test_month_lists_ranges_and_year_rollover(self):
        cases = {"2026年7、8、9月": ("2026-07-01", "2026-09-30"),
                 "2026年7月至10月": ("2026-07-01", "2026-10-31"),
                 "2025年12月到2026年2月": ("2025-12-01", "2026-02-28"),
                 "2025年12月至2月": ("2025-12-01", "2026-02-28"),
                 "2024年2月": ("2024-02-01", "2024-02-29")}
        for question, expected in cases.items():
            with self.subTest(question=question):
                query = explicit_filter_patch(question, july_query())
                self.assertEqual((query["start_date"], query["end_date"]), expected)

    def test_disjoint_dates_never_expand_or_drop_requested_dates(self):
        for question in ("7月和9月", "2026-07-01和2026-08-01", "2026年7月及2027年8月"):
            with self.subTest(question=question):
                query = merge_followup_query(july_query(), question, july_query())
                self.assertEqual(query["date_scope"], "unclear")
                self.assertTrue(query["clarification_needed"])
                self.assertIsNone(query["start_date"])
                self.assertIsNone(query["end_date"])

    def test_partial_month_does_not_get_overwritten_by_full_month_shortcut(self):
        for question in ("B产线7月上旬", "B产线7月1日到7月15日"):
            parsed = {**july_query(), "end_date": "2026-07-10" if "上旬" in question else "2026-07-15"}
            query = merge_followup_query(july_query(), question, parsed)
            self.assertEqual(query["end_date"], parsed["end_date"])

    def test_first_question_repairs_dates_and_line_then_filters_both_months(self):
        records = [{"timestamp": day, "production_line": line, "result": "OK"}
                   for day, line in (("2026-06-30", "B"), ("2026-07-01", "B"),
                                     ("2026-07-31", "B"), ("2026-08-01", "B"),
                                     ("2026-08-31", "B"), ("2026-09-01", "B"),
                                     ("2026-08-01", "A"))]
        parser = Mock(return_value=july_query())
        result = parse_node(initial_state(records, "B产线7月和8月的结果。"), parser)
        parser.assert_called_once()
        self.assertEqual(result["missing_inputs"], [])
        self.assertEqual(result["filters"]["end_date"], "2026-08-31")
        matched = filter_records(records, **result["filters"])
        self.assertEqual(len(matched), 4)
        self.assertTrue(all(record["production_line"] == "B" for record in matched))

    def test_multiple_source_years_require_year_in_a_new_question(self):
        records = [{"timestamp": "2025-07-01"}, {"timestamp": "2026-07-01"}]
        for question in ("B产线7月和8月", "上半年质量"):
            result = parse_node(initial_state(records, question), Mock(return_value=july_query()))
            self.assertIn("date_range", result["missing_inputs"])
            self.assertIsNone(result["filters"]["start_date"])
            self.assertIn("年份", result["clarification"])

    def test_explicit_year_wins_over_model_and_source_coverage(self):
        result = parse_node(initial_state([{"timestamp": "2026-07-01"}], "2025年B产线7月和8月"),
                            Mock(return_value=july_query()))
        self.assertEqual((result["filters"]["start_date"], result["filters"]["end_date"]),
                         ("2025-07-01", "2025-08-31"))

    def test_repeated_line_labels_do_not_drop_second_line(self):
        query = explicit_filter_patch("A产线和B产线7月和8月", july_query())
        self.assertEqual(query["production_line"], ["A", "B"])

    def test_followup_from_all_data_can_use_unique_source_year(self):
        previous = {**july_query(), "start_date": None, "end_date": None, "date_scope": "all_data"}
        query = merge_followup_query(previous, "B产线7月和8月", july_query())
        state = initial_state([{"timestamp": "2026-08-01"}], "B产线7月和8月", parsed_query=query)
        result = parse_node(state, Mock())
        self.assertEqual(result["missing_inputs"], [])
        self.assertEqual(result["filters"]["end_date"], "2026-08-31")

    def test_cross_year_session_does_not_supply_an_arbitrary_year(self):
        previous = {**july_query(), "start_date": "2025-01-01", "end_date": "2026-12-31"}
        query = merge_followup_query(previous, "7月和8月", july_query())
        self.assertEqual(query["date_scope"], "unclear")
        self.assertTrue(query["clarification_needed"])

    def test_explanation_receives_applied_scope(self):
        report = {"filters": july_query(), "data_scope": {"matched_count": 155}}
        evidence = _explanation_evidence(report)
        self.assertEqual(evidence["filters"], report["filters"])
        self.assertEqual(evidence["data_scope"], report["data_scope"])

    def test_explanation_cannot_claim_more_months_than_were_analyzed(self):
        report = {"task": "quality_analysis", "status": "success", "question": "B产线7月和8月",
                  "filters": {**july_query(), "production_line": ["B"]},
                  "baseline": {"total_count": 155, "defect_count": 2, "defect_rate_percent": 1.29},
                  "top_factors": [], "summary": "本轮仅统计7月。"}
        answer = _explain(report, lambda _: {"text": "B产线7月和8月的结果。"})
        self.assertEqual(answer[2], "fallback")
        self.assertIn("date range", answer[3])


if __name__ == "__main__":
    unittest.main()
