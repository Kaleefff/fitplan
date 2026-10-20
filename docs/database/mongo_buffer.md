# MongoDB buffer: `meal_recognitions`

Holds only unconfirmed meal recognition results (D3, FR-N4). Created by `database/mongo-init/01_meal_recognitions.js`. Field names are camelCase (internal only); the API returns the same fields in snake_case (`Recognition` in `openapi.yaml`).

## Lifecycle

1. The user uploads a photo; the backend stores it under `PHOTO_DIR` and calls `ai-service`.
2. Labels are mapped to `food_item` rows (`algorithms.md` 11) and one document is written with `status: "pending"`.
3. Each correction in the review step updates the document.
4. Confirm writes `nutrition_log` and `nutrition_log_food_item` in one PostgreSQL transaction, then deletes the document.
5. Unconfirmed documents are deleted by the TTL index after `expiresAt` (6 h). The cleanup job deletes their photos.

AI errors are returned directly; no `failed` document is stored.

## Document

| Field | Type | Description |
| --- | --- | --- |
| `_id` | ObjectId | Recognition id |
| `userId` | int | `app_user.id` |
| `status` | string | `pending` |
| `mealType` | string | `breakfast`, `lunch`, `dinner`, `snack` |
| `photoUrl` | string | Relative to `PHOTO_DIR`: `meals/<userId>/<uuid>.<ext>` |
| `model` | object | `name`, `version` returned by `ai-service` |
| `overallConfidence` | double | 0–1, top candidate |
| `recognisedItems` | array | See below |
| `createdAt` | date | Creation time |
| `expiresAt` | date | `createdAt` + 6 h, used by the TTL index |

Each element of `recognisedItems`:

| Field | Type | Description |
| --- | --- | --- |
| `name` | string | Model label, or the food name for an item added by hand |
| `foodItemId` | int / null | Matched `food_item.id`; null until the user picks one |
| `candidates` | array | Top-K `{label, confidence, foodItemId}` from the model |
| `confidence` | double | 0–1 |
| `lowConfidence` | bool | confidence < 0.30 |
| `grams` | double | Starts at `default_portion_g`, then as corrected |
| `nutrition` | object | `kcal`, `protein`, `fat`, `carbs` for `grams` |
| `allergyWarning` | bool | The food shares an allergen with the user |
| `corrected` | bool | The user changed the item or grams |

## Indexes

    db.meal_recognitions.createIndex({ expiresAt: 1 }, { expireAfterSeconds: 0 })
    db.meal_recognitions.createIndex({ userId: 1, status: 1 })

The TTL monitor runs about once a minute, so every query also filters `expiresAt > now`.
