"""Tests for per-site request pacing."""

import unittest
import threading
from unittest.mock import patch

from app.downloader.errors import DownloadCancelled
from app.downloader.transport.rate_limiter import RequestRateLimiter


class RequestRateLimiterTests(unittest.TestCase):
    @patch("app.downloader.transport.rate_limiter.time.sleep")
    @patch("app.downloader.transport.rate_limiter.time.monotonic", return_value=0.0)
    def test_paces_each_site_independently(self, monotonic, sleep):
        limiter = RequestRateLimiter({"rule34": 1, "other_site": 2})

        limiter.wait("rule34")
        limiter.wait("rule34")
        limiter.wait("other_site")
        limiter.wait("other_site")

        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1.0, 0.5])

    @patch("app.downloader.transport.rate_limiter.time.sleep")
    @patch("app.downloader.transport.rate_limiter.time.monotonic", return_value=0.0)
    def test_unconfigured_site_is_not_delayed(self, monotonic, sleep):
        RequestRateLimiter({"rule34": 1}).wait("unknown_site")

        sleep.assert_not_called()

    @patch("app.downloader.transport.rate_limiter.time.monotonic", return_value=0.0)
    def test_cancellation_interrupts_a_rate_limit_wait(self, monotonic):
        limiter = RequestRateLimiter({"rule34": 1})
        limiter.wait("rule34")
        cancel_event = threading.Event()
        cancel_event.set()

        with self.assertRaises(DownloadCancelled):
            limiter.wait("rule34", cancel_event)


if __name__ == "__main__":
    unittest.main()
