"""Tests for the task boundary consumed by the local browser UI."""

import threading
import unittest
from pathlib import Path

from app.downloader.config import AppConfig
from app.downloader.errors import DownloadCancelled
from app.downloader.models import DownloadProgress
from app.downloader.services.download_tasks import DownloadTaskManager


class DownloadTaskTests(unittest.TestCase):
    def setUp(self):
        self.config = AppConfig(Path("."), Path("."), Path("."), {})

    def test_task_reports_progress_and_completion(self):
        def runner(_tags, _config, report, *, cancel_event, progress):
            report("Found 2 eligible adult-rated posts.")
            progress(DownloadProgress("downloading", 1, 2, 1, 0, 0))
            return 1, 1, 0

        manager = DownloadTaskManager(lambda: self.config, runner)
        task = manager.start("  blue_hair  ")
        task_thread_finished = threading.Event()

        def wait_for_completion():
            with task.condition:
                while task.state not in {"complete", "error", "cancelled"}:
                    task.condition.wait(1)
                task_thread_finished.set()

        waiter = threading.Thread(target=wait_for_completion)
        waiter.start()
        self.assertTrue(task_thread_finished.wait(2))
        waiter.join()

        snapshot = manager.snapshot(task)
        self.assertEqual(snapshot["state"], "complete")
        self.assertEqual(snapshot["tags"], "blue_hair")
        self.assertEqual(snapshot["result"], {"downloaded": 1, "skipped": 1, "failed": 0})
        events, finished = manager.events_after(task, 0)
        self.assertFalse(finished)
        self.assertIn("progress", [event["type"] for event in events])
        self.assertIn("complete", [event["type"] for event in events])
        events, finished = manager.events_after(task, events[-1]["sequence"])
        self.assertTrue(finished)
        self.assertEqual(events, [])

    def test_cancel_signals_running_task_and_reports_cancelled(self):
        started = threading.Event()

        def runner(_tags, _config, _report, *, cancel_event, progress):
            started.set()
            cancel_event.wait(2)
            raise DownloadCancelled("Download cancelled.")

        manager = DownloadTaskManager(lambda: self.config, runner)
        task = manager.start("landscape")
        self.assertTrue(started.wait(2))
        self.assertTrue(manager.cancel(task.task_id))

        with task.condition:
            self.assertTrue(
                task.condition.wait_for(lambda: task.state == "cancelled", timeout=2)
            )
        self.assertFalse(manager.cancel(task.task_id))
        events, _ = manager.events_after(task, 0)
        self.assertIn("cancelled", [event["type"] for event in events])

    def test_only_one_task_can_run_at_a_time(self):
        release = threading.Event()

        def runner(_tags, _config, _report, *, cancel_event, progress):
            release.wait(2)
            return 0, 0, 0

        manager = DownloadTaskManager(lambda: self.config, runner)
        task = manager.start("first")
        with self.assertRaisesRegex(RuntimeError, "already running"):
            manager.start("second")
        manager.cancel(task.task_id)
        release.set()

    def test_blank_tags_are_rejected(self):
        manager = DownloadTaskManager(lambda: self.config)
        with self.assertRaisesRegex(ValueError, "search tag"):
            manager.start("   ")

    def test_worker_errors_are_available_to_the_ui(self):
        def runner(_tags, _config, _report, *, cancel_event, progress):
            raise RuntimeError("Credentials file is missing.")

        manager = DownloadTaskManager(lambda: self.config, runner)
        task = manager.start("landscape")
        with task.condition:
            self.assertTrue(
                task.condition.wait_for(lambda: task.state == "error", timeout=2)
            )

        snapshot = manager.snapshot(task)
        self.assertEqual(snapshot["state"], "error")
        self.assertEqual(snapshot["error"], "Credentials file is missing.")
        events, _ = manager.events_after(task, 0)
        error_event = next(event for event in events if event["type"] == "error")
        self.assertEqual(error_event["error"], "Credentials file is missing.")


if __name__ == "__main__":
    unittest.main()
