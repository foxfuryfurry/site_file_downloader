"""Filesystem operations for downloaded files."""

from datetime import datetime, timezone
import json
import threading
from pathlib import Path
from urllib.parse import unquote, urlparse

from ..sources.rule34_adapter import Rule34Post
from ..transport.http_client import download_to_path
from ..transport.rate_limiter import RequestRateLimiter


def save_post(
    post: Rule34Post,
    downloads_dir: Path,
    rate_limiter: RequestRateLimiter,
    cancel_event: threading.Event | None = None,
) -> Path:
    """Download one post using a safe, stable filename based on its post ID."""
    extension = Path(unquote(urlparse(post.file_url).path)).suffix.lower()
    destination = downloads_dir / f"rule34_{post.post_id}{extension}"
    temporary_path = destination.with_suffix(destination.suffix + ".part")
    metadata_path = destination.with_suffix(".json")
    temporary_metadata_path = metadata_path.with_suffix(".json.part")
    try:
        downloads_dir.mkdir(parents=True, exist_ok=True)
        if cancel_event is None:
            download_to_path(post.file_url, temporary_path, "rule34", rate_limiter)
        else:
            download_to_path(
                post.file_url, temporary_path, "rule34", rate_limiter, cancel_event
            )
        temporary_path.replace(destination)
        raw_tags = post.raw_data.get("tags", post.tags)
        if not isinstance(raw_tags, str):
            raise ValueError("Rule34 post tags must be a string.")
        metadata = {
            "id": post.raw_data.get("id", post.post_id),
            "tags": raw_tags.split(),
            "source": post.raw_data.get("source"),
            "title": "",
            "description": "",
            "downloaded_at": datetime.now(timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
        }
        with temporary_metadata_path.open("w", encoding="utf-8") as metadata_file:
            json.dump(metadata, metadata_file, ensure_ascii=False, indent=2)
            metadata_file.write("\n")
        temporary_metadata_path.replace(metadata_path)
    except (OSError, TypeError, ValueError) as exc:
        temporary_path.unlink(missing_ok=True)
        temporary_metadata_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"Could not save post {post.post_id} or its metadata sidecar: {exc}"
        ) from exc
    except RuntimeError:
        temporary_path.unlink(missing_ok=True)
        temporary_metadata_path.unlink(missing_ok=True)
        raise
    return destination
