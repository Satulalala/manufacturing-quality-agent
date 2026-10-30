import unittest

from tools.registry import ToolRegistry, ToolValidationError


class ToolRegistryTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.registry = ToolRegistry()
        self.registry.register(
            "summarize",
            "Return a compact summary.",
            {
                "type": "object",
                "properties": {"limit": {"type": "integer"}},
                "required": ["limit"],
                "additionalProperties": False,
            },
            lambda args, context: self.calls.append((args, context)) or {"count": args["limit"]},
        )

    def test_rejects_unknown_tool_and_unexpected_arguments_before_execution(self):
        with self.assertRaisesRegex(ToolValidationError, "allowlisted"):
            self.registry.execute("run_python", {}, {})
        with self.assertRaisesRegex(ToolValidationError, "unknown fields"):
            self.registry.execute("summarize", {"limit": 1, "path": "private.csv"}, {})
        self.assertEqual(self.calls, [])

    def test_validates_argument_types_strictly(self):
        with self.assertRaisesRegex(ToolValidationError, "integer"):
            self.registry.execute("summarize", {"limit": True}, {})

    def test_rejects_missing_required_arguments_before_execution(self):
        with self.assertRaisesRegex(ToolValidationError, "arguments.limit is required"):
            self.registry.execute("summarize", {}, {})
        self.assertEqual(self.calls, [])

    def test_executes_only_registered_handler(self):
        result = self.registry.execute("summarize", {"limit": 3}, {"data_version": "v1"})
        self.assertEqual(result, {"count": 3})
        self.assertEqual(len(self.calls), 1)

    def test_optional_filter_echo_must_match_locked_scope(self):
        locked_context = {"filters": {"production_line": ["A"], "start_date": "2026-01-01"}}
        ToolRegistry.validate_scope_arguments(
            {"user_filters": ["production_line=A", "start_date=2026-01-01"]},
            locked_context,
        )
        with self.assertRaisesRegex(ToolValidationError, "program-locked scope"):
            ToolRegistry.validate_scope_arguments(
                {"user_filters": ["production_line=B", "start_date=2026-01-01"]},
                locked_context,
            )


if __name__ == "__main__":
    unittest.main()
