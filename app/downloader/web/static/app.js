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
const galleryTab = document.querySelector("#gallery-tab");
const rule34Tab = document.querySelector("#rule34-tab");
const galleryPanel = document.querySelector("#gallery-panel");
const rule34Panel = document.querySelector("#rule34-panel");
const galleryGrid = document.querySelector("#gallery-grid");
const galleryCount = document.querySelector("#gallery-count");
const galleryError = document.querySelector("#gallery-error");
const galleryDialog = document.querySelector("#gallery-dialog");
const galleryViewerTitle = document.querySelector("#gallery-viewer-title");
const galleryViewerMedia = document.querySelector("#gallery-viewer-media");
const galleryFileDetails = document.querySelector("#gallery-file-details");
const galleryMetadataForm = document.querySelector("#gallery-metadata-form");
const galleryTitleInput = document.querySelector("#gallery-title-input");
const galleryDescriptionInput = document.querySelector("#gallery-description-input");
const galleryTags = document.querySelector("#gallery-tags");
const galleryTagInput = document.querySelector("#gallery-tag-input");
const galleryMetadataStatus = document.querySelector("#gallery-metadata-status");
const galleryCarousel = document.querySelector("#gallery-carousel");
const galleryViewerError = document.querySelector("#gallery-viewer-error");
const deleteGalleryItemButton = document.querySelector("#delete-gallery-item");
const configButton = document.querySelector("#config-button");
const configDialog = document.querySelector("#config-dialog");
const configForm = document.querySelector("#config-form");
const configError = document.querySelector("#config-error");
const configSuccess = document.querySelector("#config-success");
const popularSearches = document.querySelector("#popular-searches");
const popularError = document.querySelector("#popular-error");

let currentTaskId = null;
let eventSource = null;
let activeTab = "gallery";
let startingSearch = false;
let galleryItems = [];
let activeGalleryIndex = -1;

function setStatus(state, label) {
  statusPill.className = `status-pill status-${state}`;
  statusLabel.textContent = label;
}

function setBusy(busy) {
  startButton.disabled = busy;
  tagsInput.disabled = busy;
  cancelButton.hidden = !busy;
  popularSearches.querySelectorAll("button").forEach((button) => {
    button.disabled = busy;
  });
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
    refreshGallery();
    refreshPopularSearches();
    stopWatching();
  } else if (item.type === "cancelled") {
    setStatus("idle", "Cancelled");
    progressLabel.textContent = "Download cancelled";
    refreshPopularSearches();
    stopWatching();
  } else if (item.type === "error") {
    setStatus("error", "Failed");
    progressLabel.textContent = "Download stopped with an error";
    addLog(item.error || "The download could not be completed.", "log-error");
    refreshPopularSearches();
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
  await startSearch(tagsInput.value);
});

async function startSearch(searchTags) {
  if (currentTaskId || startingSearch) return;
  formError.hidden = true;
  const tags = searchTags.trim();
  if (!tags) {
    formError.textContent = "Enter at least one search tag.";
    formError.hidden = false;
    tagsInput.focus();
    return;
  }

  startingSearch = true;
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
    startingSearch = false;
    addLog(`Searching for: ${payload.tags}`);
    watchTask(payload.id);
  } catch (error) {
    startingSearch = false;
    formError.textContent = error.message;
    formError.hidden = false;
    setStatus("error", "Could not start");
    setBusy(false);
  }
}

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

function selectTab(name) {
  activeTab = name;
  const gallerySelected = name === "gallery";
  galleryTab.classList.toggle("active", gallerySelected);
  rule34Tab.classList.toggle("active", !gallerySelected);
  galleryTab.setAttribute("aria-selected", String(gallerySelected));
  rule34Tab.setAttribute("aria-selected", String(!gallerySelected));
  galleryTab.tabIndex = gallerySelected ? 0 : -1;
  rule34Tab.tabIndex = gallerySelected ? -1 : 0;
  galleryPanel.hidden = !gallerySelected;
  rule34Panel.hidden = gallerySelected;
  if (gallerySelected) refreshGallery();
  else refreshPopularSearches();
}

galleryTab.addEventListener("click", () => selectTab("gallery"));
rule34Tab.addEventListener("click", () => selectTab("rule34"));

for (const tab of [galleryTab, rule34Tab]) {
  tab.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const next = tab === galleryTab ? rule34Tab : galleryTab;
    selectTab(next === galleryTab ? "gallery" : "rule34");
    next.focus();
  });
}

document.querySelector("#refresh-gallery-button").addEventListener("click", refreshGallery);

async function refreshPopularSearches() {
  popularError.hidden = true;
  try {
    const response = await fetch("/api/searches/top", { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Could not load search history.");
    popularSearches.replaceChildren();
    if (payload.searches.length === 0) {
      const empty = document.createElement("p");
      empty.className = "popular-placeholder";
      empty.textContent = "Searches you run will appear here.";
      popularSearches.append(empty);
      return;
    }
    payload.searches.forEach((search, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "popular-search-button";
      const rank = document.createElement("span");
      rank.className = "popular-rank";
      rank.textContent = String(index + 1).padStart(2, "0");
      const tags = document.createElement("span");
      tags.className = "popular-tags";
      tags.textContent = search.tags;
      const calls = document.createElement("span");
      calls.className = "popular-calls";
      calls.textContent = `${search.calls}×`;
      button.append(rank, tags, calls);
      button.addEventListener("click", () => {
        if (currentTaskId || startingSearch) return;
        selectTab("rule34");
        tagsInput.value = search.tags;
        startSearch(search.tags);
      });
      popularSearches.append(button);
    });
  } catch (error) {
    popularSearches.replaceChildren();
    popularError.textContent = error.message;
    popularError.hidden = false;
  }
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let size = bytes / 1024;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(size >= 10 ? 0 : 1)} ${units[unit]}`;
}

function createGalleryThumbnail(item) {
  const image = document.createElement("img");
  image.src = item.thumbnail_url;
  image.alt = "";
  image.loading = "lazy";
  image.decoding = "async";
  image.addEventListener("error", async () => {
    let message = "Preview unavailable.";
    try {
      const response = await fetch(item.thumbnail_url, { cache: "no-store" });
      const payload = await response.json();
      if (typeof payload.error === "string") message = payload.error;
    } catch (error) {
      if (error instanceof Error) message = `Preview unavailable: ${error.message}`;
    }
    const unavailable = document.createElement("span");
    unavailable.className = "gallery-thumbnail-error";
    unavailable.textContent = message;
    unavailable.title = message;
    image.replaceWith(unavailable);
  }, { once: true });
  return image;
}

function renderGallery(items) {
  const activeName = galleryDialog.open
    ? galleryItems[activeGalleryIndex]?.name
    : null;
  galleryItems = items;
  galleryGrid.replaceChildren();
  galleryCount.textContent = String(items.length);
  if (items.length === 0) {
    const empty = document.createElement("div");
    empty.className = "gallery-empty card";
    empty.innerHTML = '<span class="gallery-empty-mark" aria-hidden="true">▧</span><h2>Your gallery is empty</h2><p>Downloaded images and videos will show up here.</p><button class="button button-primary" type="button">Browse Rule34</button>';
    empty.querySelector("button").addEventListener("click", () => {
      selectTab("rule34");
      rule34Tab.focus();
    });
    galleryGrid.append(empty);
    if (galleryDialog.open) {
      galleryDialog.close();
      activeGalleryIndex = -1;
    }
    return;
  }

  for (const item of items) {
    const card = document.createElement("button");
    card.className = "gallery-card";
    card.type = "button";
    card.setAttribute("aria-label", `Open ${item.name}`);
    card.addEventListener("click", () => openGalleryItem(items.indexOf(item)));
    const preview = document.createElement("span");
    preview.className = "gallery-preview";
    preview.append(createGalleryThumbnail(item));
    card.append(preview);
    galleryGrid.append(card);
  }

  if (galleryDialog.open) {
    const updatedIndex = galleryItems.findIndex((item) => item.name === activeName);
    if (updatedIndex < 0) {
      galleryDialog.close();
    } else {
      activeGalleryIndex = updatedIndex;
      renderGalleryViewer();
    }
  }
}

function addGalleryDetail(label, value) {
  const row = document.createElement("div");
  row.className = "gallery-detail-row";
  const term = document.createElement("dt");
  term.textContent = label;
  const description = document.createElement("dd");
  description.textContent = value;
  row.append(term, description);
  galleryFileDetails.append(row);
}

function formatIsoDate(value) {
  if (typeof value !== "string") return "Unknown";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Unknown" : date.toISOString();
}

function renderGalleryTags(tags) {
  galleryTags.replaceChildren();
  tags.forEach((tag, index) => {
    const chip = document.createElement("span");
    chip.className = "gallery-tag-chip";
    const text = document.createElement("span");
    text.textContent = tag;
    const remove = document.createElement("button");
    remove.className = "gallery-tag-remove";
    remove.type = "button";
    remove.setAttribute("aria-label", `Remove tag ${tag}`);
    remove.textContent = "×";
    remove.addEventListener("click", () => {
      const item = galleryItems[activeGalleryIndex];
      const currentTags = Array.isArray(item?.metadata?.tags)
        ? [...item.metadata.tags]
        : [];
      currentTags.splice(index, 1);
      item.metadata = { ...(item.metadata || {}), tags: currentTags };
      renderGalleryTags(currentTags);
      galleryMetadataStatus.textContent = "Tag removed. Save details to keep the change.";
    });
    chip.append(text, remove);
    galleryTags.append(chip);
  });
}

function addGalleryTag(value) {
  const tag = value.trim();
  if (!tag) return;
  const item = galleryItems[activeGalleryIndex];
  if (!item) return;
  const currentTags = Array.isArray(item.metadata?.tags)
    ? [...item.metadata.tags]
    : [];
  if (currentTags.some((existing) => existing.toLowerCase() === tag.toLowerCase())) {
    galleryMetadataStatus.textContent = "That tag is already listed.";
    return;
  }
  currentTags.push(tag);
  item.metadata = { ...(item.metadata || {}), tags: currentTags };
  renderGalleryTags(currentTags);
  galleryMetadataStatus.textContent = "Tag added. Save details to keep the change.";
}

function renderGalleryViewer() {
  const item = galleryItems[activeGalleryIndex];
  if (!item) return;

  galleryViewerError.hidden = true;
  galleryMetadataStatus.textContent = "";
  galleryViewerTitle.textContent = item.name;
  galleryViewerMedia.replaceChildren();
  galleryFileDetails.replaceChildren();

  if (item.kind === "video") {
    const video = document.createElement("video");
    video.src = item.url;
    video.controls = true;
    video.playsInline = true;
    video.preload = "metadata";
    galleryViewerMedia.append(video);
  } else {
    const image = document.createElement("img");
    image.src = item.url;
    image.alt = item.name;
    galleryViewerMedia.append(image);
  }

  addGalleryDetail("File name", item.name);
  addGalleryDetail("Size", formatBytes(item.size));
  addGalleryDetail("File modified date (ISO 8601 UTC)", new Date(item.modified * 1000).toISOString());
  const metadata = item.metadata || {};
  addGalleryDetail("Download date/time (ISO 8601 UTC)", formatIsoDate(metadata.downloaded_at));
  if (item.metadata && Object.keys(item.metadata).length > 0) {
    for (const [key, value] of Object.entries(item.metadata)) {
      if (["title", "description", "downloaded_at"].includes(key)) continue;
      if (key === "tags") continue;
      const formattedValue =
        typeof value === "string" ? value : JSON.stringify(value, null, 2);
      addGalleryDetail(key, formattedValue);
    }
  } else {
    addGalleryDetail(
      "Additional information",
      item.metadata_error || "No additional metadata.",
    );
  }
  galleryTitleInput.value =
    typeof metadata.title === "string" ? metadata.title : "";
  galleryDescriptionInput.value =
    typeof metadata.description === "string" ? metadata.description : "";
  renderGalleryTags(Array.isArray(metadata.tags) ? metadata.tags : []);

  galleryCarousel.replaceChildren();
  galleryItems.forEach((carouselItem, index) => {
    const button = document.createElement("button");
    button.className = "gallery-carousel-item";
    button.type = "button";
    button.setAttribute("aria-label", `Open ${carouselItem.name}`);
    button.setAttribute("aria-current", String(index === activeGalleryIndex));
    if (index === activeGalleryIndex) button.classList.add("active");
    button.addEventListener("click", () => {
      activeGalleryIndex = index;
      renderGalleryViewer();
    });
    button.append(createGalleryThumbnail(carouselItem));
    galleryCarousel.append(button);
  });

  const activeThumbnail = galleryCarousel.querySelector(".active");
  activeThumbnail?.scrollIntoView({ block: "nearest", inline: "center" });
  document.querySelector("#gallery-previous").disabled =
    galleryItems.length < 2;
  document.querySelector("#gallery-next").disabled = galleryItems.length < 2;
}

function openGalleryItem(index) {
  if (index < 0 || index >= galleryItems.length) return;
  activeGalleryIndex = index;
  renderGalleryViewer();
  if (!galleryDialog.open) galleryDialog.showModal();
}

function moveGalleryViewer(direction) {
  if (galleryItems.length < 2) return;
  activeGalleryIndex =
    (activeGalleryIndex + direction + galleryItems.length) % galleryItems.length;
  renderGalleryViewer();
}

async function refreshGallery() {
  galleryError.hidden = true;
  try {
    const response = await fetch("/api/gallery", { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Could not load the gallery.");
    renderGallery(payload.items);
  } catch (error) {
    galleryError.textContent = error.message;
    galleryError.hidden = false;
  }
}

document.querySelector("#close-gallery-viewer").addEventListener("click", () => {
  galleryDialog.close();
});
galleryDialog.addEventListener("close", () => {
  galleryViewerMedia.replaceChildren();
});
galleryDialog.addEventListener("click", (event) => {
  if (event.target === galleryDialog) galleryDialog.close();
});
document.querySelector("#gallery-previous").addEventListener("click", () => {
  moveGalleryViewer(-1);
});
document.querySelector("#gallery-next").addEventListener("click", () => {
  moveGalleryViewer(1);
});
galleryMetadataForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const item = galleryItems[activeGalleryIndex];
  if (!item) return;

  const saveButton = document.querySelector("#save-gallery-metadata");
  galleryViewerError.hidden = true;
  saveButton.disabled = true;
  try {
    const response = await fetch(item.url, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: galleryTitleInput.value,
        description: galleryDescriptionInput.value,
        tags: Array.isArray(item.metadata?.tags) ? item.metadata.tags : [],
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Could not save these details.");
    }
    item.metadata = payload.metadata;
    item.metadata_error = "";
    renderGalleryViewer();
    galleryMetadataStatus.textContent = "Details saved.";
  } catch (error) {
    galleryViewerError.textContent = error.message;
    galleryViewerError.hidden = false;
  } finally {
    saveButton.disabled = false;
  }
});
galleryTagInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    addGalleryTag(galleryTagInput.value);
    galleryTagInput.value = "";
  } else if (
    event.key === "Backspace" &&
    galleryTagInput.value === "" &&
    galleryTags.lastElementChild
  ) {
    galleryTags.lastElementChild.querySelector("button").click();
  }
});
galleryDialog.addEventListener("keydown", (event) => {
  if (event.key === "ArrowLeft") {
    event.preventDefault();
    moveGalleryViewer(-1);
  } else if (event.key === "ArrowRight") {
    event.preventDefault();
    moveGalleryViewer(1);
  }
});
deleteGalleryItemButton.addEventListener("click", async () => {
  const item = galleryItems[activeGalleryIndex];
  if (!item) return;
  if (!window.confirm(`Delete ${item.name} and its metadata file?`)) return;

  galleryViewerError.hidden = true;
  deleteGalleryItemButton.disabled = true;
  try {
    const response = await fetch(item.url, { method: "DELETE" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Could not delete this file.");
    galleryDialog.close();
    await refreshGallery();
  } catch (error) {
    galleryViewerError.textContent = error.message;
    galleryViewerError.hidden = false;
  } finally {
    deleteGalleryItemButton.disabled = false;
  }
});

function openConfig() {
  configError.hidden = true;
  configSuccess.hidden = true;
  document.querySelector("#config-api-key").value = "";
  document.querySelector("#config-user-id").value = "";
  configButton.disabled = true;
  fetch("/api/config", { cache: "no-store" })
    .then(async (response) => {
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Could not load settings.");
      configForm.elements.downloads_dir.value = payload.downloads_dir;
      configForm.elements.rule34_requests_per_second.value =
        payload.rule34_requests_per_second;
      document.querySelector("#credential-status").textContent =
        payload.credentials_configured
          ? "Credentials are saved. Leave both fields blank to keep them."
          : "Credentials are not configured. Enter both values to enable Rule34 downloads.";
      configDialog.showModal();
    })
    .catch((error) => {
      configError.textContent = error.message;
      configError.hidden = false;
      configDialog.showModal();
    })
    .finally(() => {
      configButton.disabled = false;
    });
}

configButton.addEventListener("click", openConfig);
document.querySelector("#close-config").addEventListener("click", () => configDialog.close());
document.querySelector("#cancel-config").addEventListener("click", () => configDialog.close());
configDialog.addEventListener("click", (event) => {
  if (event.target === configDialog) configDialog.close();
});

configForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  configError.hidden = true;
  configSuccess.hidden = true;
  const saveButton = document.querySelector("#save-config");
  saveButton.disabled = true;
  try {
    const response = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        downloads_dir: configForm.elements.downloads_dir.value.trim(),
        rule34_requests_per_second: Number(
          configForm.elements.rule34_requests_per_second.value,
        ),
        api_key: configForm.elements.api_key.value,
        user_id: configForm.elements.user_id.value,
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Could not save settings.");
    configForm.elements.api_key.value = "";
    configForm.elements.user_id.value = "";
    configSuccess.hidden = false;
    document.querySelector("#credential-status").textContent =
      payload.credentials_configured
        ? "Credentials are saved. Leave both fields blank to keep them."
        : "Credentials are not configured. Enter both values to enable Rule34 downloads.";
    await refreshGallery();
  } catch (error) {
    configError.textContent = error.message;
    configError.hidden = false;
  } finally {
    saveButton.disabled = false;
  }
});

selectTab(activeTab);
