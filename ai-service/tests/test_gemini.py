"""A-01: GeminiProvider with a fake client (app/gemini.py). No network."""

import asyncio
import json
import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import httpx
import httpx2
import pytest
from google.genai import errors as genai_errors
from google.genai import types

from app.gemini import LABELS_INTRO, PROMPT, GeminiProvider
from app.provider import ProviderError, ProviderTimeoutError
from tests.conftest import TEST_KEY, TEST_MODEL, make_settings

pytestmark = pytest.mark.anyio

LABELS = ["rice", "chicken breast", "broccoli", "rice, brown"]
JPEG = b"\xff\xd8\xff fake jpeg bytes"


# ---------------------------------------------------------------- fakes


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@dataclass
class Step:
    """One generate_content call: advance the fake clock, maybe sleep, then answer."""

    result: Any  # a response, or an exception to raise
    elapsed: float = 0.3  # seconds on the fake clock (the retry window)
    sleep: float = 0.0  # real seconds (the timeout)


class FakeModels:
    def __init__(self, steps: list[Step], clock: FakeClock) -> None:
        self.steps = steps
        self.clock = clock
        self.calls: list[dict[str, Any]] = []

    async def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
        self.calls.append({"model": model, "contents": contents, "config": config})
        step = self.steps.pop(0)
        self.clock.now += step.elapsed
        if step.sleep:
            await asyncio.sleep(step.sleep)
        if isinstance(step.result, BaseException):
            raise step.result
        return step.result


def provider_with(*steps: Step, **settings: object) -> tuple[GeminiProvider, FakeModels]:
    clock = FakeClock()
    models = FakeModels(list(steps), clock)
    client = SimpleNamespace(aio=SimpleNamespace(models=models))
    return GeminiProvider(make_settings(**settings), client, clock=clock), models


def response(
    items: list[dict[str, Any]] | None = None,
    *,
    text: str | None = None,
    model_version: str | None = "gemini-test-001",
    finish: types.FinishReason | None = types.FinishReason.STOP,
) -> types.GenerateContentResponse:
    body = text if text is not None else json.dumps({"items": items or []})
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=[types.Part(text=body)]),
                finish_reason=finish,
            )
        ],
        model_version=model_version,
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=1200, candidates_token_count=80, thoughts_token_count=7
        ),
    )


def item(label: str = "rice", confidence: float = 0.9, grams: float = 150, alternatives=()):
    return {
        "label": label,
        "confidence": confidence,
        "grams": grams,
        "alternatives": [{"label": a, "confidence": c} for a, c in alternatives],
    }


def api_error(status: int, message: str = "error") -> genai_errors.APIError:
    body = {"error": {"code": status, "message": message, "status": "ERROR"}}
    error_class = genai_errors.ServerError if status >= 500 else genai_errors.ClientError
    return error_class(status, body)


OK = Step(response([item()]))


# ---------------------------------------------------------------- request


async def test_request_sends_the_photo_prompt_and_config():
    provider, models = provider_with(OK)

    await provider.recognise(JPEG, LABELS)

    (call,) = models.calls
    assert call["model"] == TEST_MODEL
    photo, prompt = call["contents"]
    assert photo.inline_data.data == JPEG
    assert photo.inline_data.mime_type == "image/jpeg"
    assert prompt == f"{PROMPT}\n\n{LABELS_INTRO}\n{json.dumps(LABELS)}"
    config = call["config"]
    assert config.temperature == 0
    assert config.max_output_tokens == 4096
    assert config.response_mime_type == "application/json"
    assert config.response_schema is None  # the JSON schema field is used instead
    assert config.media_resolution == types.MediaResolution.MEDIA_RESOLUTION_MEDIUM
    assert config.thinking_config.thinking_level == types.ThinkingLevel.MINIMAL


@pytest.mark.parametrize(
    ("resolution", "level", "expected_resolution", "expected_level"),
    [
        ("low", "low", types.MediaResolution.MEDIA_RESOLUTION_LOW, types.ThinkingLevel.LOW),
        ("high", "high", types.MediaResolution.MEDIA_RESOLUTION_HIGH, types.ThinkingLevel.HIGH),
    ],
)
async def test_media_resolution_and_thinking_level_come_from_settings(
    resolution, level, expected_resolution, expected_level
):
    provider, models = provider_with(
        OK, gemini_media_resolution=resolution, gemini_thinking_level=level
    )

    await provider.recognise(JPEG, LABELS)

    config = models.calls[0]["config"]
    assert config.media_resolution == expected_resolution
    assert config.thinking_config.thinking_level == expected_level


async def test_each_label_is_in_the_prompt_once_as_json_and_not_in_the_schema():
    labels = ['żurek "domowy"', "rice, brown", "rice"]
    provider, models = provider_with(OK)

    await provider.recognise(JPEG, labels)

    call = models.calls[0]
    prompt = call["contents"][1]
    listed = prompt.removeprefix(f"{PROMPT}\n\n{LABELS_INTRO}\n")
    assert json.loads(listed) == labels
    for label in labels:
        assert prompt.count(json.dumps(label, ensure_ascii=False)) == 1
    assert "żurek" in listed  # ensure_ascii=False: Polish letters are not escaped
    schema = call["config"].response_json_schema
    dumped = json.dumps(schema, ensure_ascii=False)
    assert "enum" not in dumped and "$defs" not in dumped
    assert not any(json.dumps(label, ensure_ascii=False) in dumped for label in labels)


async def test_schema_shapes_the_answer():
    provider, models = provider_with(OK)

    await provider.recognise(JPEG, LABELS)

    schema = models.calls[0]["config"].response_json_schema
    assert schema["required"] == ["items"]
    assert schema["properties"]["items"]["maxItems"] == 20
    entry = schema["properties"]["items"]["items"]
    assert entry["required"] == ["label", "confidence", "grams", "alternatives"]
    assert entry["properties"]["label"] == {"type": "string"}
    assert entry["properties"]["confidence"] == {"type": "number", "minimum": 0, "maximum": 1}
    assert entry["properties"]["grams"] == {"type": "number", "minimum": 0}
    assert entry["properties"]["alternatives"]["maxItems"] == 2
    alternative = entry["properties"]["alternatives"]["items"]
    assert alternative["properties"]["label"] == {"type": "string"}
    assert alternative["required"] == ["label", "confidence"]


def test_real_client_has_sdk_retries_off_and_no_sdk_timeout():
    provider = GeminiProvider.from_settings(make_settings(gemini_timeout_s=7))

    options = provider._client._api_client._http_options
    assert options.retry_options.attempts == 1
    # an SDK timeout becomes Google's request deadline, which must be >= 10 s (HTTP 400)
    assert options.timeout is None


# ---------------------------------------------------------------- answer


async def test_answer_is_mapped_to_the_prediction():
    provider, _ = provider_with(
        Step(
            response(
                [
                    item("rice", 0.82, 180.5, [("rice, brown", 0.1), ("broccoli", 0.05)]),
                    item("chicken breast", 0.6, 120),
                ]
            )
        )
    )

    prediction = await provider.recognise(JPEG, LABELS)

    assert prediction.model_dump() == {
        "model": {"name": TEST_MODEL, "version": "gemini-test-001"},
        "items": [
            {
                "label": "rice",
                "confidence": 0.82,
                "grams": 180.5,
                "alternatives": [
                    {"label": "rice, brown", "confidence": 0.1},
                    {"label": "broccoli", "confidence": 0.05},
                ],
            },
            {"label": "chicken breast", "confidence": 0.6, "grams": 120.0, "alternatives": []},
        ],
    }


@pytest.mark.parametrize("model_version", [None, "", "  "])
async def test_version_falls_back_to_the_model_name(model_version):
    provider, _ = provider_with(Step(response([item()], model_version=model_version)))

    prediction = await provider.recognise(JPEG, LABELS)

    assert prediction.model.version == TEST_MODEL


async def test_photo_without_food_gives_no_items():
    provider, _ = provider_with(Step(response([])))

    prediction = await provider.recognise(JPEG, LABELS)

    assert prediction.items == []


async def test_unknown_labels_are_dropped():
    provider, _ = provider_with(
        Step(
            response(
                [
                    item("pizza", 0.9),
                    item("rice", 0.8, alternatives=[("pizza", 0.3), ("broccoli", 0.2)]),
                    item("broccoli", 0.7, alternatives=[("broccoli", 0.4), ("rice", 0.1)]),
                    item("chicken breast", 0.6, alternatives=[("rice", 0.2), ("rice", 0.1)]),
                ]
            )
        )
    )

    prediction = await provider.recognise(JPEG, LABELS)

    assert [(i.label, [a.label for a in i.alternatives]) for i in prediction.items] == [
        ("rice", ["broccoli"]),
        ("broccoli", ["rice"]),
        ("chicken breast", ["rice"]),
    ]


async def test_labels_match_trimmed_and_lower_cased_and_come_back_as_sent():
    labels = ["Rice", "chicken breast", "Broccoli"]
    provider, _ = provider_with(
        Step(
            response(
                [
                    item("  rice ", 0.9, alternatives=[("RICE", 0.5), ("broccoli ", 0.2)]),
                    item(
                        "Chicken Breast", 0.8, alternatives=[("broccoli", 0.3), ("BROCCOLI", 0.1)]
                    ),
                    item("chicken", 0.7),
                ]
            )
        )
    )

    prediction = await provider.recognise(JPEG, labels)

    assert [(i.label, [a.label for a in i.alternatives]) for i in prediction.items] == [
        ("Rice", ["Broccoli"]),
        ("chicken breast", ["Broccoli"]),
    ]


@pytest.mark.parametrize("grams", [0, 0.0, -5])
async def test_grams_zero_or_less_become_null(grams):
    provider, _ = provider_with(Step(response([item(grams=grams)])))

    prediction = await provider.recognise(JPEG, LABELS)

    assert prediction.items[0].grams is None


VALID = item()


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        '{"items": [',  # cut off
        "{}",
        '{"items": null}',
        json.dumps({"items": [{**VALID, "confidence": 1.5}]}),
        json.dumps({"items": [{**VALID, "confidence": -0.1}]}),
        json.dumps({"items": [{**VALID, "grams": "lots"}]}),
        json.dumps({"items": [{k: v for k, v in VALID.items() if k != "label"}]}),
        json.dumps({"items": [{k: v for k, v in VALID.items() if k != "grams"}]}),
        json.dumps({"items": [{k: v for k, v in VALID.items() if k != "alternatives"}]}),
        json.dumps({"items": [item(alternatives=[("broccoli", 0.1)] * 3)]}),
        json.dumps({"items": [item()] * 21}),
        '{"items": [{"label": "rice", "confidence": NaN, "grams": 1, "alternatives": []}]}',
        '{"items": [{"label": "rice", "confidence": 0.5, "grams": Infinity, "alternatives": []}]}',
    ],
)
async def test_invalid_answer_is_an_error_never_a_partial_result(text):
    provider, _ = provider_with(Step(response(text=text)))

    with pytest.raises(ProviderError) as raised:
        await provider.recognise(JPEG, LABELS)

    assert not isinstance(raised.value, ProviderTimeoutError)


@pytest.mark.parametrize(
    "finish",
    [types.FinishReason.MAX_TOKENS, types.FinishReason.SAFETY, types.FinishReason.RECITATION],
)
async def test_unfinished_answer_is_an_error(finish):
    provider, _ = provider_with(Step(response([item()], finish=finish)))

    with pytest.raises(ProviderError):
        await provider.recognise(JPEG, LABELS)


async def test_blocked_photo_is_an_error():
    blocked = types.GenerateContentResponse(
        prompt_feedback=types.GenerateContentResponsePromptFeedback(
            block_reason=types.BlockedReason.SAFETY
        )
    )
    provider, models = provider_with(Step(blocked))

    with pytest.raises(ProviderError, match="blocked"):
        await provider.recognise(JPEG, LABELS)
    assert len(models.calls) == 1


@pytest.mark.parametrize(
    "answer",
    [
        types.GenerateContentResponse(candidates=[]),
        types.GenerateContentResponse(
            candidates=[types.Candidate(finish_reason=types.FinishReason.STOP)]
        ),
        response(text=""),
    ],
)
async def test_empty_answer_is_an_error(answer):
    provider, _ = provider_with(Step(answer))

    with pytest.raises(ProviderError):
        await provider.recognise(JPEG, LABELS)


# ---------------------------------------------------------------- retries and timeout


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_fast_429_or_5xx_is_retried_once(status, caplog):
    provider, models = provider_with(Step(api_error(status), elapsed=0.4), OK)

    with caplog.at_level(logging.INFO, logger="app.gemini"):
        prediction = await provider.recognise(JPEG, LABELS)

    assert len(prediction.items) == 1
    assert len(models.calls) == 2
    assert "attempts=2" in caplog.text


async def test_answer_at_exactly_the_window_is_still_retried():
    provider, models = provider_with(Step(api_error(503), elapsed=2.0), OK)

    await provider.recognise(JPEG, LABELS)

    assert len(models.calls) == 2


async def test_there_is_no_second_retry():
    provider, models = provider_with(
        Step(api_error(503), elapsed=0.1), Step(api_error(503), elapsed=0.1), OK
    )

    with pytest.raises(ProviderError, match="503"):
        await provider.recognise(JPEG, LABELS)
    assert len(models.calls) == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404])
async def test_4xx_other_than_429_is_not_retried(status):
    provider, models = provider_with(Step(api_error(status), elapsed=0.1), OK)

    with pytest.raises(ProviderError, match=str(status)):
        await provider.recognise(JPEG, LABELS)
    assert len(models.calls) == 1


@pytest.mark.parametrize("status", [429, 503])
async def test_slow_error_is_not_retried(status):
    provider, models = provider_with(Step(api_error(status), elapsed=2.5), OK)

    with pytest.raises(ProviderError):
        await provider.recognise(JPEG, LABELS)
    assert len(models.calls) == 1


async def test_timeout_is_not_retried():
    provider, models = provider_with(Step(OK.result, sleep=5), OK, gemini_timeout_s=0.05)

    loop = asyncio.get_running_loop()
    started = loop.time()
    with pytest.raises(ProviderTimeoutError):
        await provider.recognise(JPEG, LABELS)

    assert loop.time() - started < 1
    assert len(models.calls) == 1


async def test_the_retry_shares_the_time_budget():
    provider, models = provider_with(
        Step(api_error(503), elapsed=0.1), Step(OK.result, sleep=5), gemini_timeout_s=0.05
    )

    with pytest.raises(ProviderTimeoutError):
        await provider.recognise(JPEG, LABELS)
    assert len(models.calls) == 2


@pytest.mark.parametrize("timeout", [httpx.ReadTimeout, httpx2.ReadTimeout])
async def test_sdk_http_timeout_is_a_timeout_and_not_retried(timeout):
    provider, models = provider_with(Step(timeout("read timed out")), OK)

    with pytest.raises(ProviderTimeoutError):
        await provider.recognise(JPEG, LABELS)
    assert len(models.calls) == 1


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx2.ConnectError])
async def test_transport_error_is_an_error_and_not_retried(failure):
    provider, models = provider_with(Step(failure("connection refused")), OK)

    with pytest.raises(ProviderError) as raised:
        await provider.recognise(JPEG, LABELS)
    assert not isinstance(raised.value, ProviderTimeoutError)
    assert len(models.calls) == 1


# ---------------------------------------------------------------- logging


async def test_one_log_line_per_call_with_tokens(caplog):
    provider, _ = provider_with(OK)

    with caplog.at_level(logging.INFO, logger="app.gemini"):
        await provider.recognise(JPEG, LABELS)

    (record,) = caplog.records
    message = record.getMessage()
    for part in (
        f"model={TEST_MODEL}",
        "outcome=ok",
        "attempts=1",
        "items=1",
        "prompt_tokens=1200",
        "output_tokens=80",
        "thinking_tokens=7",
        "latency_ms=300",
    ):
        assert part in message


@pytest.mark.parametrize(
    "error",
    [
        api_error(403, f"API key not valid: {TEST_KEY}"),
        api_error(503, f"overloaded for {TEST_KEY}"),
        RuntimeError(f"boom {TEST_KEY}"),
        httpx.ConnectError(f"https://example.invalid/?key={TEST_KEY}"),
    ],
)
async def test_key_never_reaches_logs_or_errors(error, caplog):
    provider, _ = provider_with(Step(error, elapsed=3), Step(error, elapsed=3))

    with caplog.at_level(logging.DEBUG), pytest.raises(ProviderError) as raised:
        await provider.recognise(JPEG, LABELS)

    assert TEST_KEY not in caplog.text
    assert TEST_KEY not in str(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__
    assert len(caplog.records) == 1
    assert "outcome=" in caplog.records[0].getMessage()
