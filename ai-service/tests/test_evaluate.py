"""D-05: scripts/evaluate.py with a fake Gemini client. No network, no key, no .env."""

import csv
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import errors as genai_errors
from google.genai import types

from app.gemini import GeminiProvider
from app.schemas import Alternative, Item
from scripts.evaluate import (
    DEFAULT_CSV,
    DEFAULT_MANIFEST,
    PRODUCTION_TIMEOUT_S,
    Food,
    FoodFacts,
    ManifestError,
    Photo,
    PhotoResult,
    accuracy,
    compare,
    cost_per_1000,
    d05_checks,
    dropped_labels,
    format_set,
    latency,
    load_food_facts,
    main,
    parse_manifest,
    record_calls,
    result_path,
    run_photos,
    score,
    summarise,
    tokens,
    unknown_labels,
)
from scripts.measure_latency import load_labels
from tests.conftest import TEST_KEY, make_photo, make_settings

HEADER = "photo,set,expected,grams,source\n"


def write_manifest(folder: Path, body: str) -> Path:
    path = folder / "manifest.csv"
    path.write_text(HEADER + body, encoding="utf-8")
    return path


# ---------------------------------------------------------------- manifest


def test_manifest_parses_foods_accepted_labels_and_aligned_grams(tmp_path):
    path = write_manifest(
        tmp_path,
        'c01.jpg,common,"Eggs, boiled;rye bread",100;50,own\n'
        'p01.jpg,polish,"breaded pork cutlet; potatoes, boiled|mashed potatoes ;cucumber, raw"'
        ",150;;,https://commons.wikimedia.org/x\n"
        "\n"
        "g01.jpg,gap,żurek z jajkiem,,own\n",
    )

    common, polish, gap = parse_manifest(path)

    assert [f.labels for f in common.foods] == [("eggs, boiled",), ("rye bread",)]
    assert [f.grams for f in common.foods] == [100.0, 50.0]
    assert [f.labels for f in polish.foods] == [
        ("breaded pork cutlet",),
        ("potatoes, boiled", "mashed potatoes"),
        ("cucumber, raw",),
    ]
    assert [f.grams for f in polish.foods] == [150.0, None, None]
    assert polish.source == "https://commons.wikimedia.org/x"
    # the gap set is free text, never scored
    assert (gap.set, gap.expected, gap.foods) == ("gap", "żurek z jajkiem", ())


def test_manifest_without_grams_has_no_weighed_food(tmp_path):
    path = write_manifest(tmp_path, "a.jpg,common,apple;banana,,own\n")
    (photo,) = parse_manifest(path)
    assert [f.grams for f in photo.foods] == [None, None]


def test_manifest_lists_every_problem_with_its_line(tmp_path):
    path = write_manifest(
        tmp_path,
        "a.jpg,common,apple;banana,100,own\n"  # line 2: one weight for two foods
        "b.jpg,dinner,apple,,own\n"  # line 3: unknown set
        "c.jpg,polish,,,own\n"  # line 4: nothing expected
        "d.jpg,common,apple,-5,own\n"  # line 5: weight not above 0
        "e.jpg,common,apple;,,own\n"  # line 6: empty food
        "a.jpg,common,apple,,own\n"  # line 7: photo twice
        ",common,apple,,own\n",  # line 8: no photo
    )

    with pytest.raises(ManifestError) as raised:
        parse_manifest(path)

    message = str(raised.value)
    assert "line 2: grams has 1 entries, expected has 2" in message
    assert "line 3: set must be one of common, polish, gap" in message
    assert "line 4: expected is blank" in message
    assert "line 5: grams entry '-5' is not above 0" in message
    assert "line 6: expected has an empty food" in message
    assert "line 7: photo a.jpg is listed twice" in message
    assert "line 8: photo is blank" in message


def test_manifest_without_a_column_is_refused(tmp_path):
    path = tmp_path / "manifest.csv"
    path.write_text("photo,set,expected\na.jpg,common,apple\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="missing columns grams, source"):
        parse_manifest(path)


def test_unknown_labels_are_those_not_in_the_seed(tmp_path):
    path = write_manifest(
        tmp_path,
        'a.jpg,polish,"breaded pork cutlet;potatoes, boiled|kopytka;żurek",,own\n'
        "b.jpg,gap,bigos,,own\n",  # gap text is never checked
    )
    photos = parse_manifest(path)
    assert unknown_labels(photos, load_labels(DEFAULT_CSV)) == ["kopytka", "żurek"]


def test_food_facts_come_from_the_seed():
    facts = load_food_facts(DEFAULT_CSV)
    assert len(facts) == 504
    assert facts["breaded pork cutlet"].kcal_per_100g == 267.0
    assert facts["potatoes, boiled"].kcal_per_100g == 86.0
    assert all(f.default_portion_g > 0 for f in facts.values())


def test_committed_manifest_is_valid():
    """A typo in the manifest fails here, not in a paid run."""
    photos = parse_manifest(DEFAULT_MANIFEST)

    assert photos
    assert unknown_labels(photos, load_labels(DEFAULT_CSV)) == []
    # every photo name says its set, so a mix-up shows in the file list
    assert all(
        p.photo.startswith({"common": "c", "polish": "p", "gap": "g"}[p.set]) for p in photos
    )


# ---------------------------------------------------------------- scoring

FACTS = {
    "potatoes, boiled": FoodFacts(86, 200),
    "mashed potatoes": FoodFacts(113, 200),
    "breaded pork cutlet": FoodFacts(267, 150),
    "pork loin chop, cooked": FoodFacts(180, 150),
    "cucumber, raw": FoodFacts(15, 100),
    "ketchup": FoodFacts(101, 15),
    "eggs, boiled": FoodFacts(155, 100),
    "rye bread": FoodFacts(259, 40),
}


def food(*labels: str, grams: float | None = None) -> Food:
    return Food(tuple(labels), grams)


def photo(name: str, set_: str, *foods) -> Photo:
    return Photo(name, set_, "", "", "own", tuple(foods))


def it(label: str, grams: float | None, *alts: str, confidence: float = 0.8) -> Item:
    return Item(
        label=label,
        confidence=confidence,
        grams=grams,
        alternatives=[Alternative(label=a, confidence=0.1) for a in alts],
    )


SCHABOWY = photo(
    "p01.jpg",
    "polish",
    food("potatoes, boiled", "mashed potatoes", grams=200),
    food("breaded pork cutlet", grams=150),
    food("cucumber, raw"),
)
SCHABOWY_ANSWER = PhotoResult(
    SCHABOWY,
    "ok",
    seconds=2.0,
    items=[
        it("mashed potatoes", 180),  # label hit, accepted label
        it("pork loin chop, cooked", 120, "breaded pork cutlet"),  # alternatives hit only
        it("ketchup", 20),  # extra
    ],
    attempts=1,
    prompt_tokens=4000,
    output_tokens=300,
    thinking_tokens=100,
)
EGGS = photo("c01.jpg", "polish", food("eggs, boiled", grams=100), food("rye bread", grams=50))
EGGS_ANSWER = PhotoResult(
    EGGS,
    "ok",
    seconds=4.0,
    # no grams: the default portion (100 g) is used; the bread is half again too heavy
    items=[it("eggs, boiled", None), it("rye bread", 75)],
    attempts=1,
    prompt_tokens=5000,
    output_tokens=200,
    thinking_tokens=0,
)


def test_score_of_a_partly_recognised_meal():
    s = score(SCHABOWY_ANSWER, FACTS)

    assert (s.foods, s.label_hits, s.any_hits) == (3, 1, 2)
    assert s.all_found is False  # the cucumber was not found
    assert s.extra_items == 1  # ketchup; the pork chop has the cutlet as an alternative
    # potatoes: 180 g for 200 g; the cutlet has no label match, so no gram error
    assert s.gram_errors == ((20.0, 10.0),)
    assert s.weighed_unmatched == 1
    assert s.kcal_error_pct is None  # the cucumber was not weighed


def test_score_of_a_fully_weighed_meal_uses_default_portions_and_item_labels():
    s = score(EGGS_ANSWER, FACTS)

    assert (s.label_hits, s.any_hits, s.all_found, s.extra_items) == (2, 2, True, 0)
    assert s.gram_errors == ((0.0, 0.0), (25.0, 50.0))
    # true 155 + 129.5 = 284.5 kcal; estimate 155 + 194.25 = 349.25 kcal
    assert s.kcal_error_pct == pytest.approx(100 * 64.75 / 284.5)


def test_grams_of_items_with_the_same_label_are_summed():
    result = PhotoResult(
        photo("a.jpg", "common", food("potatoes, boiled", grams=200)),
        "ok",
        items=[it("potatoes, boiled", 120), it("potatoes, boiled", 100)],
    )
    assert score(result, FACTS).gram_errors == ((20.0, 10.0),)


def test_true_kcal_uses_the_first_accepted_label_and_estimate_never_the_alternatives():
    result = PhotoResult(
        photo("a.jpg", "common", food("potatoes, boiled", "mashed potatoes", grams=100)),
        "ok",
        items=[it("mashed potatoes", 100, "potatoes, boiled")],
    )
    # true 86 kcal (boiled); estimate 113 kcal (the item's own label)
    assert score(result, FACTS).kcal_error_pct == pytest.approx(100 * 27 / 86)


def test_a_failed_call_finds_nothing_and_has_no_gram_error():
    result = PhotoResult(SCHABOWY, "timeout", "Gemini did not answer within 7 s", seconds=7.0)
    s = score(result, FACTS)
    assert (s.label_hits, s.any_hits, s.all_found, s.extra_items) == (0, 0, False, 0)
    assert (s.gram_errors, s.weighed_unmatched, s.kcal_error_pct) == ((), 0, None)


def test_accuracy_over_a_set_counts_failed_calls_as_misses():
    failed = PhotoResult(EGGS, "error", "Gemini answered HTTP 500", seconds=0.5, attempts=2)
    a = accuracy([SCHABOWY_ANSWER, EGGS_ANSWER, failed], FACTS)

    assert (a.photos, a.answered, a.foods) == (3, 2, 7)
    assert (a.label_hits, a.any_hits, a.all_found, a.extra_items) == (3, 4, 1, 1)
    assert a.gram_n == 3
    assert a.gram_median_g == 20.0  # of 20, 0, 25
    assert a.gram_median_pct == 10.0  # of 10, 0, 50
    assert a.weighed_unmatched == 1
    assert a.kcal_n == 1
    assert a.kcal_median_pct == pytest.approx(100 * 64.75 / 284.5)


def test_latency_reports_timeouts_apart_from_errors_and_counts_every_slow_photo():
    results = [
        PhotoResult(EGGS, "ok", seconds=2.0),
        PhotoResult(EGGS, "ok", seconds=4.0),
        PhotoResult(EGGS, "ok", seconds=9.0),
        PhotoResult(EGGS, "timeout", seconds=10.2),
        PhotoResult(EGGS, "error", seconds=0.3),
        PhotoResult(EGGS, "invalid_image", seconds=0.01),
    ]
    lat = latency(results)
    assert (lat.total, lat.answered) == (6, 3)
    assert (lat.median, lat.p95, lat.max) == (4.0, 9.0, 9.0)
    assert (lat.over_nfr, lat.timeouts, lat.errors) == (1, 1, 2)


def test_tokens_and_cost_per_1000_scans():
    failed = PhotoResult(EGGS, "timeout", seconds=7.0, attempts=1)
    tok = tokens([SCHABOWY_ANSWER, EGGS_ANSWER, failed], "gemini-3.1-flash-lite")

    assert (tok.calls, tok.attempts) == (2, 3)
    assert (tok.prompt, tok.output, tok.thinking) == (4500.0, 250.0, 50.0)
    # 1000 * (4500 * 0.25 + (250 + 50) * 1.50) / 1e6
    assert tok.cost_per_1000 == pytest.approx(1.575)


def test_cost_per_1000_bills_thinking_as_output_and_knows_only_listed_models():
    assert cost_per_1000("gemini-3.1-flash-lite", 4000, 300, 100) == pytest.approx(1.6)
    assert cost_per_1000("gemini-3.5-flash-lite", 4000, 300, 100) == pytest.approx(2.2)
    assert cost_per_1000("gemini-3.8-flash", 4000, 300, 100) == pytest.approx(4.5)
    assert cost_per_1000("gemini-unknown", 4000, 300, 100) is None


def test_d05_checks_thresholds_latency_timeouts_and_production_budget():
    common = photo("c.jpg", "common", food("eggs, boiled"), food("rye bread"))
    common_ok = PhotoResult(common, "ok", seconds=3.0, items=[it("eggs, boiled", 100)])
    polish_ok = PhotoResult(EGGS, "ok", seconds=3.0, items=[it("eggs, boiled", 100)])
    results = [common_ok, polish_ok]
    by_set = {
        "common": summarise("common", [common_ok], FACTS, "m"),
        "polish": summarise("polish", [polish_ok], FACTS, "m"),
    }
    every = summarise("all", results, FACTS, "m")

    checks = {c.criterion: c for c in d05_checks(by_set, every, PRODUCTION_TIMEOUT_S)}
    # 1 of 2 foods found in each set: 50 % fails 80 % and 60 %
    assert not checks["common: label or alternatives hit >= 80%"].passed
    assert not checks["polish: label or alternatives hit >= 60%"].passed
    assert checks["p95 latency < 10 s (in-process)"].passed
    assert checks["timeouts <= 5% (at 7 s)"].passed
    assert checks["production budget GEMINI_TIMEOUT_S <= 7 s"].passed

    slow = [*results, PhotoResult(EGGS, "timeout", seconds=9.9)]
    every = summarise("all", slow, FACTS, "m")
    checks = {c.criterion: c for c in d05_checks(by_set, every, 9.9)}
    assert not checks["timeouts <= 5% (at 9.9 s)"].passed
    assert not checks["production budget GEMINI_TIMEOUT_S <= 7 s"].passed


# ---------------------------------------------------------------- recording the calls


def gemini_response(items: list[dict[str, Any]]) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model", parts=[types.Part(text=json.dumps({"items": items}))]
                ),
                finish_reason=types.FinishReason.STOP,
            )
        ],
        model_version="gemini-test-001",
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=4321,
            candidates_token_count=210,
            thoughts_token_count=12,
            cached_content_token_count=None,
        ),
    )


ANSWER_ITEMS = [
    {
        "label": "Eggs, boiled",
        "confidence": 0.9,
        "grams": 110,
        "alternatives": [{"label": "jajka", "confidence": 0.2}],
    },
    {"label": "żurek", "confidence": 0.7, "grams": 300, "alternatives": []},
]


class FakeModels:
    def __init__(self, answers: list[Any]) -> None:
        self.answers = answers
        self.calls = 0

    async def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
        self.calls += 1
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer


class FakeAio:
    def __init__(self, models: FakeModels) -> None:
        self.models = models
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


def fake_provider(settings, *answers: Any) -> tuple[GeminiProvider, FakeModels, FakeAio]:
    models = FakeModels(list(answers))
    aio = FakeAio(models)
    return GeminiProvider(settings, SimpleNamespace(aio=aio)), models, aio


def test_provider_keeps_its_client_where_record_calls_wraps_it():
    provider, _, _ = fake_provider(make_settings())
    assert hasattr(provider, "_client")
    record_calls(provider)
    assert type(provider._client).__name__ == "_RecordingClient"


def test_dropped_labels_are_those_outside_the_list_in_answer_order():
    text = json.dumps({"items": ANSWER_ITEMS})
    assert dropped_labels(text, ["eggs, boiled", "rye bread"]) == ["jajka", "żurek"]
    assert dropped_labels("not json", ["x"]) == []
    assert dropped_labels(None, ["x"]) == []


@pytest.mark.anyio
async def test_run_records_usage_attempts_and_dropped_labels_and_closes_the_client(tmp_path):
    (tmp_path / "a.jpg").write_bytes(make_photo())
    (tmp_path / "b.jpg").write_bytes(make_photo())
    (tmp_path / "c.jpg").write_bytes(b"not a photo")
    provider, models, aio = fake_provider(
        make_settings(),
        gemini_response(ANSWER_ITEMS),
        RuntimeError("connection reset"),
    )
    photos = [
        photo("a.jpg", "common", food("eggs, boiled")),
        photo("b.jpg", "gap"),
        photo("c.jpg", "common", food("apple")),
    ]

    # the second call raises from the client: the provider turns it into an error
    ok, failed, invalid = await run_photos(provider, photos, tmp_path, ["eggs, boiled"])

    assert ok.status == "ok"
    assert [i.label for i in ok.items] == ["eggs, boiled"]  # żurek is dropped by app/
    assert ok.model_version == "gemini-test-001"
    assert (ok.attempts, ok.prompt_tokens, ok.output_tokens, ok.thinking_tokens) == (
        1,
        4321,
        210,
        12,
    )
    assert ok.cached_tokens == 0
    assert ok.dropped == ["jajka", "żurek"]
    assert failed.status == "error"
    assert (failed.attempts, failed.prompt_tokens, failed.dropped) == (1, None, [])
    assert invalid.status == "invalid_image"
    assert invalid.attempts == 0
    assert models.calls == 2  # the unreadable photo is never sent
    assert aio.closed


# ---------------------------------------------------------------- command line


@pytest.fixture
def workspace(tmp_path):
    photos = tmp_path / "photos"
    photos.mkdir()
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        (photos / name).write_bytes(make_photo())
    manifest = write_manifest(
        tmp_path,
        'a.jpg,common,"eggs, boiled",110,own\n'
        'b.jpg,polish,"potatoes, boiled|mashed potatoes;breaded pork cutlet",,own\n'
        "c.jpg,gap,żurek,,own\n",
    )
    return SimpleNamespace(root=tmp_path, photos=photos, manifest=manifest, out=tmp_path / "out")


class Factories:
    """main() with test settings, a fake provider and a scripted answer to the prompt."""

    def __init__(self, *answers: Any, reply: str = "y") -> None:
        self.answers = answers
        self.reply = reply
        self.settings: list[Any] = []
        self.prompts: list[str] = []
        self.providers = 0

    def settings_factory(self, **overrides: Any):
        settings = make_settings(**overrides)
        self.settings.append(settings)
        return settings

    def provider_factory(self, settings):
        self.providers += 1
        provider, _, _ = fake_provider(settings, *self.answers)
        return provider

    def input_fn(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.reply

    def run(self, ws, *args: str) -> int:
        argv = [
            "--manifest",
            str(ws.manifest),
            "--photos",
            str(ws.photos),
            "--out-dir",
            str(ws.out),
            *args,
        ]
        return main(
            argv,
            settings_factory=self.settings_factory,
            provider_factory=self.provider_factory,
            input_fn=self.input_fn,
        )


def ok_answer() -> types.GenerateContentResponse:
    return gemini_response(
        [{"label": "eggs, boiled", "confidence": 0.9, "grams": 100, "alternatives": []}]
    )


def test_main_runs_after_confirmation_and_writes_one_row_per_photo(workspace, capsys):
    f = Factories(ok_answer(), ok_answer(), ok_answer())

    assert f.run(workspace, "--model", "gemini-3.1-flash-lite", "--resolution", "high") == 0

    assert f.prompts == ["Send 3 billed Gemini calls? [y/N] "]
    path = workspace.out / "gemini-3.1-flash-lite_high.csv"
    with path.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    assert [r["photo"] for r in rows] == ["a.jpg", "b.jpg", "c.jpg"]
    assert rows[0]["status"] == "ok"
    assert (rows[0]["label_hits"], rows[0]["any_hits"], rows[0]["foods"]) == ("1", "1", "1")
    assert json.loads(rows[0]["items"])[0]["label"] == "eggs, boiled"
    assert rows[0]["prompt_tokens"] == "4321"
    out = capsys.readouterr().out
    assert "3 photos (1 common, 1 polish, 1 gap)" in out
    assert "== common (1 photos) ==" in out
    assert "== polish (1 photos) ==" in out
    assert "== gap: what came back for dishes with no label ==" in out
    assert "== D-05 ==" in out
    assert TEST_KEY not in out


def test_main_with_yes_does_not_ask(workspace):
    f = Factories(ok_answer(), ok_answer(), ok_answer())
    assert f.run(workspace, "--yes") == 0
    assert f.prompts == []
    assert f.providers == 1


@pytest.mark.parametrize("reply", ["", "n", "no", "maybe"])
def test_main_without_a_yes_sends_nothing(workspace, capsys, reply):
    f = Factories(reply=reply)
    assert f.run(workspace) == 1
    assert f.providers == 0
    assert "nothing was sent" in capsys.readouterr().out


def test_main_refuses_more_photos_than_the_limit_before_asking(workspace, capsys):
    f = Factories()
    assert f.run(workspace, "--limit", "2") == 2
    assert (f.prompts, f.providers) == ([], 0)
    assert "3 photos is more than --limit 2 billed calls" in capsys.readouterr().err


def test_main_first_n_sends_only_the_first_photos(workspace):
    f = Factories(ok_answer())
    assert f.run(workspace, "--first", "1", "--limit", "1", "--yes", "--tag", "dry") == 0
    rows = (workspace.out / "gemini-test_medium_dry.csv").read_text(encoding="utf-8")
    assert rows.count("\n") == 2  # header and one photo


def test_main_stops_on_unknown_labels_before_any_call(workspace, capsys):
    workspace.manifest.write_text(
        HEADER + "a.jpg,polish,schabowy;kopytka|potato gnocchi,,own\n", encoding="utf-8"
    )
    f = Factories()
    assert f.run(workspace, "--yes") == 2
    assert f.providers == 0
    err = capsys.readouterr().err
    assert "2 expected label(s) are not in food_item.csv" in err
    assert "kopytka" in err and "schabowy" in err


def test_main_stops_on_a_missing_photo(workspace, capsys):
    (workspace.photos / "b.jpg").unlink()
    f = Factories()
    assert f.run(workspace, "--yes") == 2
    assert f.providers == 0
    assert "b.jpg" in capsys.readouterr().err


def test_main_never_overwrites_a_result_without_overwrite(workspace, capsys):
    workspace.out.mkdir()
    (workspace.out / "gemini-test_medium.csv").write_text("old", encoding="utf-8")
    f = Factories()
    assert f.run(workspace, "--yes") == 2
    assert f.providers == 0
    assert "use --overwrite or --tag" in capsys.readouterr().err


def test_main_without_a_key_sends_nothing(workspace, capsys):
    f = Factories()
    original = f.settings_factory
    f.settings_factory = lambda **kw: original(**kw, gemini_api_key="")  # type: ignore[method-assign]
    assert f.run(workspace, "--yes") == 1
    assert f.providers == 0
    assert "GEMINI_API_KEY or GEMINI_MODEL is not set" in capsys.readouterr().err


def test_main_passes_the_overrides_to_the_settings(workspace):
    f = Factories(ok_answer(), ok_answer(), ok_answer())
    args = ["--model", "gemini-3.8-flash", "--resolution", "low", "--thinking", "low"]
    assert f.run(workspace, *args, "--timeout", "9.9", "--yes") == 0
    (settings,) = f.settings
    assert settings.gemini_model == "gemini-3.8-flash"
    assert settings.gemini_media_resolution == "low"
    assert settings.gemini_thinking_level == "low"
    assert settings.gemini_timeout_s == 9.9


def test_main_refuses_a_timeout_of_10_s(workspace, capsys):
    f = Factories()
    with pytest.raises(SystemExit) as raised:
        f.run(workspace, "--timeout", "10", "--yes")
    assert raised.value.code == 2
    assert "gemini_timeout_s" in capsys.readouterr().err
    assert f.providers == 0


def test_result_path_is_model_and_resolution_with_an_optional_tag(tmp_path):
    assert result_path(tmp_path, "gemini-3.1-flash-lite", "medium", None).name == (
        "gemini-3.1-flash-lite_medium.csv"
    )
    assert (
        result_path(tmp_path, "models/x y", "high", "repeat").name == "models-x-y_high_repeat.csv"
    )


def test_compare_reports_photos_whose_labels_differ(tmp_path, capsys):
    def write(name: str, rows: list[tuple[str, str, list[dict[str, Any]]]]) -> Path:
        path = tmp_path / name
        with path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=["photo", "status", "items"])
            writer.writeheader()
            for photo_name, status, items in rows:
                writer.writerow({"photo": photo_name, "status": status, "items": json.dumps(items)})
        return path

    def items(*labels: str, alt: str | None = None) -> list[dict[str, Any]]:
        alts = [{"label": alt, "confidence": 0.1}] if alt else []
        return [{"label": lbl, "alternatives": alts} for lbl in labels]

    a = write(
        "a.csv",
        [
            ("1.jpg", "ok", items("apple", "banana")),
            ("2.jpg", "ok", items("pierogi", alt="steamed dumplings")),
            ("3.jpg", "ok", items("goulash")),
            ("4.jpg", "timeout", []),
        ],
    )
    b = write(
        "b.csv",
        [
            ("1.jpg", "ok", items("banana", "apple")),  # order does not matter
            ("2.jpg", "ok", items("pierogi", alt="potato gnocchi")),
            ("3.jpg", "ok", items("beef stew")),
            ("4.jpg", "ok", items("apple")),  # not answered in a: not compared
        ],
    )

    report = compare(a, b)

    assert "3.jpg: ['goulash'] != ['beef stew']" in report
    assert "2.jpg: same labels, different alternatives" in report
    assert "same labels 2/3, same labels and alternatives 1/3" in report
    assert main(["--compare", str(a), str(b)]) == 0
    assert "same labels 2/3" in capsys.readouterr().out


@pytest.mark.anyio
async def test_a_refused_request_keeps_googles_message_in_the_result(tmp_path):
    (tmp_path / "a.jpg").write_bytes(make_photo())
    body = {
        "error": {
            "code": 400,
            "message": "Thinking level  MINIMAL\n is not supported",
            "status": "INVALID_ARGUMENT",
        }
    }
    provider, models, _ = fake_provider(make_settings(), genai_errors.ClientError(400, body))

    (result,) = await run_photos(
        provider, [photo("a.jpg", "common", food("apple"))], tmp_path, ["apple"]
    )

    assert result.status == "error"
    # whitespace collapsed; app/ itself still logs only the status
    assert result.error == "Gemini answered HTTP 400: Thinking level MINIMAL is not supported"
    assert (result.attempts, models.calls) == (1, 1)  # a 400 is never retried


def test_cost_line_tells_no_answer_apart_from_a_model_without_a_price():
    failed = PhotoResult(EGGS, "error", "Gemini answered HTTP 400", seconds=0.3, attempts=1)
    refused = format_set(summarise("common", [failed], FACTS, "gemini-3.8-flash"), scored=True)
    assert "no token data (no call answered)" in refused
    assert "no price" not in refused

    unpriced = format_set(summarise("common", [EGGS_ANSWER], FACTS, "gemini-x"), scored=True)
    assert "no price for this model" in unpriced
