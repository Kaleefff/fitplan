"""A-01: POST /predict and GET /health with a fake provider (app/main.py)."""

import json
import logging
from collections.abc import Iterator, Sequence

import pytest
from fastapi.testclient import TestClient

from app.config import MAX_PHOTO_BYTES
from app.gemini import GeminiProvider
from app.main import MAX_LABELS, QUIET_LOGGERS, create_app
from app.provider import ProviderError, ProviderTimeoutError
from app.schemas import Alternative, Item, ModelInfo, Prediction
from tests.conftest import TEST_KEY, TEST_MODEL, make_photo, make_settings, open_photo

LABELS = ["rice", "chicken breast", "broccoli"]
PREDICTION = Prediction(
    model=ModelInfo(name=TEST_MODEL, version="gemini-test-001"),
    items=[
        Item(
            label="rice",
            confidence=0.82,
            grams=180.0,
            alternatives=[Alternative(label="broccoli", confidence=0.1)],
        ),
        Item(label="chicken breast", confidence=0.25, grams=None, alternatives=[]),
    ],
)


class FakeProvider:
    def __init__(self, result: Prediction | Exception = PREDICTION) -> None:
        self.result = result
        self.calls: list[tuple[bytes, list[str]]] = []

    async def recognise(self, jpeg: bytes, labels: Sequence[str]) -> Prediction:
        self.calls.append((jpeg, list(labels)))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def make_client(provider: FakeProvider | None = None, **settings: object) -> TestClient:
    app = create_app(make_settings(**settings), provider or FakeProvider())
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def client(provider: FakeProvider) -> Iterator[TestClient]:
    with make_client(provider) as test_client:
        yield test_client


def post(
    client: TestClient,
    photo: bytes | None = None,
    labels: str | None = None,
    filename: str = "meal.jpg",
    content_type: str = "image/jpeg",
):
    files = {} if photo is None else {"photo": (filename, photo, content_type)}
    data = {} if labels is None else {"labels": labels}
    return client.post("/predict", files=files or None, data=data)


def predict(client: TestClient, photo: bytes | None = None, labels: Sequence[str] = LABELS):
    return post(client, make_photo() if photo is None else photo, json.dumps(list(labels)))


def assert_error(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"code", "message", "details"}
    assert body["code"] == code
    assert isinstance(body["details"], list)
    return body


# ---------------------------------------------------------------- success


def test_predict_returns_the_documented_shape(client, provider):
    response = predict(client)

    assert response.status_code == 200
    assert response.json() == {
        "model": {"name": TEST_MODEL, "version": "gemini-test-001"},
        "items": [
            {
                "label": "rice",
                "confidence": 0.82,
                "grams": 180.0,
                "alternatives": [{"label": "broccoli", "confidence": 0.1}],
            },
            {"label": "chicken breast", "confidence": 0.25, "grams": None, "alternatives": []},
        ],
    }
    assert len(provider.calls) == 1


def test_provider_gets_the_resized_jpeg_without_exif(client, provider):
    response = predict(client, make_photo("PNG", (3000, 2000)))

    assert response.status_code == 200
    jpeg, _ = provider.calls[0]
    sent = open_photo(jpeg)
    assert sent.format == "JPEG"
    assert sent.size == (1024, 683)
    assert len(sent.getexif()) == 0


def test_labels_keep_their_order_without_duplicates(client, provider):
    predict(client, labels=["rice", "Rice", "broccoli", "rice", "broccoli"])

    assert provider.calls[0][1] == ["rice", "Rice", "broccoli"]


def test_label_of_100_chars_and_2000_labels_are_accepted(client, provider):
    labels = ["x" * 100, *(f"food {i}" for i in range(MAX_LABELS - 1))]

    assert predict(client, labels=labels).status_code == 200
    assert len(provider.calls[0][1]) == MAX_LABELS


def test_declared_content_type_and_name_are_not_trusted(client, provider):
    png_as_gif = post(client, make_photo("PNG"), json.dumps(LABELS), "meal.gif", "image/gif")
    gif_as_jpeg = post(client, make_photo("GIF"), json.dumps(LABELS), "meal.jpg", "image/jpeg")

    assert png_as_gif.status_code == 200
    assert_error(gif_as_jpeg, 400, "invalid_image")
    assert len(provider.calls) == 1


# ---------------------------------------------------------------- errors


@pytest.mark.parametrize(
    "photo",
    [b"", b"not an image", make_photo("GIF"), make_photo("BMP"), make_photo("PNG")[:60]],
)
def test_unreadable_photo_is_400_invalid_image(client, provider, photo):
    assert_error(predict(client, photo), 400, "invalid_image")
    assert provider.calls == []


def test_photo_over_8_mib_is_413(client, provider):
    assert_error(predict(client, b"\xff" * (MAX_PHOTO_BYTES + 1)), 413, "payload_too_large")
    assert provider.calls == []


def test_photo_of_exactly_8_mib_passes_the_size_check(client):
    # not an image, so it reaches the photo check: the size limit itself let it through
    assert_error(predict(client, b"\xff" * MAX_PHOTO_BYTES), 400, "invalid_image")


def test_huge_request_is_refused_before_it_is_read(client, provider):
    response = predict(client, b"\xff" * (MAX_PHOTO_BYTES + 3 * 1024 * 1024))

    assert_error(response, 413, "payload_too_large")
    assert provider.calls == []


@pytest.mark.parametrize(
    "labels",
    [
        "not json",
        '{"rice": 1}',
        '"rice"',
        "[]",
        '[""]',
        '["   "]',
        "[1]",
        '["rice", null]',
        json.dumps(["x" * 101]),
        json.dumps([f"food {i}" for i in range(MAX_LABELS + 1)]),
    ],
)
def test_invalid_labels_are_422(client, provider, labels):
    body = assert_error(post(client, make_photo(), labels), 422, "validation_error")

    assert body["details"]
    assert all(detail["field"].startswith("labels") for detail in body["details"])
    assert provider.calls == []


def test_missing_fields_are_422(client, provider):
    no_labels = assert_error(post(client, make_photo()), 422, "validation_error")
    no_photo = assert_error(post(client, labels=json.dumps(LABELS)), 422, "validation_error")

    assert [d["field"] for d in no_labels["details"]] == ["body.labels"]
    assert [d["field"] for d in no_photo["details"]] == ["body.photo"]
    assert provider.calls == []


def test_provider_error_is_502_ai_unavailable():
    with make_client(FakeProvider(ProviderError(f"Gemini answered HTTP 500 {TEST_KEY}"))) as c:
        body = assert_error(predict(c), 502, "ai_unavailable")

    assert body["details"] == []
    assert TEST_KEY not in json.dumps(body)


def test_provider_timeout_is_504_ai_unavailable():
    with make_client(FakeProvider(ProviderTimeoutError("too slow"))) as c:
        assert_error(predict(c), 504, "ai_unavailable")


def test_unexpected_provider_failure_is_500_without_details():
    with make_client(FakeProvider(RuntimeError(TEST_KEY))) as c:
        body = assert_error(predict(c), 500, "internal_error")

    assert TEST_KEY not in json.dumps(body)


@pytest.mark.parametrize(
    "settings",
    [{"gemini_api_key": ""}, {"gemini_api_key": "   "}, {"gemini_model": ""}],
)
def test_missing_key_or_model_is_503_not_configured(provider, settings):
    with make_client(provider, **settings) as c:
        assert_error(predict(c), 503, "not_configured")
        health = c.get("/health")

    assert health.status_code == 503
    assert health.json()["status"] == "not_configured"
    assert provider.calls == []


def test_unknown_path_and_method_use_the_error_model(client):
    assert_error(client.get("/nope"), 404, "not_found")
    assert_error(client.get("/predict"), 405, "method_not_allowed")


def test_malformed_multipart_body_is_422(client):
    response = client.post(
        "/predict",
        content=b"--x\r\nbroken",
        headers={"content-type": "multipart/form-data; boundary=x"},
    )

    assert_error(response, 422, "validation_error")


# ---------------------------------------------------------------- health, settings


def test_health_reports_the_model_and_never_calls_the_provider(client, provider):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "model": TEST_MODEL}
    assert provider.calls == []


def test_key_is_not_in_the_settings_repr():
    settings = make_settings()

    for text in (repr(settings), str(settings), settings.model_dump_json()):
        assert TEST_KEY not in text
    assert settings.gemini_api_key.get_secret_value() == TEST_KEY


def test_configured_app_builds_and_closes_the_gemini_provider():
    app = create_app(make_settings())

    with TestClient(app) as c:
        assert isinstance(app.state.provider, GeminiProvider)
        assert c.get("/health").status_code == 200


@pytest.mark.parametrize("timeout", [0, -1, 10, 12.5])
def test_timeout_must_stay_below_nfr_perf(timeout):
    with pytest.raises(ValueError, match="gemini_timeout_s"):
        make_settings(gemini_timeout_s=timeout)


# ---------------------------------------------------------------- logging


def test_sdk_and_http_client_log_warnings_only():
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.NOTSET)

    create_app(make_settings(log_level="DEBUG"), FakeProvider())

    assert QUIET_LOGGERS == ("google_genai", "httpx2")
    for name in QUIET_LOGGERS:
        assert logging.getLogger(name).getEffectiveLevel() == logging.WARNING
        # their children too, e.g. google_genai.models ("AFC is enabled")
        assert logging.getLogger(f"{name}.child").getEffectiveLevel() == logging.WARNING
