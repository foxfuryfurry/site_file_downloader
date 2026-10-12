"""Tests for downloaded media and Rule34 metadata sidecars."""

import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.downloader.sources.rule34_adapter import Rule34Post
from app.downloader.errors import DownloadCancelled
from app.downloader.storage.filesystem import save_post
from app.downloader.transport.rate_limiter import RequestRateLimiter


class FilesystemTests(unittest.TestCase):
    @patch("app.downloader.storage.filesystem.download_to_path")
    def test_save_post_writes_selected_api_data_with_tags_as_list(self, download):
        def write_media(_url: str, destination: Path, _site: str, _limiter) -> None:
            destination.write_bytes(b"media")

        download.side_effect = write_media
        api_data = {
            "id": 123,
            "rating": "explicit",
            "tags": "artist character",
            "file_url": "https://img.rule34.xxx/images/123/example.jpg",
            "width": 1920,
            "source": "https://example.org/post/123",
        }
        post = Rule34Post(
            "123",
            "artist character",
            "https://img.rule34.xxx/images/123/example.jpg",
            api_data,
        )

        with TemporaryDirectory() as directory:
            media_path = save_post(
                post,
                Path(directory),
                RequestRateLimiter({"rule34": 1}),
            )
            metadata_path = media_path.with_suffix(".json")

            self.assertEqual(media_path.name, "rule34_123.jpg")
            self.assertEqual(metadata_path.name, "rule34_123.json")
            self.assertEqual(media_path.read_bytes(), b"media")
            self.assertEqual(
                json.loads(metadata_path.read_text(encoding="utf-8")),
                {
                    "id": 123,
                    "tags": ["artist", "character"],
                    "source": "https://example.org/post/123",
                },
            )
            self.assertFalse(list(Path(directory).glob("*.part")))

    def test_cancelled_save_leaves_no_partial_file_or_sidecar(self):
        post = Rule34Post(
            "123", "artist character", "https://img.rule34.xxx/images/123/image.jpg"
        )
        cancel_event = threading.Event()
        cancel_event.set()

        with TemporaryDirectory() as directory:
            with self.assertRaises(DownloadCancelled):
                save_post(
                    post,
                    Path(directory),
                    RequestRateLimiter({"rule34": 1}),
                    cancel_event,
                )
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
