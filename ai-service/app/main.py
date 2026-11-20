"""ai-service HTTP API (A-01): POST /predict and GET /health.

POST /predict (multipart): `photo` (JPEG, PNG or WebP by content, at most 8 MiB) and
`labels` (a JSON array of the active recognition labels, sent by the backend with every
call). Answers the Prediction of app/schemas.py, or an error in the backend model:

    400 invalid_image      not a readable JPEG, PNG or WebP
    413 payload_too_large  photo over 8 MiB (the app's limit)
    422 validation_error   missing or invalid field
    502 ai_unavailable     Gemini error or invalid answer
    504 ai_unavailable     Gemini timeout
    503 not_configured     GEMINI_API_KEY or GEMINI_MODEL missing

GET /health: 200 {status, model} when configured, 503 otherwise; never calls Gemini.
Run: uvicorn app.main:create_app --factory --port 8001 (settings from the environment)
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import AfterValidator, StringConstraints, TypeAdapter, ValidationError
from starlette.concurrency import run_in_threadpool

from app.config import MAX_PHOTO_BYTES, Settings, get_settings
from app.errors import AppError, ErrorCode, error_response, field_path, install_error_handlers
from app.gemini import GeminiProvider
from app.image import InvalidImageError, prepare_photo
from app.provider import ProviderError, ProviderTimeoutError, RecognitionProvider
from app.schemas import Prediction

logger = logging.getLogger(__name__)

MAX_LABEL_CHARS = 100  # food_item.recognition_label is VARCHAR(100)
MAX_LABELS = 2000
# whole request: the photo plus the labels field (Starlette caps text fields at 1 MiB)
# plus multipart overhead; a larger Content-Length is refused before it is read
MAX_REQUEST_BYTES = MAX_PHOTO_BYTES + 2 * 1024 * 1024
# photos decoded at a time; a large PNG needs a few hundred MB of the 512 MB limit
PREPARE_CONCURRENCY = 1
# the SDK and its HTTP client log every call at INFO ("AFC is enabled", the request
# line); app.gemini already logs one line per call, so these log warnings only
QUIET_LOGGERS = ("google_genai", "httpx2")


def _not_blank(label: str) -> str:
    if not label.strip():
        raise ValueError("label is blank")
    return label


Label = Annotated[
    str, StringConstraints(min_length=1, max_length=MAX_LABEL_CHARS), AfterValidator(_not_blank)
]
_LABELS = TypeAdapter(list[Label])


def parse_labels(raw: str) -> list[str]:
    """JSON array of non-blank strings <= 100 chars; duplicates removed, order kept."""
    try:
        labels = _LABELS.validate_json(raw)
    except ValidationError as error:
        details = [
            {
                "field": field_path(("labels", *err["loc"])),
                "code": err["type"],
                "message": err["msg"],
            }
            for err in error.errors(include_url=False, include_input=False)
        ]
        raise AppError(
            422, ErrorCode.VALIDATION_ERROR, "labels must be a JSON array of labels", details
        ) from None
    unique = list(dict.fromkeys(labels))
    if not 1 <= len(unique) <= MAX_LABELS:
        raise AppError(
            422,
            ErrorCode.VALIDATION_ERROR,
            "labels must be a JSON array of labels",
            [
                {
                    "field": "labels",
                    "code": "length",
                    "message": f"between 1 and {MAX_LABELS} distinct labels required",
                }
            ],
        )
    return unique


def not_configured() -> AppError:
    return AppError(503, ErrorCode.NOT_CONFIGURED, "GEMINI_API_KEY or GEMINI_MODEL is not set")


def create_app(
    settings: Settings | None = None, provider: RecognitionProvider | None = None
) -> FastAPI:
    """The app; tests pass explicit settings and a fake provider."""
    settings = settings or get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(), format="%(levelname)s %(name)s %(message)s"
    )
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned: GeminiProvider | None = None
        if provider is not None:
            app.state.provider = provider
        elif settings.configured:
            owned = GeminiProvider.from_settings(settings)
            app.state.provider = owned
        else:
            app.state.provider = None
            logger.warning("not configured: GEMINI_API_KEY or GEMINI_MODEL is not set")
        app.state.prepare_slots = asyncio.Semaphore(PREPARE_CONCURRENCY)
        try:
            yield
        finally:
            if owned is not None:
                await owned.aclose()

    app = FastAPI(title="FitPlan ai-service", version="0.1.0", lifespan=lifespan)
    install_error_handlers(app)

    @app.middleware("http")
    async def limit_request_size(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        length = request.headers.get("content-length")
        if length is not None and length.isdigit() and int(length) > MAX_REQUEST_BYTES:
            return error_response(413, ErrorCode.PAYLOAD_TOO_LARGE, "Photo is larger than 8 MB")
        return await call_next(request)

    @app.get("/health")
    async def health() -> JSONResponse:
        if not settings.configured:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "not_configured",
                    "model": settings.gemini_model.strip() or None,
                },
            )
        return JSONResponse(content={"status": "ok", "model": settings.gemini_model.strip()})

    @app.post("/predict", response_model=Prediction)
    async def predict(
        request: Request,
        photo: Annotated[UploadFile, File(description="JPEG, PNG or WebP, at most 8 MB")],
        labels: Annotated[str, Form(description="JSON array of recognition labels")],
    ) -> Any:
        active: RecognitionProvider | None = request.app.state.provider
        if not settings.configured or active is None:
            raise not_configured()

        data = await photo.read(MAX_PHOTO_BYTES + 1)
        if len(data) > MAX_PHOTO_BYTES:
            raise AppError(413, ErrorCode.PAYLOAD_TOO_LARGE, "Photo is larger than 8 MB")
        label_list = parse_labels(labels)

        try:
            async with request.app.state.prepare_slots:
                prepared = await run_in_threadpool(prepare_photo, data)
        except InvalidImageError:
            raise AppError(
                400, ErrorCode.INVALID_IMAGE, "Photo must be a readable JPEG, PNG or WebP image"
            ) from None

        try:
            return await active.recognise(prepared.jpeg, label_list)
        except ProviderTimeoutError:
            raise AppError(
                504, ErrorCode.AI_UNAVAILABLE, "The recognition service did not answer in time"
            ) from None
        except ProviderError:
            raise AppError(
                502, ErrorCode.AI_UNAVAILABLE, "The recognition service is not available"
            ) from None

    return app
