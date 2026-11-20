"""Measure /predict latency on real photos (A-01, NFR-PERF). EVERY PHOTO COSTS MONEY.

Each photo is up to one billed Gemini call (paid tier, D25), so CI never runs this script.
Start ai-service with a real key first (README.md), then from ai-service/:

    uv run python scripts/measure_latency.py PHOTO_DIR [--url http://localhost:8001]

The photos are the .jpg, .jpeg, .png and .webp files directly in PHOTO_DIR, sent one
at a time in name order; more than --limit photos (default 20) is refused. The labels
are lower(name) of every row of database/seed/food_item.csv, the list migration 0005
and the seed write to food_item.recognition_label.

Latency is the wall time of the whole POST /predict as the backend sees it: upload,
photo check and resize, and the Gemini call. One line per photo, then the median,
mean, p95 (nearest rank) and max over the photos that got an answer (200), and how
many requests of all took longer than the 10 s of NFR-PERF. Exit status 1 if any
photo did not get an answer. The script never reads or prints the key.
"""

import argparse
import csv
import json
import math
import statistics
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CSV = REPO_ROOT / "database" / "seed" / "food_item.csv"
DEFAULT_URL = "http://localhost:8001"
DEFAULT_LIMIT = 20
NFR_PERF_SECONDS = 10.0
# ai-service bounds Gemini by GEMINI_TIMEOUT_S (< 10 s); this only stops a hung server
REQUEST_TIMEOUT_S = 30.0
CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


@dataclass
class Result:
    photo: str
    status: int
    seconds: float
    body: dict[str, Any] = field(default_factory=dict)


@dataclass
class Summary:
    answered: int
    total: int
    median: float | None
    mean: float | None
    p95: float | None
    max: float | None
    over_nfr: int


def load_labels(path: Path) -> list[str]:
    """lower(name) of every food, duplicates removed, file order kept."""
    with path.open(encoding="utf-8", newline="") as file:
        return list(dict.fromkeys(row["name"].lower() for row in csv.DictReader(file)))


def find_photos(folder: Path) -> list[Path]:
    return sorted(
        (p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in CONTENT_TYPES),
        key=lambda p: p.name.lower(),
    )


def p95(values: Sequence[float]) -> float:
    """Nearest-rank 95th percentile: the smallest value with >= 95 % of values at or below."""
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def summarise(results: Sequence[Result]) -> Summary:
    times = [r.seconds for r in results if r.status == 200]
    return Summary(
        answered=len(times),
        total=len(results),
        median=statistics.median(times) if times else None,
        mean=statistics.fmean(times) if times else None,
        p95=p95(times) if times else None,
        max=max(times) if times else None,
        over_nfr=sum(r.seconds > NFR_PERF_SECONDS for r in results),
    )


def predict(client: httpx.Client, photo: Path, labels_json: str) -> Result:
    content_type = CONTENT_TYPES[photo.suffix.lower()]
    files = {"photo": (photo.name, photo.read_bytes(), content_type)}
    started = time.perf_counter()
    response = client.post("/predict", files=files, data={"labels": labels_json})
    seconds = time.perf_counter() - started
    try:
        body = response.json()
    except ValueError:
        body = {}
    return Result(photo.name, response.status_code, seconds, body if isinstance(body, dict) else {})


def measure(client: httpx.Client, photos: Sequence[Path], labels: Sequence[str]) -> list[Result]:
    labels_json = json.dumps(list(labels), ensure_ascii=False)
    results = []
    for photo in photos:
        result = predict(client, photo, labels_json)
        print(describe(result), flush=True)
        results.append(result)
    return results


def describe(result: Result) -> str:
    head = f"{result.photo:<32} {result.status}  {result.seconds:6.2f} s"
    if result.status != 200:
        return f"{head}  {result.body.get('code', '?')}: {result.body.get('message', '')}"
    items = result.body.get("items", [])
    if not items:
        return f"{head}  (no items)"
    parts = []
    for item in items:
        grams = "?" if item.get("grams") is None else f"{item['grams']:g} g"
        parts.append(f"{item['label']} {item['confidence']:.2f} {grams}")
    return f"{head}  " + " | ".join(parts)


def format_summary(summary: Summary) -> str:
    def seconds(value: float | None) -> str:
        return "-" if value is None else f"{value:.2f} s"

    return (
        f"answered {summary.answered} of {summary.total}\n"
        f"median {seconds(summary.median)}  mean {seconds(summary.mean)}  "
        f"p95 {seconds(summary.p95)}  max {seconds(summary.max)}\n"
        f"over {NFR_PERF_SECONDS:g} s (NFR-PERF): {summary.over_nfr} of {summary.total}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("photo_dir", type=Path)
    parser.add_argument("--url", default=DEFAULT_URL, help=f"ai-service (default {DEFAULT_URL})")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="food_item.csv")
    parser.add_argument(
        "--limit", type=int, default=DEFAULT_LIMIT, help="most photos (billed calls) to send"
    )
    args = parser.parse_args(argv)

    if not args.photo_dir.is_dir():
        parser.error(f"not a folder: {args.photo_dir}")
    photos = find_photos(args.photo_dir)
    if not photos:
        parser.error(f"no .jpg, .jpeg, .png or .webp files in {args.photo_dir}")
    if len(photos) > args.limit:
        parser.error(f"{len(photos)} photos is more than --limit {args.limit} billed calls")
    labels = load_labels(args.csv)

    with httpx.Client(base_url=args.url, timeout=REQUEST_TIMEOUT_S) as client:
        try:
            health = client.get("/health")
        except httpx.HTTPError as error:
            print(f"ai-service not reachable at {args.url}: {type(error).__name__}")
            return 1
        if health.status_code != 200:
            print(f"ai-service /health answered {health.status_code}: {health.text}")
            return 1
        print(
            f"model {health.json().get('model')}, {len(labels)} labels, "
            f"{len(photos)} photos = up to {len(photos)} billed Gemini calls "
            "(a photo ai-service refuses is not sent to Gemini)\n"
        )
        results = measure(client, photos, labels)

    summary = summarise(results)
    print("\n" + format_summary(summary))
    return 0 if summary.answered == summary.total else 1


if __name__ == "__main__":
    sys.exit(main())
