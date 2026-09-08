from __future__ import annotations

import logging
import sys
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from api.app.core.config import Settings
from api.app.shared.request_context import request_id_var


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


def configure_logging(settings: Settings) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(settings.api_log_level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(settings.api_log_level)
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s request_id=%(request_id)s logger=%(name)s %(message)s"
        )
    )
    root.addHandler(handler)

    logging.getLogger("uvicorn.access").disabled = True


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = int((time.perf_counter() - started) * 1000)
        logging.getLogger("api.access").info(
            "http_request method=%s path=%s status=%s duration_ms=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response
