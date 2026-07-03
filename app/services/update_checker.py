from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError

from app.services.app_logging import get_logger
from app.services.network_diagnostics import classify_network_error, fetch_json, friendly_network_message
from app.version import APP_VERSION


RELEASES_API_URL = "https://api.github.com/repos/ykaamyoficial/controle-producao-industel-releases/releases/latest"
log = get_logger("updates.checker")


class UpdateCheckError(RuntimeError):
    pass


@dataclass(frozen=True)
class VersionInfo:
    parts: tuple[int, ...]
    suffix: str = ""


def parse_version(value: str) -> VersionInfo:
    clean = (value or "").strip()
    clean = clean[1:] if clean.lower().startswith("v") else clean
    match = re.match(r"^(\d+(?:\.\d+)*)(.*)$", clean)
    if not match:
        return VersionInfo((0,), clean)
    parts = tuple(int(piece) for piece in match.group(1).split("."))
    return VersionInfo(parts, match.group(2).strip())


def is_newer_version(latest: str, current: str) -> bool:
    latest_info = parse_version(latest)
    current_info = parse_version(current)
    max_len = max(len(latest_info.parts), len(current_info.parts))
    latest_parts = latest_info.parts + (0,) * (max_len - len(latest_info.parts))
    current_parts = current_info.parts + (0,) * (max_len - len(current_info.parts))
    return latest_parts > current_parts


def _default_fetch_json(url: str, timeout: int = 10) -> dict[str, Any]:
    return fetch_json(url, timeout)


def parse_github_release(payload: dict[str, Any], current_version: str = APP_VERSION) -> dict[str, Any]:
    tag_name = str(payload.get("tag_name") or "")
    latest_version = tag_name[1:] if tag_name.lower().startswith("v") else tag_name
    assets = []
    for asset in payload.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        assets.append(
            {
                "name": asset.get("name"),
                "browser_download_url": asset.get("browser_download_url"),
                "size": asset.get("size"),
                "content_type": asset.get("content_type"),
            }
        )

    return {
        "update_available": is_newer_version(latest_version, current_version),
        "current_version": current_version,
        "latest_version": latest_version,
        "tag_name": tag_name,
        "published_at": payload.get("published_at"),
        "release_notes": payload.get("body") or "",
        "assets": assets,
    }


def check_for_updates(
    *,
    current_version: str = APP_VERSION,
    url: str = RELEASES_API_URL,
    fetch_json: Callable[[str, int], dict[str, Any]] | None = None,
    timeout: int = 10,
) -> dict[str, Any]:
    fetch = fetch_json or _default_fetch_json
    try:
        payload = fetch(url, timeout)
        return parse_github_release(payload, current_version=current_version)
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError, UpdateCheckError) as exc:
        kind = classify_network_error(exc)
        log.exception("Verificacao de atualizacao falhou | tipo=%s | url=%s", kind, url)
        return {
            "update_available": False,
            "current_version": current_version,
            "latest_version": current_version,
            "published_at": None,
            "release_notes": "",
            "assets": [],
            "error": str(exc),
            "error_kind": kind,
            "user_message": friendly_network_message(kind),
        }
