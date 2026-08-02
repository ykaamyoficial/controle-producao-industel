from __future__ import annotations

import contextvars
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


REQUEST_ID_HEADER = "X-Request-ID"
request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)


def valid_request_id(value: str) -> bool:
    if not value or len(value) > 80:
        return False
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
    return all(char in allowed for char in value)


def request_id_from_request(request: Request) -> str:
    value = request.headers.get(REQUEST_ID_HEADER, "").strip()
    if valid_request_id(value):
        return value
    return str(uuid.uuid4())


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request_id_from_request(request)
        token = request_id_var.set(request_id)
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
