"""Tests for Rule34 search filtering and download history."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from app.downloader.config import AppConfig, Rule34Credentials
from app.downloader.services.download_service import download_by_tags
from app.downloader.sources.rule34_adapter import Rule34Post, search_posts
from app.downloader.storage.history import downloaded_ids, record_search
from app.downloader.transport.rate_limiter import RequestRateLimiter


class Rule34AdapterTests(unittest.TestCase):
    @patch("app.downloader.sources.rule34_adapter.get_json")
    def test_search_requires_explicit_rating_and_safe_media_url(self, get_json):
        get_json.return_value = [
            {
                "id": 10,
                "rating": "explicit",
                "tags": "adult character",
                "file_url": "https://img.rule34.xxx/images/10/image.jpg",
            },
            {
                "id": 11,
                "rating": "safe",
                "tags": "adult character",
                "file_url": "https://img.rule34.xxx/images/11/image.jpg",
            },
            {
                "id": 12,
                "rating": "explicit",
                "tags": "teen character",
                "file_url": "https://img.rule34.xxx/images/12/image.jpg",
            },
            {
                "id": 13,
                "rating": "explicit",
                "tags": "adult character",
                "file_url": "https://example.org/image.jpg",
            },
        ]

        expected_post = {
            "id": 10,
            "rating": "explicit",
            "tags": "adult character",
            "file_url": "https://img.rule34.xxx/images/10/image.jpg",
        }
        posts = search_posts(
            "character blue_hair",
            Rule34Credentials(api_key="test-secret", user_id="123"),
            RequestRateLimiter({"rule34": 1}),
        )

        self.assertEqual([post.post_id for post in posts], ["10"])
        self.assertEqual(posts[0].raw_data, expected_post)
        query = parse_qs(urlparse(get_json.call_args.args[0]).query)
        self.assertIn("rating:explicit", query["tags"][0])
        self.assertNotIn("rating:e ", query["tags"][0])
        self.assertIn("-loli", query["tags"][0])
        self.assertIn("character blue_hair", query["tags"][0])
        self.assertEqual(query["api_key"], ["test-secret"])
        self.assertEqual(query["user_id"], ["123"])
        self.assertEqual(query["limit"], ["1000"])
        self.assertEqual(query["pid"], ["0"])

    @patch("app.downloader.sources.rule34_adapter.get_json")
    def test_search_advances_pid_when_page_limit_is_reached(self, get_json):
        get_json.side_effect = [
            [
                {
                    "id": index,
                    "rating": "explicit",
                    "tags": "adult character",
                    "file_url": f"https://img.rule34.xxx/images/{index}/image.jpg",
                }
                for index in range(1000)
            ],
            [
                {
                    "id": 1000,
                    "rating": "explicit",
                    "tags": "adult character",
                    "file_url": "https://img.rule34.xxx/images/1000/image.jpg",
                }
            ],
        ]

        posts = search_posts(
            "character",
            Rule34Credentials(api_key="test-secret", user_id="123"),
            RequestRateLimiter({"rule34": 1}),
        )

        self.assertEqual(len(posts), 1001)
        self.assertEqual(posts[-1].post_id, "1000")
        queries = [
            parse_qs(urlparse(call.args[0]).query) for call in get_json.call_args_list
        ]
        self.assertEqual([query["pid"][0] for query in queries], ["0", "1"])
        self.assertEqual([query["limit"][0] for query in queries], ["1000", "1000"])

    @patch("app.downloader.sources.rule34_adapter.get_json")
    def test_empty_tags_are_rejected(self, get_json):
        with self.assertRaises(ValueError):
            search_posts(
                "  ",
                Rule34Credentials(api_key="test-secret", user_id="123"),
                RequestRateLimiter({"rule34": 1}),
            )
        get_json.assert_not_called()

    @patch("app.downloader.sources.rule34_adapter.get_json")
    def test_authentication_error_is_actionable_without_exposing_credentials(
        self, get_json
    ):
        get_json.return_value = "Missing authentication. Go to api.rule34.xxx"

        with self.assertRaisesRegex(
            RuntimeError, "Check services.rule34.api_key"
        ) as error:
            search_posts(
                "pedro_pascal",
                Rule34Credentials(api_key="test-secret", user_id="123"),
                RequestRateLimiter({"rule34": 1}),
            )

        self.assertNotIn("test-secret", str(error.exception))


class DownloadHistoryTests(unittest.TestCase):
    @patch("app.downloader.services.download_service.save_post")
    @patch("app.downloader.services.download_service.search_posts")
    def test_downloaded_posts_are_not_downloaded_again(
        self, search_posts_mock, save_post_mock
    ):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            history_file = root / "history.json"
            download_path = root / "rule34_42.jpg"
            config = AppConfig(
                root / "downloads",
                history_file,
                root / "keys.json",
                {"rule34": 1},
            )
            config.keys_file.write_text(
                json.dumps(
                    {
                        "services": {
                            "rule34": {
                                "api_key": "test-secret",
                                "user_id": "123",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            post = Rule34Post(
                "42", "adult character", "https://rule34.xxx/image.jpg"
            )
            search_posts_mock.return_value = [post]
            save_post_mock.return_value = download_path
            messages: list[str] = []

            self.assertEqual(
                download_by_tags("character", config, messages.append),
                (1, 0, 0),
            )
            self.assertEqual(downloaded_ids(history_file, "rule34"), {"42"})

            self.assertEqual(
                download_by_tags("character", config, messages.append),
                (0, 1, 0),
            )
            save_post_mock.assert_called_once()
            history = json.loads(history_file.read_text(encoding="utf-8"))
            self.assertEqual(
                history,
                {
                    "rule34": {
                        "searches": [{"tags": "character", "calls": 2}],
                        "downloads": ["42"],
                    }
                },
            )

    def test_legacy_download_history_migrates_to_nested_site_history(self):
        with TemporaryDirectory() as directory:
            history_file = Path(directory) / "history.json"
            history_file.write_text(
                json.dumps(
                    {
                        "downloads": [
                            {"id": "42", "file": "rule34_42.jpg"},
                            {"id": "41", "file": "rule34_41.jpg"},
                            {"id": "42", "file": "duplicate.jpg"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(downloaded_ids(history_file, "rule34"), {"42", "41"})
            self.assertEqual(
                json.loads(history_file.read_text(encoding="utf-8")),
                {
                    "rule34": {
                        "searches": [],
                        "downloads": ["42", "41"],
                    }
                },
            )

    def test_record_search_counts_common_queries_case_insensitively(self):
        with TemporaryDirectory() as directory:
            history_file = Path(directory) / "history.json"
            record_search(history_file, "rule34", "pedro_pascal")
            record_search(history_file, "rule34", "  PEDRO_PASCAL  ")
            record_search(history_file, "rule34", "pedro_pascal smile")

            self.assertEqual(
                json.loads(history_file.read_text(encoding="utf-8")),
                {
                    "rule34": {
                        "searches": [
                            {"tags": "pedro_pascal", "calls": 2},
                            {"tags": "pedro_pascal smile", "calls": 1},
                        ],
                        "downloads": [],
                    }
                },
            )


if __name__ == "__main__":
    unittest.main()
