"""The backend's client of `ai-service` (B-19; A-01, D25): `POST /predict`.

Only the photo and the active recognition labels are sent: no user data, allergies or ids
(api-rules.md "Recognition"). Error mapping as `ai-service/README.md` "Notes for the
backend": 502, 503, 504, a timeout or an unreachable service are `AiUnavailableError`
(503 `ai_unavailable`); 400 `invalid_image` is `InvalidImageError` (422).
"""

import json
import logging
import math
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.db.repositories.recognition import Detection
from app.domain.constants import RECOGNITION_CANDIDATES

logger = logging.getLogger(__name__)


class AiUnavailableError(Exception):
    """ai-service or Gemini failed, timed out or answered something invalid."""


class InvalidImageError(Exception):
    """ai-service could not read the photo."""


@dataclass(frozen=True)
class Prediction:
    model_name: str
    model_version: str
    detections: tuple[Detection, ...]


class RecognitionProvider(Protocol):
    async def predict(self, photo: bytes, content_type: str, labels: list[str]) -> Prediction: ...


def _confidence(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("confidence is not a number")
    confidence = float(value)
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("confidence outside 0-1")
    return confidence


def _grams(value: object) -> float | None:
    """The model's estimate; anything that is not a finite number becomes None, so the
    matcher takes the fallback (algorithms.md 11)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


def parse_prediction(body: object) -> Prediction:
    """ai-service's 200 answer; raises ValueError for anything malformed (no partial
    results)."""
    if not isinstance(body, dict):
        raise ValueError("answer is not an object")
    model, items = body.get("model"), body.get("items")
    if not isinstance(model, dict) or not isinstance(items, list):
        raise ValueError("answer has no model or items")
    name, version = model.get("name"), model.get("version")
    if not isinstance(name, str) or not isinstance(version, str):
        raise ValueError("model name or version missing")
    detections = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("label"), str):
            raise ValueError("item without a label")
        alternatives = item.get("alternatives") or []
        if not isinstance(alternatives, list):
            raise ValueError("alternatives are not a list")
        pairs = []
        for alternative in alternatives[: RECOGNITION_CANDIDATES - 1]:
            if not isinstance(alternative, dict) or not isinstance(alternative.get("label"), str):
                raise ValueError("alternative without a label")
            pairs.append((alternative["label"], _confidence(alternative.get("confidence"))))
        detections.append(
            Detection(
                label=item["label"],
                confidence=_confidence(item.get("confidence")),
                grams=_grams(item.get("grams")),
                alternatives=tuple(pairs),
            )
        )
    return Prediction(name, version, tuple(detections))


class HttpRecognitionProvider:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,  # tests replace the network
    ) -> None:
        self._url = base_url.rstrip("/") + "/predict"
        self._timeout = timeout_seconds
        self._transport = transport

    async def predict(self, photo: bytes, content_type: str, labels: list[str]) -> Prediction:
        try:
            client = httpx.AsyncClient(timeout=self._timeout, transport=self._transport)
            async with client:
                response = await client.post(
                    self._url,
                    files={"photo": ("photo", photo, content_type)},
                    data={"labels": json.dumps(labels, ensure_ascii=False)},
                )
        except httpx.HTTPError as exc:
            logger.warning("ai-service unreachable: %s", type(exc).__name__)
            raise AiUnavailableError from None
        if response.status_code == 400:
            raise InvalidImageError
        if response.status_code != 200:
            logger.warning("ai-service answered %d", response.status_code)
            raise AiUnavailableError
        try:
            return parse_prediction(response.json())
        except ValueError as exc:  # also a body that is not JSON
            logger.warning("ai-service answer rejected: %s", exc)
            raise AiUnavailableError from None
