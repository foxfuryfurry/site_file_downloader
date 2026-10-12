"""Persistent per-site search statistics and downloaded IDs."""

import json
from pathlib import Path
from typing import Any


History = dict[str, dict[str, Any]]


def _write_history(history_file: Path, history: History) -> None:
    history_file.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = history_file.with_suffix(history_file.suffix + ".tmp")
    with temporary_file.open("w", encoding="utf-8") as file:
        json.dump(history, file, indent=4)
        file.write("\n")
    temporary_file.replace(history_file)


def _empty_site_history() -> dict[str, Any]:
    return {"searches": [], "downloads": []}


def _read_history(history_file: Path) -> History:
    if not history_file.exists():
        return {}
    with history_file.open(encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid download history format: {history_file}")

    if "downloads" in data and isinstance(data["downloads"], list):
        records = data["downloads"]
        if not all(isinstance(record, dict) for record in records):
            raise ValueError(f"Invalid legacy download history format: {history_file}")
        ids = list(
            dict.fromkeys(str(record["id"]) for record in records if "id" in record)
        )
        history = {"rule34": _empty_site_history()}
        history["rule34"]["downloads"] = ids
        _write_history(history_file, history)
        return history

    history: History = {}
    for site, site_data in data.items():
        if not isinstance(site, str) or not site.strip():
            raise ValueError(f"Invalid download history site in: {history_file}")

        if isinstance(site_data, list):
            site_history = _empty_site_history()
            site_history["downloads"] = list(
                dict.fromkeys(str(post_id) for post_id in site_data)
            )
        elif isinstance(site_data, dict):
            searches = site_data.get("searches", [])
            downloads = site_data.get("downloads", [])
            if not isinstance(searches, list) or not isinstance(downloads, list):
                raise ValueError(f"Invalid download history entry in: {history_file}")
            if not all(
                isinstance(search, dict)
                and isinstance(search.get("tags"), str)
                and isinstance(search.get("calls"), int)
                and not isinstance(search.get("calls"), bool)
                and search["calls"] > 0
                for search in searches
            ):
                raise ValueError(f"Invalid search history entry in: {history_file}")
            if not all(isinstance(post_id, (str, int)) for post_id in downloads):
                raise ValueError(f"Invalid download history entry in: {history_file}")
            site_history = {
                "searches": searches,
                "downloads": list(dict.fromkeys(str(post_id) for post_id in downloads)),
            }
        else:
            raise ValueError(f"Invalid download history entry in: {history_file}")

        history[site] = site_history

    return history


def downloaded_ids(history_file: Path, site: str) -> set[str]:
    """Return IDs already recorded for a site."""
    if not site.strip():
        raise ValueError("History site name must not be empty.")
    site_history = _read_history(history_file).get(site)
    if site_history is None:
        return set()
    return set(site_history["downloads"])


def record_search(history_file: Path, site: str, tags: str) -> None:
    """Count searches with the same normalized, space-separated tags."""
    if not site.strip():
        raise ValueError("History site name must not be empty.")
    normalized_tags = " ".join(tags.split())
    if not normalized_tags:
        raise ValueError("Search tags must not be empty.")

    history = _read_history(history_file)
    site_history = history.setdefault(site, _empty_site_history())
    search_key = normalized_tags.casefold()
    for search in site_history["searches"]:
        if " ".join(search["tags"].split()).casefold() == search_key:
            search["calls"] += 1
            break
    else:
        site_history["searches"].append({"tags": normalized_tags, "calls": 1})
    _write_history(history_file, history)


def record_download(history_file: Path, site: str, post_id: str) -> None:
    """Record a completed download using an atomic JSON file replacement."""
    if not site.strip():
        raise ValueError("History site name must not be empty.")
    if not post_id.strip():
        raise ValueError("Download ID must not be empty.")

    history = _read_history(history_file)
    site_history = history.setdefault(site, _empty_site_history())
    if post_id not in site_history["downloads"]:
        site_history["downloads"].append(post_id)
    _write_history(history_file, history)
