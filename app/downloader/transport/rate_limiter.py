"""Thread-safe, per-site request pacing."""

import threading
import time
from collections.abc import Mapping

from ..errors import DownloadCancelled


class RequestRateLimiter:
    """Space request starts according to each site's configured rate."""

    def __init__(self, requests_per_second: Mapping[str, float]) -> None:
        self._intervals = {
            site: 1.0 / requests_per_second
            for site, requests_per_second in requests_per_second.items()
        }
        self._next_request: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(
        self, site: str, cancel_event: threading.Event | None = None
    ) -> None:
        """Wait until the next request for this site is allowed to start."""
        interval = self._intervals.get(site)
        if interval is None:
            if cancel_event is not None and cancel_event.is_set():
                raise DownloadCancelled("Download cancelled.")
            return

        with self._lock:
            now = time.monotonic()
            scheduled_time = self._next_request.get(site, now)
            self._next_request[site] = max(now, scheduled_time) + interval
            delay = scheduled_time - now

        if delay > 0:
            if cancel_event is None:
                time.sleep(delay)
            elif cancel_event.wait(delay):
                raise DownloadCancelled("Download cancelled.")
        if cancel_event is not None and cancel_event.is_set():
            raise DownloadCancelled("Download cancelled.")
