"""Common error model of the API contract: {code, message, details[]}."""

import logging
from enum import StrEnum
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from pydantic.json_schema import SkipJsonSchema
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "validation_error"
    UNAUTHORIZED = "unauthorized"
    INVALID_CREDENTIALS = "invalid_credentials"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    CONFLICT = "conflict"
    RATE_LIMITED = "rate_limited"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    INSUFFICIENT_EXERCISES = "insufficient_exercises"
    INSUFFICIENT_FOODS = "insufficient_foods"
    INVALID_SWAP = "invalid_swap"
    AI_UNAVAILABLE = "ai_unavailable"
    INTERNAL_ERROR = "internal_error"


_CODE_BY_STATUS = {
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    409: ErrorCode.CONFLICT,
    413: ErrorCode.PAYLOAD_TOO_LARGE,
    422: ErrorCode.VALIDATION_ERROR,
    429: ErrorCode.RATE_LIMITED,
}


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="allow")

    field: str | SkipJsonSchema[None] = None
    code: str
    message: str


class Error(BaseModel):
    """Contract `Error` schema; documents error responses in the generated OpenAPI."""

    code: ErrorCode
    message: str
    details: list[ErrorDetail]


# Routes with parameters or a body pass this as `responses=`, otherwise FastAPI
# documents its own HTTPValidationError instead of the contract model.
VALIDATION_ERROR_RESPONSE: dict[int | str, dict[str, Any]] = {
    422: {"model": Error, "description": "Invalid input"},
}


class AppError(Exception):
    """Raised by services; turned into the contract error body."""

    def __init__(
        self,
        status_code: int,
        code: ErrorCode,
        message: str,
        details: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []
        self.headers = headers


def error_body(code: ErrorCode, message: str, details: list[dict[str, Any]] | None = None) -> dict:
    return {"code": code.value, "message": message, "details": details or []}


def _field_path(loc: tuple[Any, ...]) -> str:
    return ".".join(str(part) for part in loc)


async def _app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(exc.code, exc.message, exc.details),
        headers=exc.headers,
    )


async def _validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        {"field": _field_path(err["loc"]), "code": err["type"], "message": err["msg"]}
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=error_body(ErrorCode.VALIDATION_ERROR, "Request validation failed", details),
    )


async def _http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _CODE_BY_STATUS.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
    message = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(code, message),
        headers=getattr(exc, "headers", None),
    )


async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content=error_body(ErrorCode.INTERNAL_ERROR, "Internal server error"),
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)
