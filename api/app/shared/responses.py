from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from api.app.shared.request_context import request_id_var


def current_request_id(request: Request | None = None) -> str:
    if request is not None:
        value = getattr(request.state, "request_id", None)
        if value:
            return value
    return request_id_var.get() or ""


def error_response(code: str, message: str, request: Request, status_code: int, *, details: object | None = None) -> JSONResponse:
    request_id = current_request_id(request)
    error = {
        "code": code,
        "message": message,
        "request_id": request_id,
    }
    if details is not None:
        error["details"] = details
    response = JSONResponse(
        status_code=status_code,
        content={"error": error},
    )
    if request_id:
        response.headers["X-Request-ID"] = request_id
    return response
