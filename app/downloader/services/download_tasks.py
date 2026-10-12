"""Run downloads independently of the local web server request threads."""

from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
import secrets
import threading
from typing import Any

from ..config import AppConfig, load_config
from ..errors import DownloadCancelled
from ..models import DownloadProgress
from .download_service import download_by_tags


TERMINAL_STATES = {"complete", "cancelled", "error"}
MAX_RETAINED_TASKS = 32
MAX_RETAINED_EVENTS = 1024
DownloadRunner = Callable[..., tuple[int, int, int]]


@dataclass
class DownloadTask:
    """In-memory state and replayable events for one download."""

    task_id: str
    tags: str
    state: str = "queued"
    cancel_event: threading.Event = field(default_factory=threading.Event)
    condition: threading.Condition = field(default_factory=threading.Condition)
    events: deque[dict[str, Any]] = field(
        default_factory=lambda: deque(maxlen=MAX_RETAINED_EVENTS)
    )
    sequence: int = 0
    progress: dict[str, Any] | None = None
    result: dict[str, int] | None = None
    error: str | None = None


class DownloadTaskManager:
    """Stable start, progress, cancellation, and error boundary for the UI."""

    def __init__(
        self,
        config_loader: Callable[[], AppConfig] = load_config,
        download_runner: DownloadRunner = download_by_tags,
    ) -> None:
        self._config_loader = config_loader
        self._download_runner = download_runner
        self._lock = threading.Lock()
        self._tasks: dict[str, DownloadTask] = {}
        self._active_task_id: str | None = None

    def start(self, tags: str) -> DownloadTask:
        normalized_tags = tags.strip()
        if not normalized_tags:
            raise ValueError("Enter at least one search tag.")

        with self._lock:
            active = self._tasks.get(self._active_task_id or "")
            if active is not None:
                with active.condition:
                    if active.state not in TERMINAL_STATES:
                        raise RuntimeError("A download is already running.")
            self._prune_tasks()
            if len(self._tasks) >= MAX_RETAINED_TASKS:
                raise RuntimeError("Too many recent tasks; restart the app to continue.")

            task = DownloadTask(secrets.token_urlsafe(16), normalized_tags)
            self._tasks[task.task_id] = task
            self._active_task_id = task.task_id

        self._publish(task, "state", state="queued", message="Download queued.")
        worker = threading.Thread(
            target=self._run_task,
            args=(task,),
            name=f"download-{task.task_id}",
            daemon=True,
        )
        try:
            worker.start()
        except RuntimeError:
            self._set_terminal(task, "error", error="Could not start the download worker.")
            raise
        return task

    def get(self, task_id: str) -> DownloadTask | None:
        with self._lock:
            return self._tasks.get(task_id)

    def cancel(self, task_id: str) -> bool:
        task = self.get(task_id)
        if task is None:
            return False
        with task.condition:
            if task.state in TERMINAL_STATES or task.cancel_event.is_set():
                return False
            task.cancel_event.set()
            self._publish(
                task,
                "state",
                state="cancelling",
                message="Cancellation requested.",
            )
        return True

    def snapshot(self, task: DownloadTask) -> dict[str, Any]:
        with task.condition:
            return {
                "id": task.task_id,
                "tags": task.tags,
                "state": task.state,
                "progress": task.progress,
                "result": task.result,
                "error": task.error,
                "event_sequence": task.sequence,
            }

    def events_after(
        self, task: DownloadTask, sequence: int, timeout: float = 15.0
    ) -> tuple[list[dict[str, Any]], bool]:
        with task.condition:
            if not any(event["sequence"] > sequence for event in task.events):
                if task.state not in TERMINAL_STATES:
                    task.condition.wait(timeout)

            events = list(task.events)
            available = [event for event in events if event["sequence"] > sequence]
            if events and sequence < events[0]["sequence"] - 1:
                available.insert(
                    0,
                    {
                        "sequence": events[0]["sequence"] - 1,
                        "type": "snapshot",
                        "state": task.state,
                        "progress": task.progress,
                        "message": "Some earlier progress events are no longer retained.",
                    },
                )
            return available, task.state in TERMINAL_STATES and not available

    def _prune_tasks(self) -> None:
        for task_id, task in tuple(self._tasks.items()):
            if len(self._tasks) < MAX_RETAINED_TASKS:
                break
            with task.condition:
                if task.state in TERMINAL_STATES:
                    del self._tasks[task_id]

    def _run_task(self, task: DownloadTask) -> None:
        with task.condition:
            if task.cancel_event.is_set():
                cancelled_before_start = True
            else:
                cancelled_before_start = False
                self._publish(
                    task, "state", state="running", message="Searching for posts."
                )
        if cancelled_before_start:
            self._set_terminal(task, "cancelled", message="Download cancelled.")
            return
        try:
            counts = self._download_runner(
                task.tags,
                self._config_loader(),
                lambda message: self._publish(task, "log", message=message),
                cancel_event=task.cancel_event,
                progress=lambda progress: self._report_progress(task, progress),
            )
        except DownloadCancelled:
            self._set_terminal(task, "cancelled", message="Download cancelled.")
        except Exception as exc:
            self._set_terminal(task, "error", error=str(exc))
        else:
            result = {
                "downloaded": counts[0],
                "skipped": counts[1],
                "failed": counts[2],
            }
            self._set_terminal(task, "complete", result=result)

    def _report_progress(
        self, task: DownloadTask, progress: DownloadProgress
    ) -> None:
        values = asdict(progress)
        with task.condition:
            task.progress = values
        self._publish(task, "progress", progress=values)

    def _set_terminal(
        self,
        task: DownloadTask,
        state: str,
        *,
        result: dict[str, int] | None = None,
        error: str | None = None,
        message: str | None = None,
    ) -> None:
        with task.condition:
            task.state = state
            task.result = result
            task.error = error
        self._publish(
            task,
            state if state in {"cancelled", "error"} else "complete",
            state=state,
            result=result,
            error=error,
            message=message,
        )
        with self._lock:
            if self._active_task_id == task.task_id:
                self._active_task_id = None

    def _publish(
        self,
        task: DownloadTask,
        event_type: str,
        **fields: Any,
    ) -> None:
        with task.condition:
            if "state" in fields:
                task.state = fields["state"]
            task.sequence += 1
            event = {
                "sequence": task.sequence,
                "type": event_type,
                **fields,
            }
            task.events.append(event)
            task.condition.notify_all()
