# AI recognition evaluation (D-05)

Feasibility of meal photo recognition with the Gemini API (D25) for FR-N1–N4 and NFR-PERF.
Measured on 2026-11-20 with the code of `ai-service` `/predict`. T-03 reruns this evaluation
on the final pipeline and adds its results here.

**Verdict: go.** Keep the current defaults: `gemini-3.1-flash-lite`, media resolution
`medium`, thinking level `minimal`.
- **Accuracy:** the label or its alternatives hold the correct food for 97.4 % of the
  expected foods (D-05 asks for ≥ 80 %).
- **Latency:** p95 is 3.31 s in-process, with no timeouts.
- **Cost:** $1.28 per 1000 scans.

## Method

### Photo set

| | |
| --- | --- |
| Photos | 20, all in the `common` set (`ai-service/eval/manifest.csv`) |
| Expected foods | 78 (1–7 per photo, mean 3.9); drinks on the table count as foods |
| Weighed | none |
| Source | own phone photos by one person: 16 home meals, 4 restaurant plates. Not committed (privacy); on the team Drive |
| Polish meals | none in a set of their own; one Polish-style plate (fried potatoes with kiełbasa and mushrooms) |

**Scope.** D-05 first asked for at least 50 photos including Polish meals, with a separate
≥ 60 % threshold for Polish meals.
- On 2026-11-20 the team narrowed it to at least 20 photos of common meals, because the app
  does not target Polish cuisine in particular. `tasks.md` D-05 now says so.
- No meal was weighed, so the gram and kcal errors are not measured. T-03 adds weighed
  meals (see Limits).

**Ground truth.** Each expected food lists every seed label that is correct for it. For
example, a dark bread slice accepts `rye bread`, `multigrain bread`, `pumpernickel` and
`whole wheat bread`, since the kind of bread cannot be told from a photo.
- **No label:** the sauces (cream and mushroom sauce, chimichurri, a spicy glaze) have no
  seed label and are not expected.
- **Nearest label:** three foods without their own label are mapped to the closest one:
  octopus → `squid, fried`, manchego → `gouda|edam|parmesan`, chorizo →
  `salami|polish sausage (kielbasa)`.
- **Who decided:** the person who took the photos confirmed every expected food.

### Pipeline

`ai-service/scripts/evaluate.py` runs each photo in-process, with the code of `/predict`:
1. `prepare_photo`: at most 1024 px on the longest side, JPEG quality 85, no EXIF.
2. `GeminiProvider` sends one `generate_content` call, at temperature 0.

**Labels:** the 504 seed labels (`lower(name)` of `database/seed/food_item.csv`) go in the
prompt as a JSON array, and ai-service drops any label outside the list (D25).

**Recording:** a recording wrapper around the Gemini client keeps, for each call:
- the token counts of `usage_metadata`
- the number of attempts
- the labels Gemini returned outside the list
- Google's error message

These go only to `ai-service/eval/results/*.csv`, never to a log.

### Metrics

| Metric | Definition |
| --- | --- |
| Label hit | share of expected foods that some item's label matches |
| Label or alternatives hit | share of expected foods that some item's label or one of its up to 2 alternatives matches. **This is the D-05 criterion** |
| All foods found | share of photos where every expected food is a label or alternatives hit |
| Extra items | items whose label and alternatives match no expected food |
| Latency | `prepare_photo` plus the Gemini call, in-process: median, p95 (nearest rank) and max of the answered photos. The 4G upload and the backend hop are not included (T-04) |
| Timeouts | calls stopped by `GEMINI_TIMEOUT_S` |
| Tokens and cost | mean prompt, output and thinking tokens of the answered calls; cost per 1000 scans with the prices below. Thinking is billed as output; the implicit-cache discount is ignored |

**Failed calls** count as photos where nothing was found.

**Go criteria:**
- label or alternatives hit ≥ 80 % (common)
- p95 latency below 10 s in-process
- timeouts ≤ 5 %
- the production budget `GEMINI_TIMEOUT_S` = 7 s

A run with a longer timeout is a quality reference only: a model can be chosen only if it
meets the 7 s budget.

**Prices,** USD per 1M input / output tokens, checked on 2026-11-11:

| Model | Input | Output |
| --- | --- | --- |
| `gemini-3.1-flash-lite` | 0.25 | 1.50 |
| `gemini-3.5-flash-lite` | 0.30 | 2.50 |
| `gemini-3.8-flash` | 0.75 | 3.75 |

### Configurations

| Run | Model | Media resolution | Thinking | Timeout | Photos |
| --- | --- | --- | --- | --- | --- |
| A | `gemini-3.1-flash-lite` | medium | minimal | 7 s | 20 |
| B | `gemini-3.1-flash-lite` | high | minimal | 7 s | 20 |
| C (quality reference) | `gemini-3.8-flash` | medium | low | 9.9 s | 20 |
| A repeat | `gemini-3.1-flash-lite` | medium | minimal | 7 s | first 10 |

**Run C's thinking level.** `gemini-3.8-flash` refuses thinking level `minimal` with HTTP
400: "Thinking level MINIMAL is not supported for this model. Please retry with other
thinking level." Run C therefore uses `low`, the smallest change.

## Results

All photos are in the common set.

| | A | B | C |
| --- | --- | --- | --- |
| Label hit | 76/78 (97.4 %) | 73/78 (93.6 %) | 68/78 (87.2 %) |
| **Label or alternatives hit** (≥ 80 %) | **76/78 (97.4 %)** | 74/78 (94.9 %) | 68/78 (87.2 %) |
| Label or alternatives hit, answered photos only | 76/78 (97.4 %) | 74/78 (94.9 %) | 68/70 (97.1 %) |
| All foods found | 18/20 | 17/20 | 17/20 |
| Extra items (per photo) | 3 (0.15) | 3 (0.15) | 5 (0.28) |
| Latency median / p95 / max | 2.57 / 3.31 / 3.74 s | 2.77 / 3.26 / 3.64 s | 6.26 / 9.56 / 9.56 s |
| Calls over 7 s | 0 | 0 | 9 (7 answered, 2 timeouts) |
| Timeouts / errors | 0 / 0 | 0 / 0 | 2 / 0 (at 9.9 s) |
| Prompt / output / thinking tokens (mean) | 3,335 / 296 / 0 | 3,896 / 274 / 0 | 3,336 / 315 / 23 |
| Cost per 1000 scans | $1.28 | $1.38 | $3.77 |
| D-05 | **pass** | pass | fail (timeouts, budget) |

Gram error and kcal error: not measured (no weighed meals).

**Reproducibility.** Run A repeated on its first 10 photos returned the same labels, the
same alternatives and the same grams for 10 of 10 photos (`evaluate.py --compare`).
Temperature 0 is deterministic in practice.

### Misses and extras

| Photo | A | B | C |
| --- | --- | --- | --- |
| c05 patty, rice, fries | extra `cream of mushroom soup` (the sauce) | same | same |
| c11 chicken thigh, rice, cucumber salad | missed the peas | missed the peas and the cucumber bowl (called it `zucchini, cooked`, not a label) | timeout |
| c12 rice, black beans, carrot, pepper | — | — | one item `rice and beans`; missed carrot and pepper |
| c13 potatoes, kiełbasa, mushrooms | extra `spinach, raw` (parsley) | missed the onion | — |
| c14 octopus, sweet potato | — | — | extras `olive oil`, `zucchini, raw` |
| c15 chili, rice, cucumber | — | — | timeout |
| c18 fruit, cheeses, chorizo, eggs | — | manchego only as an alternative (label `emmental`) | — |
| c19 chicken bowl | — | missed the lettuce; extra `cappuccino` (the cup behind the plate) | extra `cappuccino` |
| c20 roast beef, salad, bread | missed the bread (see below); extra `pesto` (the chimichurri) | extra `pesto` | extra `pesto` |

Most extras are foods with no label of their own, mapped by Gemini to the nearest label (a
cream sauce → soup, chimichurri → pesto), or things beside the plate. Both kinds can be
deleted by the user at review (FR-N4).

**Labels outside the list.** Gemini returns a label that is not on the list in 3 of the 20
photos of run A, although the prompt asks for listed labels only:
- c14 `octopus, cooked`
- c17 `brioche`
- c20 `chimichurri`, `sourdough bread`

ai-service drops such an item completely (D25, `algorithms.md` 11), even when one of its
alternatives is on the list. That is how c20 lost its bread in run A.

## Choice

| | Choice | Reason |
| --- | --- | --- |
| Model | `gemini-3.1-flash-lite` | Passes every D-05 criterion. As accurate as `gemini-3.8-flash` on the photos both answered (97.4 % vs 97.1 %), about 2.4 times faster (median 2.57 s vs 6.26 s) and a third of the cost. `gemini-3.8-flash` cannot meet the 7 s budget: 9 of 20 calls took longer. `gemini-3.5-flash-lite` was not needed, because A passes |
| Media resolution | `medium` | `high` adds about 560 prompt tokens (+17 %) and was less accurate here (94.9 % vs 97.4 %) |
| Thinking level | `minimal` | No thinking tokens and no loss of accuracy. `gemini-3.1-flash-lite` accepts `minimal` |

These are the current defaults of `ai-service/app/config.py` and `.env.example`, so no
configuration change follows.

## Tokens and cost

| | Pre-implementation estimate, 11 Nov 2026 | Measured, run A |
| --- | --- | --- |
| Input (prompt) tokens | 3,310 = photo 560 (medium) + labels 2,350 (as a schema enum) + prompt and schema 400 | 3,335 (3,332–3,345) |
| Output tokens | 300 (about 4 items) | 296 (78–569; 3.9 items per photo) |
| Thinking tokens | 0 | 0 |
| Cost per 1000 scans (`gemini-3.1-flash-lite`) | $1.28 | $1.28 |

**Labels in the prompt cost about the same as a schema enum.** The estimate came from the
team's Gemini integration note and assumed a schema enum of the labels. Since then the
labels have moved into the prompt as a JSON array, because Gemini refuses an enum of 504
labels with HTTP 400 (D25). A higher prompt was expected, but the
measured prompt is within 1 % of the estimate.

**Growth:** the labels are most of the prompt, so it grows with the number of foods in the
seed.

**What this evaluation cost:** 73 billed calls (dry run 3, A 20, B 20, C 20, repeat 10),
plus a few calls of a run that was interrupted: about $0.15. The 22 calls that ended in
HTTP 400 (run C with thinking `minimal`, and two probes) were not billed.

## Label gaps (proposal for a seed follow-up)

**Seen in this evaluation:**
- **Returned by Gemini, no label:** octopus, brioche, sourdough bread.
- **Mapped to the nearest label:** chorizo (→ `salami`) and manchego (→ a hard cheese).
- **Sauces:** no seed sauce covers a cream or mushroom sauce, chimichurri or a spicy glaze.

**Found in the seed review for D-05:** common Polish dishes with no label at all:
- soups: żurek, zupa ogórkowa, krupnik, flaki, chłodnik
- mains and sides: bigos, łazanki, kluski śląskie, pyzy, fasolka po bretońsku, sałatka
  jarzynowa, ryba po grecku, kapusta zasmażana, golonka, zrazy, kluski leniwe, knedle ze
  śliwkami, zapiekanka
- sweets and drinks: makowiec, kompot

Others have only an approximate label, for example rosół → `chicken noodle soup`,
kopytka → `potato gnocchi`, twaróg → `cottage cheese`.

Adding labels is a DB-04 follow-up. Each new food needs a per-100 g source, and gets its
recognition label as A-01 describes.

**Proposal for ai-service (a separate change, not part of D-05):** when an item's label is
not on the list but one of its alternatives is, keep the item under that alternative
instead of dropping it. That would have recovered the bread in c20. It changes the
behaviour that D25 and `algorithms.md` 11 describe, so it needs a change request.

## Limits

- **Small set:** 20 photos from one person, mostly home cooking on similar plates; a
  single run per configuration.
- **No Polish meals:** accuracy on Polish dishes is unknown. The label gaps above suggest
  it would be lower than on these photos.
- **No weighed meals:** the gram and kcal errors, the part of FR-N2 that decides
  nutrition, are not measured. The gram estimates look plausible but are unverified.
- **Generous ground truth:** the accepted labels are generous where the photo cannot
  tell (the kind of bread, the fat level of a cheese). A stricter key would give lower hit
  rates.
- **In-process latency:** the upload over 4G or Wi-Fi and the backend hop are not
  included. T-04 measures the end-to-end 10 s of NFR-PERF.
- **Prices** are those of 2026-11-11 and ignore the implicit-cache discount (run B had
  some cached prompt tokens).

**T-03** reruns `evaluate.py` on the final pipeline, with weighed meals so that the gram
and kcal errors are measured (`tasks.md` T-03). More photos and more photographers would
also narrow the uncertainty of the hit rates.

## Reproduce

From `ai-service/`, with the photos in `eval/photos/`. Each run asks before sending its
billed calls.

```sh
uv run python -m scripts.evaluate --model gemini-3.1-flash-lite --resolution medium --thinking minimal
uv run python -m scripts.evaluate --model gemini-3.1-flash-lite --resolution high --thinking minimal
uv run python -m scripts.evaluate --model gemini-3.8-flash --resolution medium --thinking low --timeout 9.9
uv run python -m scripts.evaluate --model gemini-3.1-flash-lite --resolution medium --thinking minimal --first 10 --tag repeat
uv run python -m scripts.evaluate --compare eval/results/gemini-3.1-flash-lite_medium.csv eval/results/gemini-3.1-flash-lite_medium_repeat.csv
```

The results are in `ai-service/eval/results/`, one CSV per run.
