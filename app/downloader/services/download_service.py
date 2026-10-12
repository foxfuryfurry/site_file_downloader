"""Coordinate Rule34 searches, file downloads, and duplicate history."""

from collections.abc import Callable
import threading

from ..config import AppConfig, load_rule34_credentials
from ..errors import DownloadCancelled
from ..models import DownloadProgress
from ..sources.rule34_adapter import search_posts
from ..storage.filesystem import save_post
from ..storage.history import downloaded_ids, record_download, record_search
from ..transport.rate_limiter import RequestRateLimiter


ProgressCallback = Callable[[str], None]
StructuredProgressCallback = Callable[[DownloadProgress], None]


def download_by_tags(
    tags: str,
    config: AppConfig,
    report: ProgressCallback,
    *,
    cancel_event: threading.Event | None = None,
    progress: StructuredProgressCallback | None = None,
) -> tuple[int, int, int]:
    """Download new adult-rated results and persist successful post IDs."""
    if progress is not None:
        progress(DownloadProgress(phase="searching"))
    site = "rule34"
    record_search(config.history_file, site, tags)
    credentials = load_rule34_credentials(config.keys_file)
    rate_limiter = RequestRateLimiter(config.rate_limits)
    if cancel_event is None:
        posts = search_posts(tags, credentials, rate_limiter)
    else:
        posts = search_posts(tags, credentials, rate_limiter, cancel_event)
    if not posts:
        report(f'No images/videos with the tags: "{tags}"')
        return 0, 0, 0

    seen_ids = downloaded_ids(config.history_file, site)
    downloaded = skipped = failed = 0
    total = len(posts)
    if progress is not None:
        progress(DownloadProgress(phase="downloading", total=total))
    for completed, post in enumerate(posts, start=1):
        if cancel_event is not None and cancel_event.is_set():
            raise DownloadCancelled("Download cancelled.")
        if post.post_id in seen_ids:
            skipped += 1
            if progress is not None:
                progress(
                    DownloadProgress("downloading", completed, total, downloaded, skipped, failed)
                )
            continue
        try:
            if cancel_event is None:
                file_path = save_post(post, config.downloads_dir, rate_limiter)
            else:
                file_path = save_post(
                    post, config.downloads_dir, rate_limiter, cancel_event
                )
        except DownloadCancelled:
            raise
        except RuntimeError as exc:
            failed += 1
            report(f"Post {post.post_id}: {exc}")
            if progress is not None:
                progress(
                    DownloadProgress("downloading", completed, total, downloaded, skipped, failed)
                )
            continue
        record_download(config.history_file, site, post.post_id)
        seen_ids.add(post.post_id)
        downloaded += 1
        report(f"Downloaded post {post.post_id} to {file_path}")
        if progress is not None:
            progress(
                DownloadProgress("downloading", completed, total, downloaded, skipped, failed)
            )

    report(
        f"Finished: {downloaded} downloaded, {skipped} already in history, "
        f"{failed} failed."
    )
    return downloaded, skipped, failed
