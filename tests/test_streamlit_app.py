import unittest

from streamlit.testing.v1 import AppTest


class StreamlitAppTests(unittest.TestCase):
    def test_dashboard_loads_with_core_metrics(self):
        app = AppTest.from_file("../app.py", default_timeout=60).run()

        self.assertFalse(app.exception)
        self.assertEqual(app.title[0].value, "制造质量分析台")
        self.assertGreaterEqual(len(app.metric), 3)
        self.assertTrue(any(button.label == "运行分析" for button in app.button))

    def test_dashboard_shows_parser_selection_and_execution_trace(self):
        app = AppTest.from_file("../app.py", default_timeout=60).run()

        self.assertFalse(app.exception)
        self.assertTrue(any(selectbox.label == "LLM 解析后端" for selectbox in app.selectbox))
        trace_text = " ".join(element.value for element in app.markdown if element.value)
        self.assertIn("执行过程", trace_text)
        self.assertIn("parse_question", trace_text)

    def test_dashboard_shows_quality_toolbox_tabs(self):
        app = AppTest.from_file("../app.py", default_timeout=60).run()

        self.assertFalse(app.exception)
        subheaders = [element.value for element in app.subheader]
        self.assertIn("质量分析工具箱", subheaders)
        tab_labels = [element.label for element in app.tabs]
        self.assertIn("Pareto 缺陷分析", tab_labels)
        self.assertIn("工艺能力 Cpk", tab_labels)
        self.assertIn("SPC 控制线", tab_labels)


if __name__ == "__main__":
    unittest.main()
