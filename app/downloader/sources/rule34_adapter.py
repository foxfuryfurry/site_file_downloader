"""Search Rule34 for adult-rated posts matching user-supplied tags."""

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode, urlparse

from ..config import Rule34Credentials
from ..transport.rate_limiter import RequestRateLimiter
from ..transport.http_client import get_json


API_URL = "https://api.rule34.xxx/index.php"
PAGE_LIMIT = 1000
EXCLUDED_TAGS = (
    "-loli",
    "-shota",
    "-underage",
    "-child",
    "-toddler",
    "-cub",
    "-teen",
)
ALLOWED_MEDIA_HOSTS = ("rule34.xxx",)
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".webm"}
ADULT_RATINGS = {"e", "explicit"}


@dataclass(frozen=True)
class Rule34Post:
    """Validated metadata for a downloadable Rule34 post."""

    post_id: str
    tags: str
    file_url: str
    raw_data: dict[str, Any] = field(default_factory=dict)


def _is_rule34_host(hostname: str | None) -> bool:
    return bool(
        hostname
        and any(
            hostname == host or hostname.endswith(f".{host}")
            for host in ALLOWED_MEDIA_HOSTS
        )
    )


def search_posts(
    tags: str,
    credentials: Rule34Credentials,
    rate_limiter: RequestRateLimiter,
) -> list[Rule34Post]:
    """Search all result pages, requiring adult-rated posts."""
    user_tags = tags.split()
    if not user_tags:
        raise ValueError("Enter at least one search tag.")

    query_tags = " ".join((*user_tags, "rating:explicit", *EXCLUDED_TAGS))
    params = {
        "page": "dapi",
        "s": "post",
        "q": "index",
        "json": "1",
        "limit": str(PAGE_LIMIT),
        "tags": query_tags,
        "api_key": credentials.api_key,
        "user_id": credentials.user_id,
    }
    posts: list[Rule34Post] = []
    page_id = 0
    while True:
        params["pid"] = str(page_id)
        query = urlencode(params)
        response = get_json(f"{API_URL}?{query}", "rule34", rate_limiter)
        if isinstance(response, str):
            if "auth" in response.lower():
                raise RuntimeError(
                    "Rule34 rejected authentication. Check services.rule34.api_key "
                    "and services.rule34.user_id in app/keys.json."
                )
            raise RuntimeError(
                "The Rule34 API returned an error instead of post results."
            )
        if not isinstance(response, list):
            raise RuntimeError("The Rule34 API returned an unexpected response.")

        for item in response:
            if not isinstance(item, dict):
                continue
            post_id = item.get("id")
            file_url = item.get("file_url")
            post_tags = item.get("tags", "")
            rating = str(item.get("rating", "")).lower()
            if not isinstance(post_id, (int, str)) or not str(post_id).isdigit():
                continue
            if not isinstance(file_url, str) or not isinstance(post_tags, str):
                continue
            if rating not in ADULT_RATINGS:
                continue
            if not _is_rule34_host(urlparse(file_url).hostname):
                continue
            if urlparse(file_url).scheme != "https":
                continue
            file_extension = urlparse(file_url).path.lower()
            if not any(
                file_extension.endswith(extension)
                for extension in ALLOWED_EXTENSIONS
            ):
                continue
            if set(post_tags.lower().split()).intersection(
                {"loli", "shota", "underage", "child", "toddler", "cub", "teen"}
            ):
                continue
            posts.append(Rule34Post(str(post_id), post_tags, file_url, item))

        if len(response) < PAGE_LIMIT:
            break
        page_id += 1

    return posts
