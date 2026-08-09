import unittest

from analytics.process_capability import calculate_cpk


class ProcessCapabilityTests(unittest.TestCase):
    def test_symmetric_specs_give_cpk_equal_cp(self):
        # mean=50, sample std=sqrt(20/9), wide specs -> cp=cpk≈1.7889
        values = [48, 49, 50, 51, 52, 48, 49, 50, 51, 52]

        result = calculate_cpk(values, usl=58, lsl=42)

        self.assertEqual(result["status"], "capable")
        self.assertAlmostEqual(result["cpk"], result["cp"], places=6)
        self.assertAlmostEqual(result["cp"], 1.788854382, places=4)

    def test_asymmetric_specs_take_min_side(self):
        # mean=51, sample std=sqrt(10/19); cpu≈2.297 < cpl
        values = [51] * 10 + [50, 52, 50, 52, 50, 52, 50, 52, 50, 52]

        result = calculate_cpk(values, usl=56, lsl=44)

        self.assertEqual(result["status"], "capable")
        self.assertAlmostEqual(result["cpk"], result["cpu"], places=4)
        self.assertLess(result["cpu"], result["cpl"])
        self.assertAlmostEqual(result["cpu"], 2.29730, places=3)

    def test_low_capability_is_not_capable(self):
        values = [50, 47, 53, 46, 54, 48, 52, 45, 55, 49, 51, 47]

        result = calculate_cpk(values, usl=52, lsl=48)

        self.assertEqual(result["status"], "not_capable")
        self.assertLess(result["cpk"], 1.0)

    def test_marginal_band(self):
        values = [50.0] * 8 + [48.5, 51.5, 48.7, 51.3]

        result = calculate_cpk(values, usl=53, lsl=47)

        self.assertEqual(result["status"], "marginal")

    def test_constant_values(self):
        result = calculate_cpk([50.0] * 10, usl=56, lsl=44)

        self.assertEqual(result["status"], "constant")

    def test_insufficient_samples(self):
        result = calculate_cpk([50.0, 51.0], usl=56, lsl=44)

        self.assertEqual(result["status"], "insufficient")


if __name__ == "__main__":
    unittest.main()
