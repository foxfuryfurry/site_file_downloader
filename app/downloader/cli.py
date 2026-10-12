"""Application entry point."""

import argparse

from .web_server import run_web_app


def main() -> int:
    """Launch the loopback-only browser application."""
    parser = argparse.ArgumentParser(description="Run the local downloader web UI.")
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="local HTTP port (default: 8765; use 0 to select an available port)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="start the local server without opening a browser window",
    )
    arguments = parser.parse_args()
    if not 0 <= arguments.port <= 65535:
        parser.error("--port must be between 0 and 65535.")
    run_web_app(port=arguments.port, open_browser=not arguments.no_browser)
    return 0
