"""Load application settings from the project's JSON configuration."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "app" / "config.json"


@dataclass(frozen=True)
class AppConfig:
    """Resolved paths used by the downloader."""

    downloads_dir: Path
    history_file: Path
    keys_file: Path
    rate_limits: dict[str, float]


@dataclass(frozen=True)
class Rule34Credentials:
    """Credentials used for authenticated Rule34 API requests."""

    api_key: str
    user_id: str


def _resolve_project_path(value: Any, field_name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Configuration field '{field_name}' must be a path.")
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _parse_rate_limits(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        raise ValueError("Configuration field 'rate_limits' must be an object.")

    rate_limits: dict[str, float] = {}
    for site, settings in value.items():
        if not isinstance(site, str) or not site.strip():
            raise ValueError("Rate-limit site names must be non-empty strings.")
        if not isinstance(settings, dict):
            raise ValueError(f"Rate limit for '{site}' must be an object.")
        requests_per_second = settings.get("requests_per_second")
        if (
            isinstance(requests_per_second, bool)
            or not isinstance(requests_per_second, (int, float))
            or requests_per_second <= 0
        ):
            raise ValueError(
                f"Rate limit for '{site}' must have a positive "
                "'requests_per_second' value."
            )
        rate_limits[site] = float(requests_per_second)
    return rate_limits


def load_config(config_path: Path = CONFIG_PATH) -> AppConfig:
    """Load and validate configuration, resolving relative paths from the root."""
    with config_path.open(encoding="utf-8") as config_file:
        data = json.load(config_file)
    if not isinstance(data, dict):
        raise ValueError("Configuration must be a JSON object.")
    return AppConfig(
        downloads_dir=_resolve_project_path(data.get("downloads_dir"), "downloads_dir"),
        history_file=_resolve_project_path(data.get("history_file"), "history_file"),
        keys_file=_resolve_project_path(data.get("keys_file"), "keys_file"),
        rate_limits=_parse_rate_limits(data.get("rate_limits")),
    )


def load_rule34_credentials(keys_file: Path) -> Rule34Credentials:
    """Load Rule34 credentials without including their values in error messages."""
    with keys_file.open(encoding="utf-8") as credential_file:
        data = json.load(credential_file)
    try:
        credentials = data["services"]["rule34"]
        api_key = credentials["api_key"]
        user_id = credentials["user_id"]
    except (KeyError, TypeError) as exc:
        raise ValueError(
            "Add services.rule34.api_key and services.rule34.user_id "
            "to the configured keys JSON file."
        ) from exc

    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("services.rule34.api_key must be a non-empty string.")
    if not isinstance(user_id, (str, int)) or not str(user_id).strip():
        raise ValueError("services.rule34.user_id must be a non-empty string or integer.")

    return Rule34Credentials(
        api_key=api_key.strip(),
        user_id=str(user_id).strip(),
    )
