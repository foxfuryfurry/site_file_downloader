"""Loopback-only web UI and task API, implemented with the standard library."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import threading
from typing import Any
from urllib.parse import urlsplit
import webbrowser

from .services.download_tasks import DownloadTask, DownloadTaskManager


STATIC_DIR = Path(__file__).with_name("web") / "static"
MAX_REQUEST_BYTES = 16_384
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/static/styles.css": ("styles.css", "text/css; charset=utf-8"),
}


def is_local_origin(
    host_header: str, origin: str | None, expected_port: int, require_origin: bool
) -> bool:
    """Allow only the local app host and, for mutations, its same-origin callers."""
    try:
        host = urlsplit(f"//{host_header}")
        if (
            host.hostname not in {"127.0.0.1", "localhost"}
            or host.port != expected_port
        ):
            return False
        if not require_origin or origin is None:
            return True
        parsed_origin = urlsplit(origin)
        return (
            parsed_origin.scheme == "http"
            and parsed_origin.hostname in {"127.0.0.1", "localhost"}
            and parsed_origin.port == expected_port
            and parsed_origin.path == ""
            and not parsed_origin.query
            and not parsed_origin.fragment
        )
    except ValueError:
        return False


class LocalHttpServer(ThreadingHTTPServer):
    """HTTP server that remains bound to the local machine."""

    daemon_threads = True
    allow_reuse_address = True
    address_family = socket.AF_INET

    def __init__(
        self,
        server_address: tuple[str, int],
        task_manager: DownloadTaskManager,
    ) -> None:
        self.task_manager = task_manager
        super().__init__(server_address, LocalRequestHandler)


class LocalRequestHandler(BaseHTTPRequestHandler):
    """Serve only the bundled UI and a small same-origin task API."""

    server: LocalHttpServer

    def do_GET(self) -> None:
        if not self._is_local_request():
            self._send_json(403, {"error": "Requests must use the local app address."})
            return

        path = urlsplit(self.path).path
        if path in STATIC_FILES:
            self._serve_static(path)
            return
        if path == "/api/tasks":
            self._send_json(405, {"error": "Use POST to start a download."})
            return
        if path.startswith("/api/tasks/"):
            self._get_task(path.removeprefix("/api/tasks/"))
            return
        self._send_json(404, {"error": "Not found."})

    def do_POST(self) -> None:
        if not self._is_local_request(check_origin=True):
            self._send_json(403, {"error": "Requests must originate from this local app."})
            return
        if urlsplit(self.path).path != "/api/tasks":
            self._send_json(404, {"error": "Not found."})
            return

        if self.headers.get_content_type() != "application/json":
            self._send_json(415, {"error": "Send a JSON request body."})
            return
        try:
            content_length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._send_json(400, {"error": "A valid Content-Length header is required."})
            return
        if content_length < 0 or content_length > MAX_REQUEST_BYTES:
            self._send_json(413, {"error": "Request body is too large."})
            return

        try:
            payload = json.loads(self.rfile.read(content_length))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"error": "Request body must be valid JSON."})
            return
        if not isinstance(payload, dict) or not isinstance(payload.get("tags"), str):
            self._send_json(400, {"error": "The JSON body must contain string tags."})
            return
        tags = payload["tags"].strip()
        if not tags:
            self._send_json(400, {"error": "Enter at least one search tag."})
            return
        if len(tags) > 500:
            self._send_json(400, {"error": "Search tags must be 500 characters or fewer."})
            return

        try:
            task = self.server.task_manager.start(tags)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except RuntimeError as exc:
            self._send_json(409, {"error": str(exc)})
        else:
            self._send_json(202, self.server.task_manager.snapshot(task))

    def do_DELETE(self) -> None:
        if not self._is_local_request(check_origin=True):
            self._send_json(403, {"error": "Requests must originate from this local app."})
            return

        path = urlsplit(self.path).path
        prefix = "/api/tasks/"
        task_id = path[len(prefix) :] if path.startswith(prefix) else ""
        if not task_id or "/" in task_id:
            self._send_json(404, {"error": "Not found."})
            return
        task = self.server.task_manager.get(task_id)
        if task is None:
            self._send_json(404, {"error": "Download task not found."})
            return
        requested = self.server.task_manager.cancel(task_id)
        self._send_json(
            202 if requested else 200,
            {
                **self.server.task_manager.snapshot(task),
                "cancellation_requested": requested,
            },
        )

    def _get_task(self, route: str) -> None:
        parts = route.split("/")
        if len(parts) not in (1, 2) or not parts[0]:
            self._send_json(404, {"error": "Not found."})
            return
        task = self.server.task_manager.get(parts[0])
        if task is None:
            self._send_json(404, {"error": "Download task not found."})
            return
        if len(parts) == 1:
            self._send_json(200, self.server.task_manager.snapshot(task))
            return
        if parts[1] != "events":
            self._send_json(404, {"error": "Not found."})
            return
        self._stream_events(task)

    def _stream_events(self, task: DownloadTask) -> None:
        last_event_id = self.headers.get("Last-Event-ID", "0")
        try:
            sequence = int(last_event_id)
        except ValueError:
            self._send_json(400, {"error": "Last-Event-ID must be an integer."})
            return
        if sequence < 0:
            self._send_json(400, {"error": "Last-Event-ID must be non-negative."})
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store")
        self.send_header("X-Accel-Buffering", "no")
        self._security_headers()
        self.end_headers()
        try:
            while True:
                events, finished = self.server.task_manager.events_after(
                    task, sequence, timeout=15
                )
                for event in events:
                    sequence = event["sequence"]
                    data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                    self.wfile.write(
                        f"id: {sequence}\nevent: update\ndata: {data}\n\n".encode()
                    )
                if not events:
                    self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
                if finished:
                    break
        except (BrokenPipeError, ConnectionResetError):
            return

    def _serve_static(self, path: str) -> None:
        filename, content_type = STATIC_FILES[path]
        try:
            content = (STATIC_DIR / filename).read_bytes()
        except OSError:
            self._send_json(500, {"error": "The bundled web UI could not be read."})
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self._security_headers()
        self.end_headers()
        self.wfile.write(content)

    def _is_local_request(self, check_origin: bool = False) -> bool:
        return is_local_origin(
            self.headers.get("Host", ""),
            self.headers.get("Origin"),
            self.server.server_port,
            check_origin,
        )

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'",
        )

    def log_message(self, format: str, *args: Any) -> None:
        if args and str(args[0]).startswith(("4", "5")):
            super().log_message(format, *args)


def run_web_app(port: int = 8765, open_browser: bool = True) -> None:
    """Serve the browser UI on loopback until interrupted."""
    server = LocalHttpServer(("127.0.0.1", port), DownloadTaskManager())
    address = f"http://127.0.0.1:{server.server_port}/"
    print(f"Downloader web UI: {address}", flush=True)
    if open_browser:
        threading.Timer(0.25, webbrowser.open, args=(address,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down the local web UI.", flush=True)
    finally:
        server.server_close()
