"""Hardening middleware (api-rules.md "Hardening"): request IDs, CORS, security headers,
body size limits.
"""

import secure
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings
from app.core.errors import ErrorCode, error_body

REQUEST_ID_HEADER = "X-Request-ID"
# multipart photo upload (FR-N1), the only route with the larger limit
UPLOAD_PATHS = frozenset({"/api/v1/meals/recognitions"})


class BodySizeLimitMiddleware:
    """413 `payload_too_large` above the limit, by Content-Length or by the bytes read."""

    def __init__(self, app: ASGIApp, max_bytes: int, upload_max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.upload_max_bytes = upload_max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.upload_max_bytes if scope["path"] in UPLOAD_PATHS else self.max_bytes

        length = Headers(scope=scope).get("content-length")
        if length is not None and length.isdigit() and int(length) > limit:
            response = JSONResponse(
                status_code=413,
                content=error_body(ErrorCode.PAYLOAD_TOO_LARGE, "Request body too large"),
            )
            await response(scope, receive, send)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # handled by the error handlers like any other 413
                    raise StarletteHTTPException(413, "Request body too large")
            return message

        await self.app(scope, limited_receive, send)


class SecurityHeadersMiddleware:
    """Default headers of the `secure` package; the Swagger UI page keeps its own CSP."""

    def __init__(self, app: ASGIApp, docs_path: str) -> None:
        self.app = app
        self.docs_path = docs_path
        # Server is uvicorn's own header; it is switched off with --no-server-header
        self.headers = {
            name: value
            for name, value in secure.Secure.with_default_headers().headers.items()
            if name != "Server"
        }

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_docs = scope["path"] == self.docs_path

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in self.headers.items():
                    if is_docs and name == "Content-Security-Policy":
                        continue  # Swagger UI loads its script and styles from a CDN
                    headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)


def add_middleware(app: FastAPI, settings: Settings, docs_path: str) -> None:
    # The last one added runs first: request ID, CORS, security headers, body limit.
    app.add_middleware(
        BodySizeLimitMiddleware,
        max_bytes=settings.max_body_bytes,
        upload_max_bytes=settings.max_upload_body_bytes,
    )
    app.add_middleware(SecurityHeadersMiddleware, docs_path=docs_path)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER, "Retry-After"],
    )
    app.add_middleware(CorrelationIdMiddleware, header_name=REQUEST_ID_HEADER)
