import unittest

from analytics.spc_analysis import spc_control_limits


class SpcAnalysisTests(unittest.TestCase):
    def test_stable_process_has_no_out_of_control_points(self):
        values = [50, 49.5, 50.5, 50.2, 49.8, 50.1, 49.9, 50.3, 49.7, 50.0, 50.4, 49.6]

        result = spc_control_limits(values)

        self.assertEqual(result["status"], "in_control")
        self.assertEqual(result["out_of_control"], [])
        self.assertLess(result["lcl"], result["mean"])
        self.assertGreater(result["ucl"], result["mean"])

    def test_detects_upper_outlier(self):
        values = [50] * 19 + [58]

        result = spc_control_limits(values)

        self.assertEqual(len(result["out_of_control"]), 1)
        point = result["out_of_control"][0]
        self.assertEqual(point["side"], "upper")
        self.assertEqual(point["value"], 58)
        self.assertEqual(point["index"], 19)

    def test_detects_lower_outlier(self):
        values = [50] * 19 + [42]

        result = spc_control_limits(values)

        self.assertEqual(len(result["out_of_control"]), 1)
        self.assertEqual(result["out_of_control"][0]["side"], "lower")

    def test_insufficient_samples(self):
        result = spc_control_limits([50, 51, 52])

        self.assertEqual(result["status"], "insufficient")


if __name__ == "__main__":
    unittest.main()
