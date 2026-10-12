const form = document.querySelector("#download-form");
const tagsInput = document.querySelector("#tags");
const startButton = document.querySelector("#start-button");
const cancelButton = document.querySelector("#cancel-button");
const formError = document.querySelector("#form-error");
const statusPill = document.querySelector("#status-pill");
const statusLabel = document.querySelector("#status-label");
const progress = document.querySelector("#progress");
const progressLabel = document.querySelector("#progress-label");
const progressCount = document.querySelector("#progress-count");
const activityLog = document.querySelector("#activity-log");

let currentTaskId = null;
let eventSource = null;

function setStatus(state, label) {
  statusPill.className = `status-pill status-${state}`;
  statusLabel.textContent = label;
}

function setBusy(busy) {
  startButton.disabled = busy;
  tagsInput.disabled = busy;
  cancelButton.hidden = !busy;
}

function addLog(message, kind = "") {
  const empty = activityLog.querySelector(".empty-state");
  if (empty) empty.remove();
  const row = document.createElement("p");
  row.className = `log-entry ${kind}`;
  row.textContent = message;
  activityLog.append(row);
  activityLog.scrollTop = activityLog.scrollHeight;
}

function setProgress(value) {
  const total = value.total;
  const finished = value.completed ?? 0;
  if (total === null || total === undefined || total === 0) {
    progress.removeAttribute("value");
    progressLabel.textContent =
      value.phase === "searching" ? "Searching for matching posts" : "Preparing downloads";
    progressCount.textContent = "";
    return;
  }
  progress.value = Math.round((finished / total) * 100);
  progressLabel.textContent = "Downloading and checking results";
  progressCount.textContent = `${finished} / ${total}`;
}

function stopWatching() {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
  currentTaskId = null;
  setBusy(false);
}

function handleEvent(event) {
  const item = JSON.parse(event.data);
  if (item.message) {
    const kind = item.type === "error" ? "log-error" : "";
    addLog(item.message, kind);
  }
  if (item.type === "progress" || item.type === "snapshot") {
    if (item.progress) setProgress(item.progress);
  }
  if (item.state === "queued") {
    setStatus("running", "Queued");
  } else if (item.state === "running") {
    setStatus("running", "In progress");
  } else if (item.state === "cancelling") {
    setStatus("running", "Cancelling");
  }
  if (item.type === "complete") {
    const result = item.result ?? {};
    progress.value = 100;
    progressLabel.textContent = "Download run complete";
    progressCount.textContent = "";
    setStatus("complete", "Complete");
    addLog(
      `${result.downloaded ?? 0} downloaded · ${result.skipped ?? 0} already saved · ${result.failed ?? 0} failed`,
      "log-summary",
    );
    stopWatching();
  } else if (item.type === "cancelled") {
    setStatus("idle", "Cancelled");
    progressLabel.textContent = "Download cancelled";
    stopWatching();
  } else if (item.type === "error") {
    setStatus("error", "Failed");
    progressLabel.textContent = "Download stopped with an error";
    addLog(item.error || "The download could not be completed.", "log-error");
    stopWatching();
  }
}

function watchTask(taskId) {
  currentTaskId = taskId;
  eventSource = new EventSource(`/api/tasks/${encodeURIComponent(taskId)}/events`);
  eventSource.addEventListener("update", handleEvent);
  eventSource.onerror = () => {
    if (eventSource && eventSource.readyState === EventSource.CLOSED) {
      addLog("The progress connection closed. Check the local server and retry.", "log-error");
      setStatus("error", "Connection lost");
      stopWatching();
    }
  };
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  formError.hidden = true;
  const tags = tagsInput.value.trim();
  if (!tags) {
    formError.textContent = "Enter at least one search tag.";
    formError.hidden = false;
    tagsInput.focus();
    return;
  }

  activityLog.replaceChildren();
  progress.value = 0;
  progressLabel.textContent = "Starting search";
  progressCount.textContent = "";
  setStatus("running", "Starting");
  setBusy(true);

  try {
    const response = await fetch("/api/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tags }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Could not start the download.");
    addLog(`Searching for: ${payload.tags}`);
    watchTask(payload.id);
  } catch (error) {
    formError.textContent = error.message;
    formError.hidden = false;
    setStatus("error", "Could not start");
    setBusy(false);
  }
});

cancelButton.addEventListener("click", async () => {
  if (!currentTaskId) return;
  cancelButton.disabled = true;
  try {
    const response = await fetch(`/api/tasks/${encodeURIComponent(currentTaskId)}`, {
      method: "DELETE",
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Cancellation request failed.");
    setStatus("running", "Cancelling");
  } catch (error) {
    addLog(error.message, "log-error");
  } finally {
    cancelButton.disabled = false;
  }
});
