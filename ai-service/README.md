# ai-service

Meal photo recognition for FitPlan Pro (A-01, FR-N2, NFR-PERF). It is a thin client of the
Gemini API behind the `RecognitionProvider` interface (D25). Only the backend (B-19) calls
it, inside the compose network. ai-service has no database access and holds only the Gemini
key.

## API

### `POST /predict`

The request is `multipart/form-data` with two fields:

| field | content |
|---|---|
| `photo` | JPEG, PNG or WebP (checked by content, not by name), at most 8 MiB |
| `labels` | a JSON array of the active recognition labels, for example `["basmati rice, cooked", "żurek"]`: 1–2000 distinct non-blank strings of at most 100 characters, used exactly as sent |

A successful answer is `200`. Every item label and alternative label is one of the labels
that were sent, spelled as sent:

```json
{
  "model": {"name": "gemini-3.1-flash-lite", "version": "gemini-3.1-flash-lite"},
  "items": [
    {
      "label": "basmati rice, cooked",
      "confidence": 0.86,
      "grams": 180,
      "alternatives": [{"label": "white rice, cooked", "confidence": 0.1}]
    }
  ]
}
```

- **Items:** at most 20; an empty list means no food was seen.
- **Confidence:** from 0 to 1.
- **Grams:** above 0, or `null` when the model gives 0 or less.
- **Alternatives:** at most 2 per item.
- **Labels outside the list:** an item whose label is not one of the sent labels is
  dropped, and so is such an alternative (also one equal to its item's label, or
  repeated). Matching trims and lower-cases both sides (`algorithms.md` 11).
- **No partial answers:** if any item is malformed, the whole answer is an error.

Errors use the backend's model `{code, message, details[]}`:

| status | code | when |
|---|---|---|
| 400 | `invalid_image` | not a readable JPEG, PNG or WebP, or over 50 megapixels |
| 413 | `payload_too_large` | photo over 8 MiB |
| 422 | `validation_error` | a missing field, or invalid `labels` |
| 502 | `ai_unavailable` | Gemini error, blocked photo or invalid answer |
| 504 | `ai_unavailable` | Gemini did not answer within `GEMINI_TIMEOUT_S` |
| 503 | `not_configured` | `GEMINI_API_KEY` or `GEMINI_MODEL` is not set |

### `GET /health`

Returns `200 {"status": "ok", "model": ...}`, or `503 {"status": "not_configured", ...}`
without a key. It never calls Gemini.

## Notes for the backend (B-19)

- **Labels:** send the active `food_item.recognition_label` values with every call (see
  `questions.md` `[A-01] labels-source`).
- **Timeout:** about 8.5 s. ai-service answers within `GEMINI_TIMEOUT_S` (7 s) plus the photo
  preparation.
- **Error mapping onto the contract:**
  - 502, 504 and 503 → `503 ai_unavailable` (ServiceUnavailable)
  - 400 `invalid_image` → `422 validation_error`
  - an unreachable ai-service → `503 ai_unavailable`
- **Items** map one to one onto `Detection` in `app/db/repositories/recognition.py`: label,
  confidence, grams (or `None`) and alternatives as `(label, confidence)`.

## How it works

1. **Photo** (`app/image.py`):
   - opened only as JPEG, PNG or WebP, using the first frame of an animation
   - refused over 50 megapixels (decompression bombs)
   - turned upright from EXIF, with transparency flattened onto white
   - shrunk to at most 1024 px per side and re-encoded as JPEG quality 85, with no EXIF
     (no location is sent to Google)
2. **Gemini** (`app/gemini.py`):
   - **Call:** one `generate_content` call. The prompt ends with the sent labels as a JSON
     array, and a JSON response schema fixes the answer's shape. Temperature is 0, with
     `GEMINI_THINKING_LEVEL` and `GEMINI_MEDIA_RESOLUTION`.
   - **Why the labels are in the prompt, not a schema enum (D25):** Gemini refuses an enum of
     the 504 seed labels with HTTP 400 ("too many states" / "too much branching";
     gemini-3.1-flash-lite, 2026-11-19), even as a single enum with no other limits. So
     ai-service checks every label against the list itself.
   - **Cost of the labels:** with the 504 seed labels and a medium-resolution photo, the
     whole prompt is about 3,340 tokens (measured by D-05, `docs/ai_evaluation.md`). It
     grows with the number of foods.
   - **Time and retry:**
     - the whole call, the retry included, has `GEMINI_TIMEOUT_S`
     - one retry, only after a 429 or 5xx that came back within 2 s
     - never a retry after a timeout
     - the SDK gets no timeout: it would send it to Google as the request deadline, and
       Google refuses a deadline under 10 s (HTTP 400)
3. **Logging:**
   - one line per call with the model, outcome, latency, attempts and token counts
   - never the key, the photo, the labels or the model's answer

## Configuration

The settings come from the environment, or from the repository's `.env` when ai-service runs
on the host (see `.env.example`).

| variable | default | |
|---|---|---|
| `GEMINI_API_KEY` | empty | key of a Google project with billing enabled (D25); never commit it |
| `GEMINI_MODEL` | `gemini-3.1-flash-lite` | |
| `GEMINI_TIMEOUT_S` | `7` | must be above 0 and below 10 (NFR-PERF) |
| `GEMINI_MEDIA_RESOLUTION` | `medium` | `low`, `medium` or `high` |
| `GEMINI_THINKING_LEVEL` | `minimal` | `minimal`, `low`, `medium` or `high` |
| `LOG_LEVEL` | `INFO` | |

## Run

Run these from `ai-service/`, with [uv](https://docs.astral.sh/uv/):

```sh
uv sync
uv run uvicorn app.main:create_app --factory --port 8001
```

To run it in compose instead (internal only, no host port; the backend reaches it at
`http://ai-service:8001`):

```sh
docker compose up -d --build ai-service
```

## Tests

```sh
uv run ruff check . && uv run ruff format --check .
uv run pytest
```

The tests use a fake Gemini client and a mock HTTP transport. They never call Gemini and
need no key. CI runs them in the `ai-service` job.

## Measuring latency (costs money)

`scripts/measure_latency.py` sends every `.jpg`, `.jpeg`, `.png` and `.webp` file in a folder
to a running ai-service, one at a time.
- **Labels:** `lower(name)` of every row of `database/seed/food_item.csv`.
- **Output:** each result, then the median, mean, p95 and max latency of the answered
  photos, and how many requests took longer than 10 s.
- **Cost:** each photo is one billed Gemini call. The script refuses more than `--limit`
  photos (default 20), and CI never runs it.

```sh
uv run python scripts/measure_latency.py path/to/photos --url http://localhost:8001
```

## Evaluating accuracy (costs money)

`scripts/evaluate.py` runs the photo set of `eval/` through the code of `/predict`
in-process (D-05, rerun by T-03; results in `docs/ai_evaluation.md`).
- **Input:** `eval/manifest.csv` and the photos in `eval/photos/`. The photos are not
  committed; see `eval/README.md`.
- **Output:**
  - `eval/results/<model>_<resolution>.csv`
  - the label and alternatives hit rates, gram and kcal error, latency, tokens and cost
    per 1000 scans
- **Cost:** it asks before sending and refuses more than `--limit` photos (default 80).
  CI never runs it.

```sh
uv run python -m scripts.evaluate --model gemini-3.1-flash-lite --resolution medium
```
