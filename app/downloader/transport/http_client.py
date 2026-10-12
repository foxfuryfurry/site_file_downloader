"""Small standard-library HTTP helpers for the Rule34 API and media files."""

import json
import threading
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from ..errors import DownloadCancelled
from .rate_limiter import RequestRateLimiter


USER_AGENT = "TagFileDownloader/1.0 (personal use)"
TIMEOUT_SECONDS = 30
DIAGNOSTIC_BODY_LIMIT = 600


def _request(url: str) -> Request:
    return Request(url, headers={"User-Agent": USER_AGENT})


def _response_diagnostic(
    url: str,
    status: int,
    content_type: str,
    body: bytes,
) -> str:
    """Build a bounded response excerpt while redacting credentials in the URL."""
    parsed_url = urlparse(url)
    endpoint = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"
    text = body.decode("utf-8", errors="replace")
    for parameter in ("api_key", "user_id"):
        for secret in parse_qs(parsed_url.query).get(parameter, []):
            if secret:
                text = text.replace(secret, "[REDACTED]")
    excerpt = " ".join(text.split())[:DIAGNOSTIC_BODY_LIMIT]
    if len(" ".join(text.split())) > DIAGNOSTIC_BODY_LIMIT:
        excerpt += "…"
    return (
        f"HTTP {status}; Content-Type: {content_type or 'unknown'}; "
        f"endpoint: {endpoint}; response: {excerpt or '[empty body]'}"
    )


def get_json(
    url: str,
    site: str,
    rate_limiter: RequestRateLimiter,
    cancel_event: threading.Event | None = None,
) -> object:
    """Fetch and decode a JSON response."""
    if cancel_event is None:
        rate_limiter.wait(site)
    else:
        rate_limiter.wait(site, cancel_event)
    try:
        with urlopen(_request(url), timeout=TIMEOUT_SECONDS) as response:
            body = response.read()
            status = response.status
            content_type = response.headers.get("Content-Type", "")
    except HTTPError as exc:
        body = exc.read()
        raise RuntimeError(
            "Could not fetch the Rule34 API response: "
            + _response_diagnostic(
                url,
                exc.code,
                exc.headers.get("Content-Type", "") if exc.headers else "",
                body,
            )
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(
            f"Could not reach the Rule34 API endpoint "
            f"{urlparse(url).scheme}://{urlparse(url).netloc}{urlparse(url).path} "
            f"({type(exc).__name__}: {exc.reason if isinstance(exc, URLError) else exc})."
        ) from exc

    if not body.strip():
        return []

    try:
        return json.loads(body.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise RuntimeError(
            "The Rule34 API response was not valid UTF-8: "
            + _response_diagnostic(url, status, content_type, body)
        ) from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"The Rule34 API returned invalid JSON "
            f"(line {exc.lineno}, column {exc.colno}): "
            + _response_diagnostic(url, status, content_type, body)
        ) from exc


def download_to_path(
    url: str,
    destination: Path,
    site: str,
    rate_limiter: RequestRateLimiter,
    cancel_event: threading.Event | None = None,
) -> None:
    """Stream a remote file to a local destination."""
    if cancel_event is None:
        rate_limiter.wait(site)
    else:
        rate_limiter.wait(site, cancel_event)
    try:
        with urlopen(_request(url), timeout=TIMEOUT_SECONDS) as response:
            with destination.open("wb") as output:
                while chunk := response.read(1024 * 128):
                    if cancel_event is not None and cancel_event.is_set():
                        raise DownloadCancelled("Download cancelled.")
                    output.write(chunk)
                if cancel_event is not None and cancel_event.is_set():
                    raise DownloadCancelled("Download cancelled.")
    except DownloadCancelled:
        destination.unlink(missing_ok=True)
        raise
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"Could not download file: {exc}") from exc
