"""Thumbnail generation for gallery previews."""

from pathlib import Path
import shutil
import subprocess
import tempfile

from PIL import Image, ImageOps
import imageio_ffmpeg


VIDEO_EXTENSIONS = {".mp4", ".webm"}
THUMBNAIL_SIZE = (320, 320)


def thumbnail_path(downloads_dir: Path, filename: str) -> Path:
    """Return the cached thumbnail path for a media filename."""
    return downloads_dir / ".thumbnails" / f"{filename}.jpg"


def ensure_thumbnail(
    media_path: Path, destination: Path, *, force: bool = False
) -> Path:
    """Create or refresh a JPEG preview if it is missing or older than its source."""
    if not media_path.is_file():
        raise FileNotFoundError(f"Media file not found: {media_path.name}")
    source_modified = media_path.stat().st_mtime_ns
    try:
        if not force and destination.stat().st_mtime_ns >= source_modified:
            return destination
    except FileNotFoundError:
        pass

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=destination.parent, suffix=".jpg", delete=False
    ) as temporary_file:
        temporary_path = Path(temporary_file.name)
    try:
        if media_path.suffix.lower() in VIDEO_EXTENSIONS:
            _create_video_thumbnail(media_path, temporary_path)
        else:
            _create_image_thumbnail(media_path, temporary_path)
        temporary_path.replace(destination)
    except (OSError, RuntimeError, ValueError, Image.DecompressionBombError) as exc:
        temporary_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"Could not create thumbnail for {media_path.name}: {exc}"
        ) from exc
    return destination


def recompute_thumbnails(downloads_dir: Path) -> dict[str, object]:
    """Rebuild thumbnails for every supported media file in the download folder."""
    if not downloads_dir.exists():
        return {"processed": 0, "succeeded": 0, "failures": []}

    root = downloads_dir.resolve()
    cache_dir = root / ".thumbnails"
    if cache_dir.is_symlink():
        raise OSError(
            "Cannot recompute thumbnails because .thumbnails is a symbolic link."
        )
    if cache_dir.exists():
        if not cache_dir.is_dir():
            raise OSError(".thumbnails exists but is not a directory.")
        shutil.rmtree(cache_dir)

    media_files = sorted(
        path
        for path in root.iterdir()
        if path.suffix.lower()
        in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".webm"}
        and path.is_file()
    )
    failures: list[dict[str, str]] = []
    for media_path in media_files:
        try:
            ensure_thumbnail(
                media_path,
                thumbnail_path(root, media_path.name),
                force=True,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            failures.append({"name": media_path.name, "error": str(exc)})

    return {
        "processed": len(media_files),
        "succeeded": len(media_files) - len(failures),
        "failures": failures,
    }


def _create_image_thumbnail(media_path: Path, destination: Path) -> None:
    with Image.open(media_path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail(THUMBNAIL_SIZE)
        image.save(destination, format="JPEG", quality=82, optimize=True)


def _create_video_thumbnail(media_path: Path, destination: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        try:
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except (OSError, RuntimeError) as exc:
            raise RuntimeError(
                "FFmpeg is unavailable. Install dependencies with "
                "`python -m pip install -r requirements.txt`, or install FFmpeg "
                "and make it available on PATH."
            ) from exc

    errors: list[str] = []
    for timestamp in ("1", "0"):
        command = [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            timestamp,
            "-i",
            str(media_path),
            "-frames:v",
            "1",
            "-vf",
            "scale=320:320:force_original_aspect_ratio=decrease",
            "-q:v",
            "4",
            "-f",
            "image2",
            "-y",
            str(destination),
        ]
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("FFmpeg timed out while generating a thumbnail.") from exc
        except OSError as exc:
            raise RuntimeError(f"Could not run FFmpeg: {exc}") from exc
        if result.returncode == 0 and destination.stat().st_size > 0:
            return
        errors.append(
            result.stderr.strip() or f"FFmpeg exited with status {result.returncode}."
        )

    raise RuntimeError(f"FFmpeg could not decode this video: {errors[-1]}")
