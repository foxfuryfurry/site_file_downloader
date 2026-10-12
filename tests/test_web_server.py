"""Tests for the loopback web API and bundled static UI."""

import json
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from app.downloader.config import AppConfig
from app.downloader.errors import DownloadCancelled
from app.downloader.models import DownloadProgress
from app.downloader.services.download_tasks import DownloadTaskManager
from app.downloader.web_server import LocalHttpServer, is_local_origin


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


if __name__ == "__main__":
    unittest.main()
