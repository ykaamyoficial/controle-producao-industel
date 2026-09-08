"""Confirmacao pos-update (Fase 10, Secao 24): handshake local minimo entre o
Desktop recem-reaberto e o Updater, sem qualquer dependencia de rede."""

from __future__ import annotations

import time
from pathlib import Path

from app.updater.paths import updater_root_dir


def handshake_dir() -> Path:
    return updater_root_dir() / "handshake"


def handshake_marker_path(request_id: str) -> Path:
    return handshake_dir() / f"{request_id}.ok"


def write_handshake_marker(request_id: str) -> None:
    path = handshake_marker_path(request_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("ok", encoding="utf-8")


def wait_for_handshake(request_id: str, *, timeout_seconds: float = 30.0, poll_interval_seconds: float = 0.5) -> bool:
    path = handshake_marker_path(request_id)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(poll_interval_seconds)
    return path.exists()


def clear_handshake_marker(request_id: str) -> None:
    handshake_marker_path(request_id).unlink(missing_ok=True)
