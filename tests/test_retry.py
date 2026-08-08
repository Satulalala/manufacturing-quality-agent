import unittest
from unittest.mock import patch

from tools.retry import with_retry


class RetryTests(unittest.TestCase):
    def test_succeeds_after_transient_failures(self):
        calls = {"count": 0}

        def flaky():
            calls["count"] += 1
            if calls["count"] < 3:
                raise ConnectionError("timeout")
            return "ok"

        result, attempts = with_retry(flaky, attempts=3, backoff=0)

        self.assertEqual(result, "ok")
        self.assertEqual(attempts, 3)

    def test_gives_up_after_max_attempts(self):
        def always_fails():
            raise ValueError("boom")

        with self.assertRaises(ValueError):
            with_retry(always_fails, attempts=3, backoff=0)

    def test_returns_single_attempt_on_first_success(self):
        result, attempts = with_retry(lambda: 42, attempts=3, backoff=0)

        self.assertEqual(result, 42)
        self.assertEqual(attempts, 1)

    def test_backoff_is_exponential(self):
        sleeps = []
        calls = {"count": 0}

        def flaky():
            calls["count"] += 1
            if calls["count"] < 3:
                raise OSError("timeout")
            return "ok"

        with patch("time.sleep", side_effect=lambda seconds: sleeps.append(seconds)):
            with_retry(flaky, attempts=3, backoff=0.2)

        self.assertEqual(sleeps, [0.2, 0.4])


if __name__ == "__main__":
    unittest.main()
