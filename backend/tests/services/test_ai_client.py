"""The backend's ai-service client (B-19): request shape and error mapping as
ai-service/README.md "Notes for the backend"."""

import asyncio
import json

import httpx
import pytest

from app.services.ai_client import (
    AiUnavailableError,
    HttpRecognitionProvider,
    InvalidImageError,
    parse_prediction,
)

ANSWER = {
    "model": {"name": "gemini-3.1-flash-lite", "version": "gemini-3.1-flash-lite"},
    "items": [
        {
            "label": "basmati rice, cooked",
            "confidence": 0.86,
            "grams": 180,
            "alternatives": [{"label": "white rice, cooked", "confidence": 0.1}],
        },
        {"label": "żurek", "confidence": 0.4, "grams": None, "alternatives": []},
    ],
}


def _predict(handler, labels=("basmati rice, cooked",)):
    provider = HttpRecognitionProvider(
        "http://ai-service:8001/", 8.5, transport=httpx.MockTransport(handler)
    )
    return asyncio.run(provider.predict(b"jpeg bytes", "image/jpeg", list(labels)))


def test_sends_the_photo_and_the_labels_and_maps_the_answer():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.read()
        return httpx.Response(200, json=ANSWER)

    prediction = _predict(handler, labels=("basmati rice, cooked", "żurek"))

    assert seen["url"] == "http://ai-service:8001/predict"
    assert b"jpeg bytes" in seen["body"]
    assert (
        json.dumps(["basmati rice, cooked", "żurek"], ensure_ascii=False).encode() in seen["body"]
    )
    assert (prediction.model_name, len(prediction.detections)) == ("gemini-3.1-flash-lite", 2)
    rice, zurek = prediction.detections
    assert (rice.label, rice.confidence, rice.grams, rice.alternatives) == (
        "basmati rice, cooked",
        0.86,
        180.0,
        (("white rice, cooked", 0.1),),
    )
    assert (zurek.grams, zurek.alternatives) == (None, ())


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (400, InvalidImageError),
        (502, AiUnavailableError),
        (503, AiUnavailableError),
        (504, AiUnavailableError),
        (422, AiUnavailableError),  # a bad request of ours is still no answer for the user
    ],
)
def test_error_statuses(status, error):
    with pytest.raises(error):
        _predict(lambda request: httpx.Response(status, json={"code": "x"}))


def test_unreachable_or_timed_out_service_is_unavailable():
    def handler(request):
        raise httpx.ConnectTimeout("no route", request=request)

    with pytest.raises(AiUnavailableError):
        _predict(handler)


@pytest.mark.parametrize(
    "body",
    [
        {"items": []},
        {"model": {"name": "m", "version": "v"}, "items": [{"label": "x", "confidence": 1.5}]},
        {"model": {"name": "m", "version": "v"}, "items": [{"confidence": 0.5}]},
        {
            "model": {"name": "m", "version": "v"},
            "items": [{"label": "x", "confidence": 0.5, "alternatives": [{"label": 1}]}],
        },
    ],
)
def test_a_malformed_answer_is_rejected_whole(body):
    with pytest.raises(ValueError):
        parse_prediction(body)
    with pytest.raises(AiUnavailableError):
        _predict(lambda request: httpx.Response(200, json=body))


def test_a_non_json_answer_is_unavailable():
    with pytest.raises(AiUnavailableError):
        _predict(lambda request: httpx.Response(200, text="<html>"))


def test_grams_that_are_not_a_finite_number_take_the_fallback():
    body = {
        "model": {"name": "m", "version": "v"},
        "items": [
            {"label": "a", "confidence": 0.5, "grams": "200"},
            {"label": "b", "confidence": 0.5, "grams": True},
        ],
    }
    assert [d.grams for d in parse_prediction(body).detections] == [None, None]
