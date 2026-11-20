"""GeminiProvider: RecognitionProvider on the Gemini API (D25).

One `generate_content` call per photo. The prompt ends with the given labels as a JSON
array; the JSON response schema fixes the shape of the answer, with every label a plain
string. D25 asks for a schema enum of the labels instead, but Gemini refuses an enum of
the 504 seed labels ("too many states" / "too much branching", HTTP 400, measured
2026-11-19 with gemini-3.1-flash-lite), so ai-service enforces the list itself: a label
matches after trimming and lower-casing (algorithms.md 11) and is returned as sent.

Time and retries: the whole call, the retry included, has `GEMINI_TIMEOUT_S`, enforced
by asyncio.timeout only (no SDK timeout: see from_settings). The SDK's own retries are
off. One retry, only after a 429 or 5xx that came back within
RETRY_WINDOW_S; never after a timeout or any other error. A timeout raises
ProviderTimeoutError; any other failure, a blocked photo or an invalid answer raises
ProviderError. There is never a partial result: either the whole answer validates or
the call fails. The only filtering is by label: an item whose label is not in the list
is dropped, and so is an alternative not in the list, equal to its item's label or
repeated.

Logging: one line per call with the model, outcome, latency, attempts and token counts.
Never the key, the photo, the labels or the model's answer; error messages are not
logged or chained either, only the HTTP status or the exception type.
"""

import asyncio
import json
import logging
import time
from collections.abc import Callable, Sequence
from typing import Annotated, Any

import httpx
import httpx2
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

from app.config import Settings
from app.provider import ProviderError, ProviderTimeoutError
from app.schemas import MAX_ALTERNATIVES, MAX_ITEMS, Alternative, Item, ModelInfo, Prediction

logger = logging.getLogger(__name__)

# the SDK sends with httpx2 (a fork under its own namespace) when it is installed, as
# google-genai 3.x requires, and with httpx otherwise; a timeout from either is a timeout
HTTP_TIMEOUTS: tuple[type[Exception], ...] = (httpx.TimeoutException, httpx2.TimeoutException)

PROMPT = (
    "Identify every food and drink visible in the photo. For each, choose the closest "
    "label, estimate the eaten portion in grams, and give your confidence from 0 to 1 and "
    "up to two alternative labels. Return an empty list if the photo shows no food."
)
LABELS_INTRO = "Labels (use only these, copied exactly):"
TEMPERATURE = 0.0
MAX_OUTPUT_TOKENS = 4096
RETRY_WINDOW_S = 2.0  # a 429 or 5xx is retried only if it came back this fast
RETRY_STATUS = 429

MEDIA_RESOLUTION = {
    "low": types.MediaResolution.MEDIA_RESOLUTION_LOW,
    "medium": types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
    "high": types.MediaResolution.MEDIA_RESOLUTION_HIGH,
}
THINKING_LEVEL = {
    "minimal": types.ThinkingLevel.MINIMAL,
    "low": types.ThinkingLevel.LOW,
    "medium": types.ThinkingLevel.MEDIUM,
    "high": types.ThinkingLevel.HIGH,
}
FINISHED = {None, types.FinishReason.STOP}

CONFIDENCE_SCHEMA = {"type": "number", "minimum": 0, "maximum": 1}


def prompt(labels: Sequence[str]) -> str:
    """PROMPT, then the labels as a JSON array (labels may contain commas)."""
    return f"{PROMPT}\n\n{LABELS_INTRO}\n{json.dumps(list(labels), ensure_ascii=False)}"


def response_schema() -> dict[str, Any]:
    """JSON schema of the answer: its shape only, no label list (see the module doc)."""
    label = {"type": "string"}
    alternative = {
        "type": "object",
        "properties": {"label": label, "confidence": CONFIDENCE_SCHEMA},
        "required": ["label", "confidence"],
    }
    item = {
        "type": "object",
        "properties": {
            "label": label,
            "confidence": CONFIDENCE_SCHEMA,
            "grams": {"type": "number", "minimum": 0},
            "alternatives": {"type": "array", "items": alternative, "maxItems": MAX_ALTERNATIVES},
        },
        "required": ["label", "confidence", "grams", "alternatives"],
    }
    return {
        "type": "object",
        "properties": {"items": {"type": "array", "items": item, "maxItems": MAX_ITEMS}},
        "required": ["items"],
    }


def normalise(label: str) -> str:
    """The matching key of algorithms.md 11: trimmed and lower-cased."""
    return label.strip().lower()


# ---------------------------------------------------------------- the model's answer

Confidence = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class _AnswerAlternative(BaseModel):
    label: str
    confidence: Confidence


class _AnswerItem(BaseModel):
    label: str
    confidence: Confidence
    grams: Annotated[float, Field(allow_inf_nan=False)]
    alternatives: list[_AnswerAlternative] = Field(max_length=MAX_ALTERNATIVES)


class _Answer(BaseModel):
    items: list[_AnswerItem] = Field(max_length=MAX_ITEMS)


class _Failure(Exception):
    """Internal: why the call failed, as the `outcome` of the log line."""

    def __init__(self, outcome: str, error: ProviderError) -> None:
        super().__init__(outcome)
        self.outcome = outcome
        self.error = error


def _to_items(answer: _Answer, labels: Sequence[str]) -> list[Item]:
    """Labels as sent; an item or alternative whose label is not in the list is dropped."""
    allowed: dict[str, str] = {}
    for label in labels:
        allowed.setdefault(normalise(label), label)
    items: list[Item] = []
    for raw in answer.items:
        label = allowed.get(normalise(raw.label))
        if label is None:
            continue
        alternatives: list[Alternative] = []
        seen = {label}
        for alt in raw.alternatives:
            alt_label = allowed.get(normalise(alt.label))
            if alt_label is not None and alt_label not in seen:
                seen.add(alt_label)
                alternatives.append(Alternative(label=alt_label, confidence=alt.confidence))
        items.append(
            Item(
                label=label,
                confidence=raw.confidence,
                grams=raw.grams if raw.grams > 0 else None,
                alternatives=alternatives,
            )
        )
    return items


def _retryable(status: int | None) -> bool:
    return status == RETRY_STATUS or (status is not None and 500 <= status <= 599)


# ---------------------------------------------------------------- provider


class GeminiProvider:
    def __init__(
        self,
        settings: Settings,
        client: Any,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._model = settings.gemini_model.strip()
        self._timeout_s = settings.gemini_timeout_s
        self._media_resolution = MEDIA_RESOLUTION[settings.gemini_media_resolution]
        self._thinking_level = THINKING_LEVEL[settings.gemini_thinking_level]
        self._client = client
        self._clock = clock

    @classmethod
    def from_settings(cls, settings: Settings) -> "GeminiProvider":
        """The real client: SDK retries off and no SDK timeout.

        The SDK sends its timeout to Google as the request deadline (X-Server-Timeout),
        and Google refuses one under 10 s with HTTP 400 ("Manually set deadline 8s is too
        short. Minimum allowed deadline is 10s", 2026-11-19). GEMINI_TIMEOUT_S stays below
        10 s (NFR-PERF), so the only time limit is asyncio.timeout in recognise(), which
        cancels the request.
        """
        client = genai.Client(
            api_key=settings.gemini_api_key.get_secret_value().strip(),
            http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)),
        )
        return cls(settings, client)

    async def aclose(self) -> None:
        await self._client.aio.aclose()

    def _config(self) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            temperature=TEMPERATURE,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            response_mime_type="application/json",
            response_json_schema=response_schema(),
            media_resolution=self._media_resolution,
            thinking_config=types.ThinkingConfig(thinking_level=self._thinking_level),
        )

    async def recognise(self, jpeg: bytes, labels: Sequence[str]) -> Prediction:
        labels = list(labels)
        contents = [types.Part.from_bytes(data=jpeg, mime_type="image/jpeg"), prompt(labels)]
        config = self._config()
        started = self._clock()
        attempts = 0
        outcome = "error"
        usage: types.GenerateContentResponseUsageMetadata | None = None
        items: int | None = None
        try:
            try:
                async with asyncio.timeout(self._timeout_s):
                    while True:
                        attempts += 1
                        attempt_started = self._clock()
                        try:
                            response = await self._client.aio.models.generate_content(
                                model=self._model, contents=contents, config=config
                            )
                            break
                        except genai_errors.APIError as error:
                            fast = self._clock() - attempt_started <= RETRY_WINDOW_S
                            if attempts == 1 and fast and _retryable(error.code):
                                continue
                            raise _Failure(
                                f"http_{error.code}",
                                ProviderError(f"Gemini answered HTTP {error.code}"),
                            ) from None
                        except HTTP_TIMEOUTS:
                            raise
                        except Exception as error:
                            raise _Failure(
                                f"transport_{type(error).__name__}",
                                ProviderError("Gemini could not be reached"),
                            ) from None
            except (TimeoutError, *HTTP_TIMEOUTS):
                raise _Failure(
                    "timeout",
                    ProviderTimeoutError(f"Gemini did not answer within {self._timeout_s:g} s"),
                ) from None

            usage = response.usage_metadata
            prediction = self._prediction(response, labels)
            items = len(prediction.items)
            outcome = "ok"
            return prediction
        except _Failure as failure:
            outcome = failure.outcome
            raise failure.error from None
        finally:
            latency_ms = round((self._clock() - started) * 1000)
            logger.log(
                logging.INFO if outcome == "ok" else logging.WARNING,
                "gemini model=%s outcome=%s latency_ms=%d attempts=%d items=%s "
                "prompt_tokens=%s output_tokens=%s thinking_tokens=%s",
                self._model,
                outcome,
                latency_ms,
                attempts,
                items,
                usage.prompt_token_count if usage else None,
                usage.candidates_token_count if usage else None,
                usage.thoughts_token_count if usage else None,
            )

    def _prediction(self, response: types.GenerateContentResponse, labels: list[str]) -> Prediction:
        feedback = response.prompt_feedback
        if feedback is not None and feedback.block_reason is not None:
            raise _Failure("blocked", ProviderError("Gemini blocked the photo"))
        if not response.candidates:
            raise _Failure("no_candidate", ProviderError("Gemini returned no answer"))
        finish_reason = response.candidates[0].finish_reason
        if finish_reason not in FINISHED:
            name = getattr(finish_reason, "name", str(finish_reason)).lower()
            raise _Failure(f"finish_{name}", ProviderError("Gemini did not finish the answer"))
        text = response.text
        if not text:
            raise _Failure("empty_answer", ProviderError("Gemini returned an empty answer"))
        try:
            answer = _Answer.model_validate_json(text)
        except ValidationError:
            raise _Failure(
                "invalid_answer", ProviderError("Gemini returned an invalid answer")
            ) from None
        version = (response.model_version or "").strip() or self._model
        return Prediction(
            model=ModelInfo(name=self._model, version=version),
            items=_to_items(answer, labels),
        )
