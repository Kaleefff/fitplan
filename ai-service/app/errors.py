"""Error bodies in the backend's model {code, message, details[]} (backend/app/core/errors.py).

ai-service is internal: B-19 maps these onto the contract. `ai_unavailable` (502 for a
Gemini error or invalid answer, 504 for a timeout) is the code the app already handles
and the contract's ServiceUnavailable; `invalid_image` and `not_configured` exist only
here (B-19: 422 validation_error and 503 ai_unavailable).
"""

import logging
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class ErrorCode(StrEnum):
    INVALID_IMAGE = "invalid_image"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    VALIDATION_ERROR = "validation_error"
    AI_UNAVAILABLE = "ai_unavailable"
    NOT_CONFIGURED = "not_configured"
    NOT_FOUND = "not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    INTERNAL_ERROR = "internal_error"


class AppError(Exception):
    def __init__(
        self,
        status_code: int,
        code: ErrorCode,
        message: str,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []


def error_body(
    code: ErrorCode, message: str, details: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {"code": code.value, "message": message, "details": details or []}


def error_response(
    status_code: int, code: ErrorCode, message: str, details: list[dict[str, Any]] | None = None
) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=error_body(code, message, details))


def field_path(loc: tuple[Any, ...]) -> str:
    return ".".join(str(part) for part in loc)


async def _app_error(_: Request, exc: AppError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.message, exc.details)


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        {"field": field_path(err["loc"]), "code": err["type"], "message": err["msg"]}
        for err in exc.errors()
    ]
    return error_response(422, ErrorCode.VALIDATION_ERROR, "Request validation failed", details)


async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    if exc.status_code == 404:
        return error_response(404, ErrorCode.NOT_FOUND, "Not found")
    if exc.status_code == 405:
        return error_response(405, ErrorCode.METHOD_NOT_ALLOWED, "Method not allowed")
    if exc.status_code == 413:
        return error_response(413, ErrorCode.PAYLOAD_TOO_LARGE, "Request too large")
    if exc.status_code == 400:
        # a malformed multipart body; the parser's text is not echoed
        return error_response(422, ErrorCode.VALIDATION_ERROR, "Malformed request body")
    return error_response(500, ErrorCode.INTERNAL_ERROR, "Internal error")


async def _unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    logger.error("unexpected error: %s", type(exc).__name__)
    return error_response(500, ErrorCode.INTERNAL_ERROR, "Internal error")


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _http_error)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unexpected_error)
