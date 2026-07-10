from __future__ import annotations

import json
from pathlib import Path

from app.services.app_paths import get_app_data_dir


PREFERENCES_FILE_NAME = "login_preferences.json"


def get_login_preferences_path() -> Path:
    return get_app_data_dir() / PREFERENCES_FILE_NAME


def load_login_preferences() -> dict[str, object]:
    path = get_login_preferences_path()
    if not path.exists():
        return {"remember_user": False, "last_user": ""}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"remember_user": False, "last_user": ""}
    remember = bool(data.get("remember_user"))
    last_user = str(data.get("last_user") or "").strip() if remember else ""
    return {"remember_user": remember and bool(last_user), "last_user": last_user}


def save_login_preferences(login: str, remember_user: bool) -> None:
    path = get_login_preferences_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not remember_user:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    safe_login = str(login or "").strip()
    payload = {"remember_user": bool(safe_login), "last_user": safe_login}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
