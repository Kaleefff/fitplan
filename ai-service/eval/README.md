# D-05 evaluation set

The photo set behind `docs/ai_evaluation.md` (D-05, rerun by T-03). The script is
`scripts/evaluate.py`; read its docstring before running it, because every photo is a billed
Gemini call.

| path | committed |
|---|---|
| `manifest.csv` | yes: one row per photo |
| `results/` | yes: one CSV per run, written by the script |
| `photos/` | no (`.gitignore`): privacy, licences and size; the photos are on the team Drive |

## Manifest

Columns: `photo`, `set`, `expected`, `grams`, `source`, `note`.

| column | content |
|---|---|
| `photo` | file name in `photos/`; `c`, `p` or `g` first for the set |
| `set` | `common`, `polish` (scored), `gap` (a dish with no label: only what comes back is recorded) |
| `expected` | the foods on the plate, separated by `;`. A food may accept several labels, separated by `\|`; the first is the true food (its kcal is used). Labels are `lower(name)` of `database/seed/food_item.csv`. For `gap`, the dish in free text |
| `grams` | weighed grams in the order of `expected`, separated by `;`; blank when not weighed, for example `180;;95` |
| `source` | `own`, or the Wikimedia Commons file URL |
| `note` | ignored by the script; `weigh` marks the meals to weigh |

`tests/test_evaluate.py` checks that every label in the manifest exists in the seed, so a
typo fails CI, not a paid run.

## Taking the photos

- **One plate per photo**, from above or at about 45°.
- **Light:** daylight, no flash and no strong shadows.
- **Frame:** no hands, faces, receipts or screens. A fork beside the plate is fine.
- **Foods:** separate, as served (mizeria next to the cutlet, not under it).
- **Phone:** take the photo as the app would get it: the phone camera, JPEG, no filters
  and no cropping.
- **Weighed meals** (`weigh` in `note`): weigh every food of the plate on a kitchen scale
  before plating, in grams, and write the weights in `grams` in the order of `expected`.
  For a mixed food (mizeria, a sauce), weigh each part before mixing and list it as its own
  food. A meal counts for the kcal error only when every food on it was weighed.
- **Web photos:** only from Wikimedia Commons, with the file page URL in `source`. Check
  that the plate matches `expected`.
- **Names:** keep the file names of the manifest, or rename the row too.
