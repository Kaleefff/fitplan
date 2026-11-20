"""D-05 Gemini feasibility: accuracy, grams, latency and tokens on a photo set. COSTS MONEY.

Every photo is one billed Gemini call (paid tier, D25); CI never runs this script. It runs
in-process with the code of POST /predict: prepare_photo, then GeminiProvider.from_settings
with the settings of the repository `.env`, overridden by --model, --resolution, --thinking
and --timeout. Run it from ai-service/ as a module (it imports app/):

    uv run python -m scripts.evaluate [--model M] [--resolution medium] [--first 3]

Input: eval/manifest.csv with the columns photo, set, expected, grams, source.
- photo: a file name in eval/photos/ (not committed: privacy, licences, size)
- set: common, polish or gap
- expected: the foods on the plate separated by ";"; a food may accept several labels
  separated by "|" (the first is the true food, used for its kcal). For the gap set
  (dishes with no label) it is the dish name in free text and is not scored.
- grams: the weighed grams aligned with expected, ";"-separated, blank when not weighed
- source: "own" or the Wikimedia Commons URL
Other columns (the template's `note`: which meals to weigh, how to plate them) are ignored.

Before any call: the manifest is checked, every expected label must be lower(name) of a
row of database/seed/food_item.csv (as measure_latency.py builds the labels), every photo
must exist, at most --limit photos (default 80) are sent, an existing result is not
overwritten without --overwrite, and the run asks for confirmation unless --yes.

Output: eval/results/<model>_<resolution>[_<tag>].csv, one row per photo, and a summary
per set: label hit, label or alternatives hit (D-05: >= 80 % common, >= 60 % polish),
all foods found, extra items, gram and kcal error, latency, tokens and the cost per 1000
scans. The labels the model returned outside the list ("dropped") go to the CSV only,
never to the console or a log. `--compare A.csv B.csv` compares the labels of two
result files (the temperature-0 repeat check) and calls nothing.

Latency is prepare_photo plus the Gemini call, in-process: the upload over 4G and the
backend hop are not included (T-04). The key is never read or printed by this script.
"""

import argparse
import asyncio
import csv
import json
import re
import statistics
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from google.genai import errors as genai_errors
from pydantic import ValidationError

from app.config import NFR_PERF_SECONDS, Settings
from app.gemini import GeminiProvider, normalise
from app.image import InvalidImageError, prepare_photo
from app.provider import ProviderError, ProviderTimeoutError
from app.schemas import Item
from scripts.measure_latency import DEFAULT_CSV, load_labels, p95

EVAL_DIR = Path(__file__).resolve().parents[1] / "eval"
DEFAULT_MANIFEST = EVAL_DIR / "manifest.csv"
DEFAULT_PHOTOS = EVAL_DIR / "photos"
DEFAULT_RESULTS = EVAL_DIR / "results"
DEFAULT_LIMIT = 80
API_ERROR_CHARS = 300  # Google's error message, as kept in the result file

MANIFEST_COLUMNS = ("photo", "set", "expected", "grams", "source")
SETS = ("common", "polish", "gap")
SCORED_SETS = ("common", "polish")
# D-05 (tasks.md): the label or its alternatives hold the correct food this often
THRESHOLDS = {"common": 0.80, "polish": 0.60}
# D-05 latency, agreed for this evaluation: p95 below NFR_PERF_SECONDS, timeouts <= 5 %
MAX_TIMEOUT_SHARE = 0.05
# the production budget: only a model that meets it can be chosen (--timeout above it
# makes the run a quality reference only)
PRODUCTION_TIMEOUT_S = Settings.model_fields["gemini_timeout_s"].default

# USD per 1M tokens (input, output); thinking tokens are billed as output. Checked on
# 2026-11-11 on the Gemini API pricing page (paid tier, text and image input).
PRICES_CHECKED = "2026-11-11"
PRICES_USD_PER_1M: dict[str, tuple[float, float]] = {
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.8-flash": (0.75, 3.75),
}

RESULT_COLUMNS = (
    "photo",
    "set",
    "expected",
    "grams",
    "status",
    "error",
    "seconds",
    "attempts",
    "model_version",
    "prompt_tokens",
    "output_tokens",
    "thinking_tokens",
    "cached_tokens",
    "foods",
    "label_hits",
    "any_hits",
    "extra_items",
    "items",
    "dropped",
)


# ---------------------------------------------------------------- manifest


class ManifestError(Exception):
    """The manifest cannot be used; the message lists every problem."""


@dataclass(frozen=True)
class Food:
    labels: tuple[str, ...]  # accepted labels, normalised; the first is the true food
    grams: float | None  # weighed grams, None when not weighed


@dataclass(frozen=True)
class Photo:
    photo: str
    set: str
    expected: str  # as written in the manifest
    grams: str  # as written in the manifest
    source: str
    foods: tuple[Food, ...]  # empty for the gap set


def parse_manifest(path: Path) -> list[Photo]:
    """The rows of the manifest; ManifestError with every problem found."""
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        missing = [c for c in MANIFEST_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ManifestError(f"{path.name}: missing columns {', '.join(missing)}")
        rows = list(reader)

    photos: list[Photo] = []
    problems: list[str] = []
    seen: set[str] = set()
    for line, row in enumerate(rows, start=2):
        values = {c: (row.get(c) or "").strip() for c in MANIFEST_COLUMNS}
        if not any(values.values()):
            continue  # a blank line
        row_problems: list[str] = []
        name = values["photo"]
        if not name:
            row_problems.append("photo is blank")
        elif name in seen:
            row_problems.append(f"photo {name} is listed twice")
        seen.add(name)
        if values["set"] not in SETS:
            row_problems.append(f"set must be one of {', '.join(SETS)}")
        foods: tuple[Food, ...] = ()
        if values["set"] in SCORED_SETS:
            foods = _parse_foods(values["expected"], values["grams"], row_problems)
        problems.extend(f"line {line}: {p}" for p in row_problems)
        if not row_problems:
            photos.append(
                Photo(
                    photo=name,
                    set=values["set"],
                    expected=values["expected"],
                    grams=values["grams"],
                    source=values["source"],
                    foods=foods,
                )
            )
    if problems:
        raise ManifestError("\n".join(problems))
    return photos


def _parse_foods(expected: str, grams: str, problems: list[str]) -> tuple[Food, ...]:
    if not expected:
        problems.append("expected is blank")
        return ()
    label_groups = []
    for food in expected.split(";"):
        labels = tuple(dict.fromkeys(normalise(lbl) for lbl in food.split("|") if lbl.strip()))
        if not labels:
            problems.append(f"expected has an empty food: {expected!r}")
            return ()
        label_groups.append(labels)

    weights: list[float | None] = [None] * len(label_groups)
    if grams:
        parts = grams.split(";")
        if len(parts) != len(label_groups):
            problems.append(f"grams has {len(parts)} entries, expected has {len(label_groups)}")
            return ()
        for i, part in enumerate(parts):
            if not part.strip():
                continue
            try:
                value = float(part)
            except ValueError:
                problems.append(f"grams entry {part.strip()!r} is not a number")
                return ()
            if not value > 0:
                problems.append(f"grams entry {part.strip()!r} is not above 0")
                return ()
            weights[i] = value
    return tuple(Food(labels, g) for labels, g in zip(label_groups, weights, strict=True))


def unknown_labels(photos: Sequence[Photo], labels: Sequence[str]) -> list[str]:
    """Expected labels that are not recognition labels, sorted."""
    known = {normalise(label) for label in labels}
    return sorted(
        {lbl for p in photos for food in p.foods for lbl in food.labels if lbl not in known}
    )


@dataclass(frozen=True)
class FoodFacts:
    kcal_per_100g: float
    default_portion_g: float


def load_food_facts(path: Path) -> dict[str, FoodFacts]:
    """cals_per_100g and default_portion_g by label (lower(name), first row wins)."""
    facts: dict[str, FoodFacts] = {}
    with path.open(encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            facts.setdefault(
                row["name"].lower(),
                FoodFacts(float(row["cals_per_100g"]), float(row["default_portion_g"])),
            )
    return facts


# ---------------------------------------------------------------- recording the calls


@dataclass
class CallRecord:
    """What the Gemini client saw during one photo; never logged."""

    attempts: int = 0
    usage: Any = None  # usage_metadata of the last response
    text: str | None = None  # the raw answer, only to find the dropped labels
    # Google's message of the last HTTP error: app/ logs only the status, but a refused
    # setting (HTTP 400) is undiagnosable without it. It never holds the key or an answer.
    api_error: str | None = None


class Recorder:
    def __init__(self) -> None:
        self.current = CallRecord()

    def start(self) -> CallRecord:
        self.current = CallRecord()
        return self.current


class _RecordingModels:
    def __init__(self, models: Any, recorder: Recorder) -> None:
        self._models = models
        self._recorder = recorder

    async def generate_content(self, **kwargs: Any) -> Any:
        record = self._recorder.current
        record.attempts += 1
        try:
            response = await self._models.generate_content(**kwargs)
        except genai_errors.APIError as error:
            message = " ".join(str(error.message or error.status or "").split())
            record.api_error = message[:API_ERROR_CHARS] or None
            raise
        record.usage = response.usage_metadata
        try:
            record.text = response.text
        except Exception:  # an answer the provider rejects anyway
            record.text = None
        return response


class _RecordingAio:
    def __init__(self, aio: Any, recorder: Recorder) -> None:
        self._aio = aio
        self.models = _RecordingModels(aio.models, recorder)

    async def aclose(self) -> None:
        await self._aio.aclose()


class _RecordingClient:
    def __init__(self, client: Any, recorder: Recorder) -> None:
        self.aio = _RecordingAio(client.aio, recorder)


def record_calls(provider: GeminiProvider) -> Recorder:
    """Wrap the provider's Gemini client so every call's usage and answer are recorded.

    GeminiProvider keeps its client in `_client` (app/gemini.py); a test fails if that
    changes, so the evaluation never silently runs without recording.
    """
    recorder = Recorder()
    provider._client = _RecordingClient(provider._client, recorder)
    return recorder


def dropped_labels(text: str | None, labels: Sequence[str]) -> list[str]:
    """Item and alternative labels of the raw answer that are not in the list."""
    if not text:
        return []
    try:
        answer = json.loads(text)
    except ValueError:
        return []
    known = {normalise(label) for label in labels}
    found: list[str] = []
    raw_items = answer.get("items") if isinstance(answer, dict) else None
    for item in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(item, dict):
            continue
        alternatives = item.get("alternatives")
        candidates = [item.get("label")] + [
            alt.get("label") for alt in alternatives or [] if isinstance(alt, dict)
        ]
        for label in candidates:
            if isinstance(label, str) and label.strip() and normalise(label) not in known:
                found.append(label.strip())
    return list(dict.fromkeys(found))


# ---------------------------------------------------------------- running


@dataclass
class PhotoResult:
    photo: Photo
    status: str  # ok, timeout, error or invalid_image
    error: str = ""
    seconds: float = 0.0
    items: list[Item] = field(default_factory=list)
    model_version: str = ""
    attempts: int = 0
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    thinking_tokens: int | None = None
    cached_tokens: int | None = None
    dropped: list[str] = field(default_factory=list)


async def evaluate_photo(
    provider: GeminiProvider,
    recorder: Recorder,
    photo: Photo,
    data: bytes,
    labels: Sequence[str],
    clock: Callable[[], float] = time.perf_counter,
) -> PhotoResult:
    record = recorder.start()
    started = clock()
    result = PhotoResult(photo, "ok")
    try:
        prepared = prepare_photo(data)
        prediction = await provider.recognise(prepared.jpeg, labels)
        result.items = prediction.items
        result.model_version = prediction.model.version
    except InvalidImageError as error:
        result.status, result.error = "invalid_image", str(error)
    except ProviderTimeoutError as error:
        result.status, result.error = "timeout", str(error)
    except ProviderError as error:
        result.status, result.error = "error", str(error)
        if record.api_error:
            result.error += f": {record.api_error}"
    result.seconds = clock() - started
    result.attempts = record.attempts
    usage = record.usage
    if usage is not None:
        result.prompt_tokens = usage.prompt_token_count or 0
        result.output_tokens = usage.candidates_token_count or 0
        result.thinking_tokens = usage.thoughts_token_count or 0
        result.cached_tokens = usage.cached_content_token_count or 0
    result.dropped = dropped_labels(record.text, labels)
    return result


async def run_photos(
    provider: GeminiProvider,
    photos: Sequence[Photo],
    photo_dir: Path,
    labels: Sequence[str],
) -> list[PhotoResult]:
    recorder = record_calls(provider)
    results = []
    try:
        for photo in photos:
            data = (photo_dir / photo.photo).read_bytes()
            result = await evaluate_photo(provider, recorder, photo, data, labels)
            print(describe(result), flush=True)
            results.append(result)
    finally:
        await provider.aclose()
    return results


def describe(result: PhotoResult) -> str:
    head = f"{result.photo.photo:<28} {result.photo.set:<6} {result.seconds:6.2f} s"
    if result.status != "ok":
        return f"{head}  {result.status}: {result.error}"
    if not result.items:
        return f"{head}  (no items)"
    parts = []
    for item in result.items:
        grams = "?" if item.grams is None else f"{item.grams:g} g"
        parts.append(f"{item.label} {item.confidence:.2f} {grams}")
    return f"{head}  " + " | ".join(parts)


# ---------------------------------------------------------------- scoring


@dataclass(frozen=True)
class Score:
    foods: int
    label_hits: int  # expected foods an item's label matches
    any_hits: int  # expected foods an item's label or one of its alternatives matches
    all_found: bool  # every expected food has a label or alternatives hit
    extra_items: int  # items whose label and alternatives match no expected food
    gram_errors: tuple[tuple[float, float], ...]  # (|error| g, |error| %) per weighed food
    weighed_unmatched: int  # weighed foods no item's label matches (no gram error)
    kcal_error_pct: float | None  # |error| % of the meal when every food was weighed


def item_grams(item: Item, facts: dict[str, FoodFacts]) -> float:
    """The model's grams, or the label's default portion (algorithms.md 11)."""
    if item.grams is not None:
        return item.grams
    known = facts.get(normalise(item.label))
    return known.default_portion_g if known else 0.0


def score(result: PhotoResult, facts: dict[str, FoodFacts]) -> Score:
    foods = result.photo.foods
    items = result.items  # empty unless the call succeeded
    item_labels = [normalise(i.label) for i in items]
    item_alts = [{normalise(a.label) for a in i.alternatives} for i in items]

    label_hits = any_hits = 0
    for food in foods:
        accepted = set(food.labels)
        by_label = any(label in accepted for label in item_labels)
        by_alt = any(alts & accepted for alts in item_alts)
        label_hits += by_label
        any_hits += by_label or by_alt

    every_label = {label for food in foods for label in food.labels}
    extra = sum(
        label not in every_label and not (alts & every_label)
        for label, alts in zip(item_labels, item_alts, strict=True)
    )

    gram_errors: list[tuple[float, float]] = []
    weighed_unmatched = 0
    kcal_error: float | None = None
    if result.status == "ok":
        for food in foods:
            if food.grams is None:
                continue
            matching = [i for i, lbl in zip(items, item_labels, strict=True) if lbl in food.labels]
            if not matching:
                weighed_unmatched += 1
                continue
            estimate = sum(item_grams(i, facts) for i in matching)
            error = abs(estimate - food.grams)
            gram_errors.append((error, 100 * error / food.grams))
        if foods and all(food.grams is not None for food in foods):
            true_kcal = sum(
                food.grams * facts[food.labels[0]].kcal_per_100g / 100
                for food in foods
                if food.grams is not None
            )
            # each item's own label, never its alternatives; extras included
            estimate_kcal = sum(
                item_grams(i, facts) * facts[lbl].kcal_per_100g / 100
                for i, lbl in zip(items, item_labels, strict=True)
                if lbl in facts
            )
            if true_kcal > 0:
                kcal_error = 100 * abs(estimate_kcal - true_kcal) / true_kcal

    return Score(
        foods=len(foods),
        label_hits=label_hits,
        any_hits=any_hits,
        all_found=bool(foods) and any_hits == len(foods),
        extra_items=extra,
        gram_errors=tuple(gram_errors),
        weighed_unmatched=weighed_unmatched,
        kcal_error_pct=kcal_error,
    )


# ---------------------------------------------------------------- summary


@dataclass(frozen=True)
class Latency:
    total: int
    answered: int
    median: float | None  # over the answered photos
    p95: float | None
    max: float | None
    over_nfr: int  # every photo, answered or not, slower than NFR_PERF_SECONDS
    timeouts: int
    errors: int  # every other failure


@dataclass(frozen=True)
class Tokens:
    calls: int  # photos with usage metadata
    attempts: int  # Gemini requests sent (billed calls; a fast 429/5xx retry adds one)
    prompt: float | None
    output: float | None
    thinking: float | None
    cost_per_1000: float | None  # USD, None for a model without a price


@dataclass(frozen=True)
class Accuracy:
    photos: int
    foods: int
    label_hits: int
    any_hits: int
    all_found: int
    extra_items: int
    answered: int
    gram_n: int
    gram_median_g: float | None
    gram_median_pct: float | None
    weighed_unmatched: int
    kcal_n: int
    kcal_median_pct: float | None


@dataclass(frozen=True)
class SetSummary:
    name: str
    accuracy: Accuracy
    latency: Latency
    tokens: Tokens


def _median(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


def _mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def cost_per_1000(model: str, prompt: float, output: float, thinking: float) -> float | None:
    price = PRICES_USD_PER_1M.get(model)
    if price is None:
        return None
    input_usd, output_usd = price
    return 1000 * (prompt * input_usd + (output + thinking) * output_usd) / 1_000_000


def latency(results: Sequence[PhotoResult]) -> Latency:
    times = [r.seconds for r in results if r.status == "ok"]
    return Latency(
        total=len(results),
        answered=len(times),
        median=_median(times),
        p95=p95(times) if times else None,
        max=max(times) if times else None,
        over_nfr=sum(r.seconds > NFR_PERF_SECONDS for r in results),
        timeouts=sum(r.status == "timeout" for r in results),
        errors=sum(r.status not in ("ok", "timeout") for r in results),
    )


def tokens(results: Sequence[PhotoResult], model: str) -> Tokens:
    used = [r for r in results if r.prompt_tokens is not None]
    prompt = _mean([r.prompt_tokens or 0 for r in used])
    output = _mean([r.output_tokens or 0 for r in used])
    thinking = _mean([r.thinking_tokens or 0 for r in used])
    cost = None
    if prompt is not None and output is not None and thinking is not None:
        cost = cost_per_1000(model, prompt, output, thinking)
    return Tokens(
        calls=len(used),
        attempts=sum(r.attempts for r in results),
        prompt=prompt,
        output=output,
        thinking=thinking,
        cost_per_1000=cost,
    )


def accuracy(results: Sequence[PhotoResult], facts: dict[str, FoodFacts]) -> Accuracy:
    """A failed call counts as a photo where nothing was found."""
    scores = [score(r, facts) for r in results]
    gram_errors = [e for s in scores for e in s.gram_errors]
    kcal = [s.kcal_error_pct for s in scores if s.kcal_error_pct is not None]
    return Accuracy(
        photos=len(results),
        foods=sum(s.foods for s in scores),
        label_hits=sum(s.label_hits for s in scores),
        any_hits=sum(s.any_hits for s in scores),
        all_found=sum(s.all_found for s in scores),
        extra_items=sum(s.extra_items for s in scores),
        answered=sum(r.status == "ok" for r in results),
        gram_n=len(gram_errors),
        gram_median_g=_median([g for g, _ in gram_errors]),
        gram_median_pct=_median([p for _, p in gram_errors]),
        weighed_unmatched=sum(s.weighed_unmatched for s in scores),
        kcal_n=len(kcal),
        kcal_median_pct=_median(kcal),
    )


def summarise(
    name: str, results: Sequence[PhotoResult], facts: dict[str, FoodFacts], model: str
) -> SetSummary:
    return SetSummary(name, accuracy(results, facts), latency(results), tokens(results, model))


@dataclass(frozen=True)
class Check:
    criterion: str
    value: str
    passed: bool


def d05_checks(by_set: dict[str, SetSummary], every: SetSummary, timeout_s: float) -> list[Check]:
    checks = []
    for name, threshold in THRESHOLDS.items():
        summary = by_set.get(name)
        if summary is None or not summary.accuracy.foods:
            continue
        share = summary.accuracy.any_hits / summary.accuracy.foods
        checks.append(
            Check(
                f"{name}: label or alternatives hit >= {threshold:.0%}",
                _pct(share),
                share >= threshold,
            )
        )
    lat = every.latency
    checks.append(
        Check(
            f"p95 latency < {NFR_PERF_SECONDS:g} s (in-process)",
            "-" if lat.p95 is None else f"{lat.p95:.2f} s",
            lat.p95 is not None and lat.p95 < NFR_PERF_SECONDS,
        )
    )
    share = lat.timeouts / lat.total if lat.total else 0.0
    checks.append(
        Check(
            f"timeouts <= {MAX_TIMEOUT_SHARE:.0%} (at {timeout_s:g} s)",
            f"{lat.timeouts}/{lat.total}",
            share <= MAX_TIMEOUT_SHARE,
        )
    )
    checks.append(
        Check(
            f"production budget GEMINI_TIMEOUT_S <= {PRODUCTION_TIMEOUT_S:g} s",
            f"{timeout_s:g} s",
            timeout_s <= PRODUCTION_TIMEOUT_S,
        )
    )
    return checks


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{100 * value:.1f} %"


def _share(part: int, whole: int) -> str:
    return f"{part}/{whole}  " + (_pct(part / whole) if whole else "-")


def _num(value: float | None, unit: str = "", digits: int = 1) -> str:
    return "-" if value is None else f"{value:.{digits}f}{unit}"


def format_set(summary: SetSummary, scored: bool) -> str:
    lines = [f"== {summary.name} ({summary.latency.total} photos) =="]
    a = summary.accuracy
    if scored:
        threshold = THRESHOLDS.get(summary.name)
        target = f"  (D-05 >= {threshold:.0%})" if threshold else ""
        extra = a.extra_items / a.answered if a.answered else None
        lines += [
            f"label hit                  {_share(a.label_hits, a.foods)}",
            f"label or alternatives hit  {_share(a.any_hits, a.foods)}{target}",
            f"all foods found            {_share(a.all_found, a.photos)}",
            f"extra items per photo      {_num(extra, digits=2)}  ({a.extra_items} in total)",
            f"gram error, weighed foods  median {_num(a.gram_median_g, ' g')}, "
            f"{_num(a.gram_median_pct, ' %')}  (n={a.gram_n}; "
            f"{a.weighed_unmatched} weighed foods without a label match)",
            f"kcal error, weighed meals  median {_num(a.kcal_median_pct, ' %')}  (n={a.kcal_n})",
        ]
    lat = summary.latency
    lines.append(
        f"latency (answered {lat.answered})  median {_num(lat.median, ' s', 2)}  "
        f"p95 {_num(lat.p95, ' s', 2)}  max {_num(lat.max, ' s', 2)}  "
        f"over {NFR_PERF_SECONDS:g} s: {lat.over_nfr}  timeouts: {lat.timeouts}  "
        f"errors: {lat.errors}"
    )
    tok = summary.tokens
    if not tok.calls:
        cost = "no token data (no call answered)"
    elif tok.cost_per_1000 is None:
        cost = "no price for this model"
    else:
        cost = f"${tok.cost_per_1000:.2f} per 1000 scans (prices of {PRICES_CHECKED})"
    lines.append(
        f"tokens (mean of {tok.calls})  prompt {_num(tok.prompt, digits=0)}  "
        f"output {_num(tok.output, digits=0)}  thinking {_num(tok.thinking, digits=0)}  "
        f"-> {cost}; {tok.attempts} Gemini requests"
    )
    return "\n".join(lines)


def format_gap(results: Sequence[PhotoResult]) -> str:
    lines = ["== gap: what came back for dishes with no label =="]
    for r in results:
        if r.status != "ok":
            returned = r.status
        else:
            returned = ", ".join(i.label for i in r.items) or "(no items)"
        dropped = (
            f"  [{len(r.dropped)} label(s) outside the list, see the CSV]" if r.dropped else ""
        )
        lines.append(f"{r.photo.photo} ({r.photo.expected}): {returned}{dropped}")
    return "\n".join(lines)


def format_report(
    results: Sequence[PhotoResult], facts: dict[str, FoodFacts], model: str, timeout_s: float
) -> str:
    by_set = {
        name: summarise(name, [r for r in results if r.photo.set == name], facts, model)
        for name in SETS
        if any(r.photo.set == name for r in results)
    }
    every = summarise("all photos", results, facts, model)
    parts = [format_set(by_set[name], scored=True) for name in SCORED_SETS if name in by_set]
    parts.append(format_set(every, scored=False))
    gap = [r for r in results if r.photo.set == "gap"]
    if gap:
        parts.append(format_gap(gap))
    checks = d05_checks(by_set, every, timeout_s)
    lines = ["== D-05 =="]
    lines += [f"{'pass' if c.passed else 'FAIL'}  {c.criterion}: {c.value}" for c in checks]
    if timeout_s > PRODUCTION_TIMEOUT_S:
        lines.append(
            f"note: --timeout {timeout_s:g} s is above the production {PRODUCTION_TIMEOUT_S:g} s; "
            "this run is a quality reference only"
        )
    parts.append("\n".join(lines))
    return "\n\n".join(parts)


# ---------------------------------------------------------------- result files


def result_path(out_dir: Path, model: str, resolution: str, tag: str | None) -> Path:
    stem = f"{model}_{resolution}" + (f"_{tag}" if tag else "")
    return out_dir / (re.sub(r"[^A-Za-z0-9._-]", "-", stem) + ".csv")


def write_results(path: Path, results: Sequence[PhotoResult], facts: dict[str, FoodFacts]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=RESULT_COLUMNS)
        writer.writeheader()
        for r in results:
            s = score(r, facts)
            writer.writerow(
                {
                    "photo": r.photo.photo,
                    "set": r.photo.set,
                    "expected": r.photo.expected,
                    "grams": r.photo.grams,
                    "status": r.status,
                    "error": r.error,
                    "seconds": f"{r.seconds:.3f}",
                    "attempts": r.attempts,
                    "model_version": r.model_version,
                    "prompt_tokens": _blank(r.prompt_tokens),
                    "output_tokens": _blank(r.output_tokens),
                    "thinking_tokens": _blank(r.thinking_tokens),
                    "cached_tokens": _blank(r.cached_tokens),
                    "foods": s.foods,
                    "label_hits": s.label_hits,
                    "any_hits": s.any_hits,
                    "extra_items": s.extra_items,
                    "items": json.dumps([i.model_dump() for i in r.items], ensure_ascii=False),
                    "dropped": json.dumps(r.dropped, ensure_ascii=False),
                }
            )


def _blank(value: int | None) -> str | int:
    return "" if value is None else value


def read_item_labels(path: Path) -> dict[str, tuple[list[str], list[str]]]:
    """photo -> (sorted item labels, sorted item and alternative labels) of a result file."""
    out = {}
    with path.open(encoding="utf-8", newline="") as file:
        for row in csv.DictReader(file):
            if row["status"] != "ok":
                continue
            items = json.loads(row["items"])
            labels = sorted(i["label"] for i in items)
            candidates = sorted(
                [i["label"] for i in items] + [a["label"] for i in items for a in i["alternatives"]]
            )
            out[row["photo"]] = (labels, candidates)
    return out


def compare(a: Path, b: Path) -> str:
    """Whether the photos answered in both files got the same labels (and candidates)."""
    first, second = read_item_labels(a), read_item_labels(b)
    shared = [photo for photo in first if photo in second]
    lines = []
    same_labels = same_candidates = 0
    for photo in shared:
        (labels_a, cand_a), (labels_b, cand_b) = first[photo], second[photo]
        same_labels += labels_a == labels_b
        same_candidates += cand_a == cand_b
        if labels_a != labels_b:
            lines.append(f"{photo}: {labels_a} != {labels_b}")
        elif cand_a != cand_b:
            lines.append(f"{photo}: same labels, different alternatives")
    lines.append(
        f"same labels {same_labels}/{len(shared)}, same labels and alternatives "
        f"{same_candidates}/{len(shared)} (photos answered in both files)"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------- command line


def main(
    argv: Sequence[str] | None = None,
    *,
    settings_factory: Callable[..., Settings] = Settings,
    provider_factory: Callable[[Settings], GeminiProvider] = GeminiProvider.from_settings,
    input_fn: Callable[[str], str] = input,
) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--photos", type=Path, default=DEFAULT_PHOTOS, help="photo folder")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="food_item.csv")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--model", help="GEMINI_MODEL (default from the environment)")
    parser.add_argument("--resolution", choices=("low", "medium", "high"))
    parser.add_argument("--thinking", choices=("minimal", "low", "medium", "high"))
    parser.add_argument(
        "--timeout", type=float, help="GEMINI_TIMEOUT_S, below 10 (default from the environment)"
    )
    parser.add_argument("--first", type=int, help="only the first N photos of the manifest")
    parser.add_argument("--tag", help="suffix of the result file name, e.g. repeat")
    parser.add_argument("--overwrite", action="store_true", help="replace an existing result")
    parser.add_argument(
        "--limit", type=int, default=DEFAULT_LIMIT, help="most photos (billed calls) to send"
    )
    parser.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    parser.add_argument(
        "--compare", nargs=2, type=Path, metavar=("A", "B"), help="compare two result files"
    )
    args = parser.parse_args(argv)

    if args.compare:
        print(compare(*args.compare))
        return 0

    overrides = {
        key: value
        for key, value in {
            "gemini_model": args.model,
            "gemini_media_resolution": args.resolution,
            "gemini_thinking_level": args.thinking,
            "gemini_timeout_s": args.timeout,
        }.items()
        if value is not None
    }
    try:
        settings = settings_factory(**overrides)
    except ValidationError as error:
        fields = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in error.errors())
        parser.error(f"invalid setting: {fields}")

    try:
        photos = parse_manifest(args.manifest)
    except (OSError, ManifestError) as error:
        print(f"manifest {args.manifest}:\n{error}", file=sys.stderr)
        return 2
    if args.first is not None:
        photos = photos[: args.first]
    if not photos:
        print("no photos to evaluate", file=sys.stderr)
        return 2

    labels = load_labels(args.csv)
    facts = load_food_facts(args.csv)
    unknown = unknown_labels(photos, labels)
    if unknown:
        print(
            f"{len(unknown)} expected label(s) are not in {args.csv.name}:\n  "
            + "\n  ".join(unknown),
            file=sys.stderr,
        )
        return 2
    missing = [p.photo for p in photos if not (args.photos / p.photo).is_file()]
    if missing:
        print(
            f"{len(missing)} photo(s) not in {args.photos}:\n  " + "\n  ".join(missing),
            file=sys.stderr,
        )
        return 2
    if len(photos) > args.limit:
        print(
            f"{len(photos)} photos is more than --limit {args.limit} billed calls",
            file=sys.stderr,
        )
        return 2

    model = settings.gemini_model.strip()
    out = result_path(args.out_dir, model, settings.gemini_media_resolution, args.tag)
    if out.exists() and not args.overwrite:
        print(f"{out} exists; use --overwrite or --tag", file=sys.stderr)
        return 2
    if not settings.configured:
        print("GEMINI_API_KEY or GEMINI_MODEL is not set", file=sys.stderr)
        return 1

    counts = ", ".join(
        f"{sum(p.set == name for p in photos)} {name}"
        for name in SETS
        if any(p.set == name for p in photos)
    )
    print(
        f"model {model}, media resolution {settings.gemini_media_resolution}, "
        f"thinking {settings.gemini_thinking_level}, timeout {settings.gemini_timeout_s:g} s\n"
        f"{len(labels)} labels; {len(photos)} photos ({counts})\n"
        f"= {len(photos)} billed Gemini calls (a fast 429/5xx is retried once)\n"
        f"results: {out}"
    )
    if not args.yes:
        answer = input_fn(f"Send {len(photos)} billed Gemini calls? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("cancelled; nothing was sent")
            return 1

    provider = provider_factory(settings)
    results = asyncio.run(run_photos(provider, photos, args.photos, labels))
    write_results(out, results, facts)
    print("\n" + format_report(results, facts, model, settings.gemini_timeout_s))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    # gap dish names may hold Polish letters; never fail on a console without them
    sys.stdout.reconfigure(errors="replace")  # type: ignore[union-attr]
    sys.exit(main())
