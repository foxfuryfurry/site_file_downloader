"""Shared application data models."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class DownloadProgress:
    """Structured progress for the browser UI and other future frontends."""

    phase: Literal["searching", "downloading"]
    completed: int = 0
    total: int | None = None
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
