# MongoDB buffer: `meal_recognitions`

Holds only unconfirmed meal recognition results (D3, FR-N4). Created by `database/mongo-init/01_meal_recognitions.js`. Field names are camelCase (internal only); the API returns the same fields in snake_case (`Recognition` in `openapi.yaml`).

## Lifecycle

1. The user uploads a photo; the backend stores it under `PHOTO_DIR` and calls `ai-service`, which calls the Gemini API (D25).
2. Labels are mapped to `food_item` rows (`algorithms.md` 11) and one document is written with `status: "pending"`.
3. Each correction in the review step updates the document.
4. Confirm writes `nutrition_log` and `nutrition_log_food_item` in one PostgreSQL transaction, then deletes the document. `meal_photo_url` is the document's `photoUrl` unchanged; the API builds any download URL from it at response time.
5. Unconfirmed documents are deleted by the TTL index after `expiresAt` (6 h). The cleanup job deletes their photos (Photo cleanup).

AI errors are returned directly; no `failed` document is stored.

## Document

| Field | Type | Description |
| --- | --- | --- |
| `_id` | ObjectId | Recognition id |
| `userId` | int | `app_user.id` |
| `status` | string | `pending` |
| `mealType` | string | `breakfast`, `lunch`, `dinner`, `snack` |
| `photoUrl` | string | Relative to `PHOTO_DIR`: `meals/<userId>/<uuid>.<ext>`; confirm copies it unchanged to `nutrition_log.meal_photo_url` |
| `model` | object | `name`, `version` of the Gemini model, returned by `ai-service` |
| `overallConfidence` | double | 0–1, highest item confidence (0 when nothing is found) |
| `recognisedItems` | array | See below |
| `createdAt` | date | Creation time |
| `expiresAt` | date | `createdAt` + 6 h, used by the TTL index |

Each element of `recognisedItems`:

| Field | Type | Description |
| --- | --- | --- |
| `name` | string | Model label, or the food name for an item added by hand |
| `foodItemId` | int / null | Matched `food_item.id`; null until the user picks one |
| `candidates` | array | The model's label and up to 2 alternatives, each `{label, confidence, foodItemId}` |
| `confidence` | double | 0–1 |
| `lowConfidence` | bool | confidence < 0.30 |
| `grams` | double | Starts at the model's estimate (fallback `default_portion_g`, `algorithms.md` 11), then as corrected |
| `nutrition` | object | `kcal`, `protein`, `fat`, `carbs` for `grams` |
| `allergyWarning` | bool | The food shares an allergen with the user |
| `corrected` | bool | The user changed the item or grams |

## Indexes

    db.meal_recognitions.createIndex({ expiresAt: 1 }, { expireAfterSeconds: 0 })
    db.meal_recognitions.createIndex({ userId: 1, status: 1 })

The TTL monitor runs about once a minute, so every query also filters `expiresAt > now`.

The backend creates the same indexes at startup (`MongoMealRecognitionRepository.ensure_indexes`), so a database not created by the init script (CI, a fresh deployment) has them too. Same keys and options as the script, so the call is a no-op on a compose database.

## Photo cleanup

When the TTL index has removed a document, its `photoUrl` can no longer be read, so the cleanup job (`app/db/photo_cleanup.py`, run by B-26) looks for orphans instead. A regular file under `PHOTO_DIR/meals/<userId>/` is deleted only when:

- no unexpired document references it,
- no `nutrition_log.meal_photo_url` references it (soft-deleted logs included; confirmed photos stay until account deletion),
- its mtime is older than the TTL plus a 30 min grace, so an upload whose document is not written yet, or a confirm running at that moment, is never touched.

MongoDB is read before PostgreSQL; if either cannot be read, nothing is deleted. Symlinks and paths outside `PHOTO_DIR` are skipped. Empty user folders are left in place. Account deletion removes `meals/<userId>/` as a whole after `purge_user`; if that step fails, the same rule removes the leftovers.
