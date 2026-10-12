"""Coordinate Rule34 searches, file downloads, and duplicate history."""

from collections.abc import Callable

from ..config import AppConfig, load_rule34_credentials
from ..sources.rule34_adapter import search_posts
from ..storage.filesystem import save_post
from ..storage.history import downloaded_ids, record_download, record_search
from ..transport.rate_limiter import RequestRateLimiter


ProgressCallback = Callable[[str], None]


def download_by_tags(
    tags: str,
    config: AppConfig,
    report: ProgressCallback,
) -> tuple[int, int, int]:
    """Download new adult-rated results and persist successful post IDs."""
    site = "rule34"
    record_search(config.history_file, site, tags)
    credentials = load_rule34_credentials(config.keys_file)
    rate_limiter = RequestRateLimiter(config.rate_limits)
    posts = search_posts(tags, credentials, rate_limiter)
    if not posts:
        report("No eligible adult-rated posts matched those tags.")
        return 0, 0, 0

    seen_ids = downloaded_ids(config.history_file, site)
    downloaded = skipped = failed = 0
    for post in posts:
        if post.post_id in seen_ids:
            skipped += 1
            continue
        try:
            file_path = save_post(post, config.downloads_dir, rate_limiter)
        except RuntimeError as exc:
            failed += 1
            report(f"Post {post.post_id}: {exc}")
            continue
        record_download(config.history_file, site, post.post_id)
        seen_ids.add(post.post_id)
        downloaded += 1
        report(f"Downloaded post {post.post_id} to {file_path}")

    report(f"Finished: {downloaded} downloaded, {skipped} already in history, {failed} failed.")
    return downloaded, skipped, failed
