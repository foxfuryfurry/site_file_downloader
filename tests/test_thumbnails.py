"""Tests for generated image and video gallery thumbnails."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from app.downloader.storage.thumbnails import ensure_thumbnail, thumbnail_path


class ThumbnailTests(unittest.TestCase):
    def test_image_thumbnail_is_bounded_and_cached(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            media_path = root / "photo.png"
            Image.new("RGB", (1280, 720), "purple").save(media_path)
            destination = thumbnail_path(root, media_path.name)

            result = ensure_thumbnail(media_path, destination)
            self.assertEqual(result, destination)
            with Image.open(destination) as thumbnail:
                self.assertLessEqual(thumbnail.width, 320)
                self.assertLessEqual(thumbnail.height, 320)
                self.assertEqual(thumbnail.format, "JPEG")

            with patch(
                "app.downloader.storage.thumbnails._create_image_thumbnail"
            ) as create_thumbnail:
                self.assertEqual(ensure_thumbnail(media_path, destination), destination)
            create_thumbnail.assert_not_called()

    def test_video_thumbnail_reports_missing_bundled_and_system_ffmpeg(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            media_path = root / "clip.mp4"
            media_path.write_bytes(b"video")
            destination = thumbnail_path(root, media_path.name)

            with patch("app.downloader.storage.thumbnails.shutil.which", return_value=None):
                with patch(
                    "app.downloader.storage.thumbnails.imageio_ffmpeg.get_ffmpeg_exe",
                    side_effect=RuntimeError("No bundled executable."),
                ):
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "Install dependencies with.*requirements.txt",
                    ):
                        ensure_thumbnail(media_path, destination)

            self.assertFalse(destination.exists())
            self.assertEqual(list(destination.parent.iterdir()), [])

    def test_video_thumbnail_falls_back_to_bundled_ffmpeg(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            media_path = root / "clip.mp4"
            media_path.write_bytes(b"video")
            destination = thumbnail_path(root, media_path.name)

            def write_video_frame(
                command: list[str], **options: object
            ) -> SimpleNamespace:
                self.assertEqual(options["timeout"], 30)
                Path(command[-1]).write_bytes(b"video-thumbnail")
                return SimpleNamespace(returncode=0, stderr="")

            with (
                patch(
                    "app.downloader.storage.thumbnails.shutil.which",
                    return_value=None,
                ),
                patch(
                    "app.downloader.storage.thumbnails.imageio_ffmpeg.get_ffmpeg_exe",
                    return_value="bundled-ffmpeg",
                ),
                patch(
                    "app.downloader.storage.thumbnails.subprocess.run",
                    side_effect=write_video_frame,
                ) as run_ffmpeg,
            ):
                self.assertEqual(ensure_thumbnail(media_path, destination), destination)

            self.assertEqual(destination.read_bytes(), b"video-thumbnail")
            command = run_ffmpeg.call_args.args[0]
            self.assertEqual(command[0], "bundled-ffmpeg")
            self.assertIn(str(media_path), command)

    def test_video_thumbnail_prefers_system_ffmpeg(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            media_path = root / "clip.mp4"
            media_path.write_bytes(b"video")
            destination = thumbnail_path(root, media_path.name)

            def write_video_frame(
                command: list[str], **options: object
            ) -> SimpleNamespace:
                self.assertEqual(options["timeout"], 30)
                Path(command[-1]).write_bytes(b"video-thumbnail")
                return SimpleNamespace(returncode=0, stderr="")

            with (
                patch(
                    "app.downloader.storage.thumbnails.shutil.which",
                    return_value="system-ffmpeg",
                ),
                patch(
                    "app.downloader.storage.thumbnails.imageio_ffmpeg.get_ffmpeg_exe"
                ) as bundled_ffmpeg,
                patch(
                    "app.downloader.storage.thumbnails.subprocess.run",
                    side_effect=write_video_frame,
                ) as run_ffmpeg,
            ):
                ensure_thumbnail(media_path, destination)

            self.assertEqual(run_ffmpeg.call_args.args[0][0], "system-ffmpeg")
            bundled_ffmpeg.assert_not_called()


if __name__ == "__main__":
    unittest.main()
