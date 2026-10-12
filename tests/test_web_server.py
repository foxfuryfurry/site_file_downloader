"""Tests for the loopback web API and bundled static UI."""

import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.request import Request, urlopen

from app.downloader import config as downloader_config
from app.downloader.config import AppConfig
from app.downloader.errors import DownloadCancelled
from app.downloader.models import DownloadProgress
from app.downloader.services.download_tasks import DownloadTaskManager
from app.downloader.web_server import (
    LocalHttpServer,
    gallery_items,
    is_local_origin,
    read_public_config,
    update_public_config,
)


class WebServerTests(unittest.TestCase):
    def setUp(self):
        self.config = AppConfig(Path("."), Path("."), Path("."), {})
        self.started = threading.Event()

        def runner(_tags, _config, _report, *, cancel_event, progress):
            if _tags == "quick":
                _report("Search complete.")
                progress(DownloadProgress("downloading", 1, 1, 1, 0, 0))
                return 1, 0, 0
            self.started.set()
            cancel_event.wait(3)
            raise DownloadCancelled("Download cancelled.")

        self.manager = DownloadTaskManager(lambda: self.config, runner)
        self.server = LocalHttpServer(("127.0.0.1", 0), self.manager)
        self.server_thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.server_thread.start()
        self.origin = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=2)

    def test_bundled_ui_is_served_with_local_only_security_headers(self):
        with urlopen(self.origin + "/", timeout=2) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("text/html", response.headers["Content-Type"])
            self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
            self.assertIn("local app", response.read().decode("utf-8").lower())
        for path, content_type in (
            ("/static/app.js", "text/javascript"),
            ("/static/styles.css", "text/css"),
        ):
            with urlopen(self.origin + path, timeout=2) as response:
                self.assertEqual(response.status, 200)
                self.assertIn(content_type, response.headers["Content-Type"])
                self.assertGreater(int(response.headers["Content-Length"]), 0)

    def test_start_cancel_and_read_task_status(self):
        request = Request(
            self.origin + "/api/tasks",
            data=json.dumps({"tags": "landscape"}).encode(),
            headers={
                "Content-Type": "application/json",
                "Origin": self.origin,
            },
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            self.assertEqual(response.status, 202)
            task = json.load(response)
        self.assertTrue(self.started.wait(2))

        cancel_request = Request(
            f"{self.origin}/api/tasks/{task['id']}",
            headers={"Origin": self.origin},
            method="DELETE",
        )
        with urlopen(cancel_request, timeout=2) as response:
            self.assertEqual(response.status, 202)

        download_task = self.manager.get(task["id"])
        self.assertIsNotNone(download_task)
        with download_task.condition:
            self.assertTrue(
                download_task.condition.wait_for(
                    lambda: download_task.state == "cancelled", timeout=2
                )
            )

        with urlopen(f"{self.origin}/api/tasks/{task['id']}", timeout=2) as response:
            self.assertEqual(json.load(response)["state"], "cancelled")

    def test_cross_origin_start_is_rejected(self):
        port = self.server.server_port
        self.assertTrue(
            is_local_origin(
                f"127.0.0.1:{port}", f"http://127.0.0.1:{port}", port, True
            )
        )
        self.assertFalse(
            is_local_origin(
                f"127.0.0.1:{port}", "http://example.com", port, True
            )
        )
        self.assertFalse(
            is_local_origin(
                f"example.com:{port}", f"http://127.0.0.1:{port}", port, True
            )
        )
        self.assertFalse(
            is_local_origin(
                f"127.0.0.1:{port}", f"http://127.0.0.1:{port + 1}", port, True
            )
        )

    def test_top_search_api_ranks_history_by_call_count(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            history_file = root / "history.json"
            history_file.write_text(
                json.dumps(
                    {
                        "rule34": {
                            "searches": [
                                {"tags": f"query_{index}", "calls": index}
                                for index in range(1, 8)
                            ],
                            "downloads": [],
                        }
                    }
                ),
                encoding="utf-8",
            )
            configured = AppConfig(
                root, history_file, root / "keys.json", {"rule34": 1}
            )
            with patch(
                "app.downloader.web_server.load_config", return_value=configured
            ):
                with urlopen(self.origin + "/api/searches/top", timeout=2) as response:
                    self.assertEqual(response.status, 200)
                    searches = json.load(response)["searches"]

        self.assertEqual(
            searches,
            [
                {"tags": f"query_{index}", "calls": index}
                for index in range(7, 2, -1)
            ],
        )

    def test_progress_events_are_streamed_as_server_sent_events(self):
        request = Request(
            self.origin + "/api/tasks",
            data=json.dumps({"tags": "quick"}).encode(),
            headers={
                "Content-Type": "application/json",
                "Origin": self.origin,
            },
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            task = json.load(response)

        with urlopen(
            f"{self.origin}/api/tasks/{task['id']}/events", timeout=2
        ) as response:
            self.assertEqual(response.headers.get_content_type(), "text/event-stream")
            stream = response.read().decode("utf-8")
        self.assertIn("event: update", stream)
        self.assertIn('"type":"progress"', stream)
        self.assertIn('"type":"complete"', stream)

    def test_gallery_lists_and_serves_only_supported_media(self):
        with TemporaryDirectory() as directory:
            gallery_dir = Path(directory) / "media"
            gallery_dir.mkdir()
            image_path = gallery_dir / "rule34_42.jpg"
            image_path.write_bytes(b"test-image")
            (gallery_dir / "rule34_42.json").write_text("{}", encoding="utf-8")
            (gallery_dir / "notes.txt").write_text("ignore", encoding="utf-8")
            configured = AppConfig(
                gallery_dir, Path(directory) / "history.json",
                Path(directory) / "keys.json", {"rule34": 1},
            )
            items = gallery_items(gallery_dir)
            self.assertEqual([item["name"] for item in items], ["rule34_42.jpg"])
            self.assertEqual(items[0]["kind"], "image")

            with patch("app.downloader.web_server.load_config", return_value=configured):
                with urlopen(
                    f"{self.origin}/api/gallery/media/rule34_42.jpg", timeout=2
                ) as response:
                    self.assertEqual(response.read(), b"test-image")
                    self.assertEqual(response.headers.get_content_type(), "image/jpeg")
                with urlopen(f"{self.origin}/api/gallery", timeout=2) as response:
                    self.assertEqual(json.load(response)["items"][0]["name"], "rule34_42.jpg")

    def test_config_updates_preserve_history_and_existing_credentials(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            keys_path = root / "keys.json"
            config_path.write_text(
                json.dumps(
                    {
                        "downloads_dir": str(root / "old-downloads"),
                        "history_file": str(root / "history.json"),
                        "keys_file": str(keys_path),
                        "rate_limits": {
                            "rule34": {"requests_per_second": 1},
                            "another": {"requests_per_second": 2},
                        },
                        "kept_setting": "unchanged",
                    }
                ),
                encoding="utf-8",
            )
            keys_path.write_text(
                json.dumps(
                    {
                        "services": {
                            "rule34": {"api_key": "do-not-return", "user_id": "42"},
                            "another": {"token": "keep-this"},
                        }
                    }
                ),
                encoding="utf-8",
            )
            temporary_config = downloader_config.load_config(config_path)
            with (
                patch("app.downloader.web_server.CONFIG_PATH", config_path),
                patch("app.downloader.web_server.load_config", return_value=temporary_config),
            ):
                update_public_config(
                    {
                        "downloads_dir": str(root / "new-downloads"),
                        "rule34_requests_per_second": 0.5,
                        "api_key": "",
                        "user_id": "",
                    }
                )
                public = read_public_config()
                self.assertTrue(public["credentials_configured"])
                self.assertNotIn("do-not-return", json.dumps(public))
                saved_config = json.loads(config_path.read_text(encoding="utf-8"))
                saved_keys = json.loads(keys_path.read_text(encoding="utf-8"))
                self.assertEqual(saved_config["history_file"], str(root / "history.json"))
                self.assertEqual(saved_config["kept_setting"], "unchanged")
                self.assertEqual(saved_config["rate_limits"]["another"]["requests_per_second"], 2)
                self.assertEqual(saved_keys["services"]["rule34"]["api_key"], "do-not-return")
                self.assertEqual(saved_keys["services"]["another"]["token"], "keep-this")

                update_public_config(
                    {
                        "downloads_dir": str(root / "new-downloads"),
                        "rule34_requests_per_second": 0.5,
                        "api_key": "new-secret",
                        "user_id": "new-user",
                    }
                )
                updated_keys = json.loads(keys_path.read_text(encoding="utf-8"))
                self.assertEqual(updated_keys["services"]["rule34"]["api_key"], "new-secret")
                self.assertEqual(updated_keys["services"]["rule34"]["user_id"], "new-user")

    def test_config_rejects_partial_credentials_and_invalid_rate(self):
        with self.assertRaisesRegex(ValueError, "both Rule34 credentials"):
            update_public_config(
                {
                    "downloads_dir": "_output",
                    "rule34_requests_per_second": 1,
                    "api_key": "only-one",
                    "user_id": "",
                }
            )
        with self.assertRaisesRegex(ValueError, "requests per second"):
            update_public_config(
                {
                    "downloads_dir": "_output",
                    "rule34_requests_per_second": 0,
                    "api_key": "",
                    "user_id": "",
                }
            )

    def test_config_api_accepts_same_origin_updates(self):
        request = Request(
            self.origin + "/api/config",
            data=json.dumps(
                {
                    "downloads_dir": "_output",
                    "rule34_requests_per_second": 1,
                    "api_key": "",
                    "user_id": "",
                }
            ).encode(),
            headers={
                "Content-Type": "application/json",
                "Origin": self.origin,
            },
            method="POST",
        )
        public_settings = {
            "downloads_dir": "_output",
            "rule34_requests_per_second": 1,
            "credentials_configured": True,
        }
        with (
            patch("app.downloader.web_server.update_public_config") as update,
            patch(
                "app.downloader.web_server.read_public_config",
                return_value=public_settings,
            ),
        ):
            with urlopen(request, timeout=2) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(json.load(response), public_settings)
        update.assert_called_once_with(
            {
                "downloads_dir": "_output",
                "rule34_requests_per_second": 1,
                "api_key": "",
                "user_id": "",
            }
        )


if __name__ == "__main__":
    unittest.main()
