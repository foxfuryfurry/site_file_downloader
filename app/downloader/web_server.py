"""Loopback-only web UI and task API, implemented with the standard library."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import mimetypes
import os
from pathlib import Path
import socket
import threading
from typing import Any
from urllib.parse import quote, unquote, urlsplit
import webbrowser

from .config import CONFIG_PATH, load_config
from .services.download_tasks import DownloadTask, DownloadTaskManager
from .storage.history import top_searches


STATIC_DIR = Path(__file__).with_name("web") / "static"
MAX_REQUEST_BYTES = 16_384
MEDIA_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".webm",
}
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/static/styles.css": ("styles.css", "text/css; charset=utf-8"),
}


def gallery_items(downloads_dir: Path) -> list[dict[str, Any]]:
    """Return media directly under the configured downloads folder."""
    if not downloads_dir.exists():
        return []
    root = downloads_dir.resolve()
    items: list[dict[str, Any]] = []
    for path in root.iterdir():
        if path.suffix.lower() not in MEDIA_EXTENSIONS:
            continue
        try:
            resolved_path = path.resolve(strict=True)
            resolved_path.relative_to(root)
            if not resolved_path.is_file():
                continue
            details = resolved_path.stat()
        except (OSError, ValueError):
            continue
        items.append(
            {
                "name": path.name,
                "url": f"/api/gallery/media/{quote(path.name, safe='')}",
                "kind": "video" if path.suffix.lower() in {".mp4", ".webm"} else "image",
                "size": details.st_size,
                "modified": details.st_mtime,
            }
        )
    return sorted(items, key=lambda item: item["modified"], reverse=True)


def read_public_config() -> dict[str, Any]:
    """Return editable settings without revealing credential values."""
    config = load_config()
    credentials_configured = False
    try:
        keys_data = json.loads(config.keys_file.read_text(encoding="utf-8"))
        credentials = keys_data["services"]["rule34"]
        if not isinstance(credentials, dict):
            return {
                "downloads_dir": str(config.downloads_dir),
                "rule34_requests_per_second": config.rate_limits.get("rule34", 1.0),
                "credentials_configured": False,
            }
        credentials_configured = bool(
            isinstance(credentials.get("api_key"), str)
            and credentials["api_key"].strip()
            and str(credentials.get("user_id", "")).strip()
        )
    except (OSError, ValueError, KeyError, TypeError):
        credentials_configured = False
    return {
        "downloads_dir": str(config.downloads_dir),
        "rule34_requests_per_second": config.rate_limits.get("rule34", 1.0),
        "credentials_configured": credentials_configured,
    }


def update_public_config(payload: dict[str, Any]) -> None:
    """Update the download folder, Rule34 rate, and optional credentials."""
    current_config = load_config()
    downloads_dir = payload.get("downloads_dir")
    if not isinstance(downloads_dir, str) or not downloads_dir.strip():
        raise ValueError("Choose a download folder.")
    downloads_dir = downloads_dir.strip()
    if len(downloads_dir) > 4096:
        raise ValueError("Download folder path is too long.")

    requests_per_second = payload.get("rule34_requests_per_second")
    if (
        isinstance(requests_per_second, bool)
        or not isinstance(requests_per_second, (int, float))
        or requests_per_second <= 0
        or requests_per_second > 1_000_000
        or not math.isfinite(float(requests_per_second))
    ):
        raise ValueError(
            "Rule34 requests per second must be greater than 0 and no more than "
            "1,000,000."
        )

    api_key = payload.get("api_key", "")
    user_id = payload.get("user_id", "")
    if not isinstance(api_key, str) or not isinstance(user_id, str):
        raise ValueError("Credentials must be strings.")
    api_key = api_key.strip()
    user_id = user_id.strip()
    if bool(api_key) != bool(user_id):
        raise ValueError("Enter both Rule34 credentials, or leave both blank.")

    with CONFIG_PATH.open(encoding="utf-8") as config_file:
        config_data = json.load(config_file)
    if not isinstance(config_data, dict):
        raise ValueError("Configuration must be a JSON object.")
    config_data["downloads_dir"] = downloads_dir
    rate_limits = config_data.get("rate_limits")
    if not isinstance(rate_limits, dict):
        raise ValueError("Configuration field 'rate_limits' must be an object.")
    rule34_settings = rate_limits.get("rule34", {})
    if not isinstance(rule34_settings, dict):
        raise ValueError("Rule34 rate limit must be an object.")
    rule34_settings["requests_per_second"] = float(requests_per_second)
    rate_limits["rule34"] = rule34_settings

    keys_data: dict[str, Any] | None = None
    if api_key:
        try:
            with current_config.keys_file.open(encoding="utf-8") as keys_file:
                loaded_keys = json.load(keys_file)
        except FileNotFoundError:
            loaded_keys = {}
        if not isinstance(loaded_keys, dict):
            raise ValueError("Credentials file must contain a JSON object.")
        keys_data = loaded_keys
        services = keys_data.setdefault("services", {})
        if not isinstance(services, dict):
            raise ValueError("Credentials field 'services' must be an object.")
        rule34_credentials = services.setdefault("rule34", {})
        if not isinstance(rule34_credentials, dict):
            raise ValueError("Rule34 credentials must be an object.")
        rule34_credentials["api_key"] = api_key
        rule34_credentials["user_id"] = user_id

    config_temp = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".tmp")
    keys_path = current_config.keys_file if keys_data is not None else None
    keys_temp = keys_path.with_suffix(keys_path.suffix + ".tmp") if keys_path else None
    try:
        _write_json(config_temp, config_data)
        if keys_temp is not None and keys_data is not None:
            keys_temp.parent.mkdir(parents=True, exist_ok=True)
            _write_json(keys_temp, keys_data)
        if keys_temp is not None and keys_path is not None:
            keys_temp.replace(keys_path)
        config_temp.replace(CONFIG_PATH)
    except OSError:
        config_temp.unlink(missing_ok=True)
        if keys_temp is not None:
            keys_temp.unlink(missing_ok=True)
        raise

    load_config(CONFIG_PATH)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as output:
        json.dump(value, output, indent=2, ensure_ascii=False)
        output.write("\n")


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
        if path == "/api/config":
            try:
                self._send_json(200, read_public_config())
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                self._send_json(500, {"error": str(exc)})
            return
        if path == "/api/gallery":
            try:
                config = load_config()
                self._send_json(200, {"items": gallery_items(config.downloads_dir)})
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                self._send_json(500, {"error": str(exc)})
            return
        if path == "/api/searches/top":
            try:
                config = load_config()
                self._send_json(
                    200,
                    {"searches": top_searches(config.history_file, "rule34", 5)},
                )
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                self._send_json(500, {"error": str(exc)})
            return
        if path.startswith("/api/gallery/media/"):
            self._serve_gallery_media(path.removeprefix("/api/gallery/media/"))
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
            if urlsplit(self.path).path == "/api/config":
                self._save_config()
                return
            self._send_json(404, {"error": "Not found."})
            return

        payload = self._read_json_body()
        if payload is None:
            return
        if not isinstance(payload.get("tags"), str):
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

    def _save_config(self) -> None:
        payload = self._read_json_body()
        if payload is None:
            return
        try:
            update_public_config(payload)
            response = read_public_config()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, response)

    def _read_json_body(self) -> dict[str, Any] | None:
        if self.headers.get_content_type() != "application/json":
            self._send_json(415, {"error": "Send a JSON request body."})
            return None
        try:
            content_length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._send_json(400, {"error": "A valid Content-Length header is required."})
            return None
        if content_length < 0 or content_length > MAX_REQUEST_BYTES:
            self._send_json(413, {"error": "Request body is too large."})
            return None
        try:
            payload = json.loads(self.rfile.read(content_length))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"error": "Request body must be valid JSON."})
            return None
        if not isinstance(payload, dict):
            self._send_json(400, {"error": "Request body must be a JSON object."})
            return None
        return payload

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

    def _serve_gallery_media(self, encoded_name: str) -> None:
        filename = unquote(encoded_name)
        if (
            not filename
            or filename in {".", ".."}
            or "/" in filename
            or "\\" in filename
            or Path(filename).suffix.lower() not in MEDIA_EXTENSIONS
        ):
            self._send_json(404, {"error": "Media file not found."})
            return
        try:
            root = load_config().downloads_dir.resolve()
            media_path = (root / filename).resolve(strict=True)
            media_path.relative_to(root)
            if not media_path.is_file():
                raise FileNotFoundError(filename)
            media_file = media_path.open("rb")
        except (OSError, ValueError):
            self._send_json(404, {"error": "Media file not found."})
            return
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        try:
            with media_file:
                content_length = os.fstat(media_file.fileno()).st_size
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(content_length))
                self.send_header("Cache-Control", "private, max-age=60")
                self._security_headers()
                self.end_headers()
                while chunk := media_file.read(1024 * 128):
                    self.wfile.write(chunk)
        except OSError:
            return

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
