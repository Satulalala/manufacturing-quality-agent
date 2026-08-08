import unittest

from agent.llm_parser import make_parse_fn, mock_parse, parse_with_llm, _sanitize_llm_filters
from agent.workflow import QualityAgent
from data.demo_data import generate_records


class LlmParserTests(unittest.TestCase):
    def test_mock_parses_chinese_dates(self):
        filters = mock_parse("请分析 1月1日到1月15日 A产线")

        self.assertEqual(filters["start_date"], "2026-01-01")
        self.assertEqual(filters["end_date"], "2026-01-15")
        self.assertEqual(filters["production_line"], ["A"])

    def test_mock_parses_vehicle_model(self):
        filters = mock_parse("请分析 2026-01-01 到 2026-01-31 ID.4 车型的不良率")

        self.assertEqual(filters["vehicle_model"], "ID.4")

    def test_mock_parses_multiple_lines(self):
        filters = mock_parse("请分析 2026-01-01 到 2026-01-31 A产线和B产线的不良率")

        self.assertEqual(filters["production_line"], ["A", "B"])

    def test_sanitize_drops_invalid_values(self):
        raw = {"start_date": "2026-01-01", "end_date": "不是日期", "production_line": 123, "vehicle_model": "ID.7"}

        cleaned = _sanitize_llm_filters(raw)

        self.assertEqual(cleaned["start_date"], "2026-01-01")
        self.assertIsNone(cleaned["end_date"])
        self.assertIsNone(cleaned["production_line"])
        self.assertEqual(cleaned["vehicle_model"], "ID.7")

    def test_parse_with_llm_merges_rule_fields_when_llm_misses_them(self):
        # mock_parse cannot extract vehicle_model, so rules provide line/date,
        # and LLM-side merge keeps the rule values when llm output is empty.
        filters = parse_with_llm("请分析 2026-01-01 到 2026-01-15 A产线")

        self.assertEqual(filters["start_date"], "2026-01-01")
        self.assertEqual(filters["production_line"], ["A"])
        self.assertIsNone(filters["vehicle_model"])

    def test_parse_with_llm_falls_back_to_rules_on_invalid_output(self):
        filters = parse_with_llm("请分析 1月1日到1月15日 A产线", provider="mock")
        self.assertEqual(filters["start_date"], "2026-01-01")

    def test_make_parse_fn_returns_callable(self):
        parse_fn = make_parse_fn("mock")

        self.assertTrue(callable(parse_fn))
        self.assertEqual(parse_fn("请分析 1月1日到1月15日")["start_date"], "2026-01-01")

    def test_agent_uses_llm_parser_for_vehicle_model(self):
        agent = QualityAgent(generate_records(2400, seed=42), llm_provider="mock")
        report = agent.answer("请分析 2026-01-01 到 2026-01-31 ID.4 车型的不良率")

        self.assertEqual(report["filters"]["vehicle_model"], "ID.4")
        self.assertEqual(report["status"], "success")

    def test_agent_supports_multiple_lines_via_filter(self):
        agent = QualityAgent(generate_records(2400, seed=42), llm_provider="mock")
        report = agent.answer("请分析 2026-01-01 到 2026-01-31 A产线和B产线的不良率")

        self.assertEqual(report["filters"]["production_line"], ["A", "B"])
        self.assertEqual(report["status"], "success")


if __name__ == "__main__":
    unittest.main()
