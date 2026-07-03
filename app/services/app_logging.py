from __future__ import annotations

import getpass
import logging
import platform
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.services.app_paths import get_logs_dir
from app.version import APP_VERSION


LOGGER_NAME = "controle_producao"


def configure_logging() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger
    log_dir = get_logs_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / "controle_producao.log",
        maxBytes=2 * 1024 * 1024,
        backupCount=10,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.info(
        "Aplicacao iniciada | versao=%s | computador=%s | usuario_windows=%s",
        APP_VERSION,
        platform.node(),
        getpass.getuser(),
    )
    return logger


def get_logger(component: str | None = None) -> logging.Logger:
    configure_logging()
    return logging.getLogger(f"{LOGGER_NAME}.{component}" if component else LOGGER_NAME)


def current_log_file() -> Path:
    return get_logs_dir() / "controle_producao.log"
