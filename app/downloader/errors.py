"""Application-specific exceptions."""


class DownloadCancelled(RuntimeError):
    """Raised when a download task is cancelled by its caller."""
