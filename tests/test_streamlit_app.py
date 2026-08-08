import unittest

from streamlit.testing.v1 import AppTest


class StreamlitAppTests(unittest.TestCase):
    def test_dashboard_loads_with_core_metrics(self):
        app = AppTest.from_file("../app.py", default_timeout=15).run()

        self.assertFalse(app.exception)
        self.assertEqual(app.title[0].value, "制造质量分析台")
        self.assertGreaterEqual(len(app.metric), 3)
        self.assertTrue(any(button.label == "运行分析" for button in app.button))


if __name__ == "__main__":
    unittest.main()
