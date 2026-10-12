"""Tests for safe, useful HTTP response diagnostics."""

import unittest
from unittest.mock import patch

from app.downloader.transport.http_client import get_json
from app.downloader.transport.rate_limiter import RequestRateLimiter


class FakeResponse:
    status = 200

    def __init__(self, body: bytes, content_type: str) -> None:
        self.body = body
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return self.body


class HttpClientTests(unittest.TestCase):
    @patch("app.downloader.transport.http_client.urlopen")
    def test_invalid_json_includes_response_context_and_redacts_credentials(
        self, urlopen_mock
    ):
        urlopen_mock.return_value = FakeResponse(
            b"<html>proxy rejected key=secret-key user=12345</html>",
            "text/html; charset=utf-8",
        )
        request_url = (
            "https://api.rule34.xxx/index.php?api_key=secret-key&user_id=12345"
        )

        with self.assertRaisesRegex(RuntimeError, "invalid JSON") as error:
            get_json(request_url, "rule34", RequestRateLimiter({"rule34": 1}))

        diagnostic = str(error.exception)
        self.assertIn("HTTP 200", diagnostic)
        self.assertIn("Content-Type: text/html", diagnostic)
        self.assertIn("proxy rejected", diagnostic)
        self.assertNotIn("secret-key", diagnostic)
        self.assertNotIn("12345", diagnostic)
        self.assertNotIn("?api_key=", diagnostic)

    @patch("app.downloader.transport.http_client.urlopen")
    def test_valid_json_response_is_decoded(self, urlopen_mock):
        urlopen_mock.return_value = FakeResponse(b'[{"id": 7}]', "application/json")

        self.assertEqual(
            get_json(
                "https://api.rule34.xxx/index.php?api_key=secret-key",
                "rule34",
                RequestRateLimiter({"rule34": 1}),
            ),
            [{"id": 7}],
        )


if __name__ == "__main__":
    unittest.main()
