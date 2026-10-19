# API rules

Behaviour the OpenAPI contract (`docs/api/openapi.yaml`, D-03) must follow and that `algorithms.md` does not cover. Also the security checklist for T-05.

## Conventions

- Prefix `/api/v1`. JSON field names are snake_case, as in the schema (only the internal Mongo documents use camelCase).
- Error body `{code, message, details[]}`; `details[]` items have `field` (path), `code`, optional extra keys. Validation and database data errors (SQLSTATE class 22, ids outside the column range, NUL in text) are 422 `validation_error` / `invalid_value`, never 500.
- Status codes: 401 `unauthorized` / `invalid_credentials`, 405 `method_not_allowed`, 404 for missing rows and for other users' rows (no difference), 409 `conflict` on every operation that can conflict (archived plan, deleted `client_uuid`, occupied day or weekday), 413 `payload_too_large`, 429 `rate_limited` with `Retry-After`, 503 `service_unavailable` with `Retry-After` when the DB pool is exhausted.
- Lists of library data are ordered by name, then id, and paginated. Inactive foods (`is_active = false`) are hidden (detail 404) and cannot be logged.
- Dates: `log_date`, `measured_on` and similar may be at most tomorrow in the user's time zone (`future_date`). Time zone = IANA name on `app_user.timezone`, validated.
- Object-level authorization on every query: a user reads and writes only their own rows.

## Auth and account (FR-U1–U5, U8)

- bcrypt cost 12 (`BCRYPT_ROUNDS`); passwords 8–72 bytes, never logged or returned.
- Access token 15 min; refresh token 30 days, sliding (each rotation gives a fresh 30 days), rotated on every use; reuse of a rotated token revokes its whole family. Access tokens stay valid until expiry after logout (no deny list).
- Logout with the caller's own refresh token (even an already rotated one) revokes its family, 204; an unknown or foreign token is 401 and revokes nothing.
- Rate limit on register, login, forgot password and the password-checking account routes: 10 requests per 60 s per client IP and route (`AUTH_RATE_LIMIT`, `AUTH_RATE_WINDOW_SECONDS`), per process; the hard limit is at the reverse proxy. No per-account lockout.
- Registration: `name` and `surname` required, 1–100 characters after trimming. Wrong password and unknown email give the same response.
- Password reset: token stored hashed, single use, 1 h expiry, same response whether the email exists or not; a reset revokes all refresh tokens.
- Change email or password needs the current password (wrong: 401 `invalid_credentials`, not a session error). Password change revokes all refresh tokens; email change keeps sessions, is not verified, same email is a no-op 200. Social-only accounts get 422 `no_password` for both and delete their account without a password.
- Account deletion: PostgreSQL first (`app_user` cascades), then the Mongo buffer and the photos in `PHOTO_DIR/meals/<user id>/`. If the second step fails it is logged and the cleanup job removes the leftovers.
- Social sign-in (stretch): verify the provider ID token server-side, link by verified email, store `oauth_identity`, issue the normal token pair.

## Profile (FR-U6, U7)

- Profile fields and ranges as `algorithms.md` 0; one error per invalid or missing field.
- Injuries: no count limit, `start_date` not in the future; listed active first, then newest start date.
- Allergies and excluded foods are replaced as a whole (PUT): duplicate ids dropped; an unknown or inactive id is 422 `not_found` and nothing changes.

## Plans (FR-P1–P9, FR-A1)

- Generation, acceptance, swap: `algorithms.md` 4 and 5. A missing plan or another user's plan is 404.
- `PATCH /session-exercises/{id}` edits sets, reps, rest, weight (0–999.99) of a draft or active plan; archived is 409.
- `PATCH /training-sessions/{id}` moves a session to another weekday; a weekday already used in the plan is 409.
- `GET /sessions/next`: each session of the active plan recurs on its weekday from `start_date` to `end_date`; the next date is today or later in the user's time zone, skipping dates on which that session already has a workout; earliest date wins, ties by `session_order`; 404 without one.

## Logs (FR-A2, A3, R1 data)

- Every create carries a client `client_uuid`. Repeating it returns the first answer (201, nothing applied twice); the `client_uuid` of a deleted row is 409. Deletes are soft (`deleted_at`) and keep the adjustments and records they produced.
- `POST /workouts`: sets matched to planned exercises by `session_exercise_id`, else by `exercise_id`; 422 for a repeated `(exercise_id, set_number)`, an unknown exercise or session, or a `session_exercise_id` outside the given session. Editing a workout (`PUT`) keeps its `client_uuid`, does not adapt the plan and does not recompute records.
- `POST /body-metrics`: one measurement per day; saving again for the day replaces it (fields not sent become null); the same `client_uuid` may move it to another free day. The newest live measurement is copied to `user_profile.current_weight` and `tdee` is recomputed; a backdated one does not change the profile; deleting the newest restores the previous. A later profile update wins until the next measurement. History newest first.
- Nutrition logs: macros computed from the food database (grams to 0.1, values half up to 2 places), totals = sum of the rounded items. The same food twice in one log is 422 `duplicate`; a log above 9999.99 kcal is 422 `too_large`. `planned_meal_id` may point to any meal of the user's diet plans. `PATCH` replaces all items when `items` is sent.
- `GET /nutrition/daily-summary`: targets of the active diet plan (null without one), totals, `remaining` (may be negative), average hunger before and after ignoring empty values.

## Recognition (FR-N1–N4)

- Upload: type and size checked, EXIF stripped, stored as `PHOTO_DIR/meals/<user id>/<uuid>.<ext>`; `ai-service` called with a timeout; errors are returned directly (no `failed` document).
- Review: add, remove, replace items, change grams (nutrition recalculated, `corrected = true`). Confirm as `algorithms.md` 11. A failure inside confirm leaves PostgreSQL unchanged and the document intact.
- Photos of confirmed meals are kept until account deletion; photos of expired recognitions are removed by the cleanup job, which never deletes when MongoDB is unavailable.

## Reports and notifications (FR-R1, R6, R7, P9)

- `report_type` is derived from the period; generating the same period again replaces the stored report. Fewer than 7 days of history is 422 `insufficient_data`. Goal prediction fields are taken as of the generation day; `training_sessions_planned` is the compliance denominator rounded.
- Export (stretch): CSV `section,key,value`, UTF-8 with BOM; PDF with an embedded Unicode font (Polish letters must print). Same figures as the report.
- Reminders: the app proposes reminders from the accepted plan's weekdays and meal times and saves them with `PUT /reminders` (whole list replaced, at most 50); the server creates none by itself. `time_of_day` is wall-clock time, never converted.
- Push tokens (stretch): Expo format only, unique per device (re-registering refreshes it; a token used by another user moves to the new user), at most 10 per user (least recently seen dropped), invalid tokens removed.
- Push delivery (stretch): the `notification` row is the queue (`is_sent = false`); retried for 24 h; `PUSH_ENABLED=false` disables delivery. Producers: weekly report (`progress_update`), new personal record (`achievement`).

## Sync (NFR-OFF, stretch)

- Offline entities: plans (read), workout logs, nutrition logs, body metrics.
- `POST /sync/push`: at most 200 items, each in its own transaction; result per item `applied`, `unchanged`, `conflict` (with `server_copy`) or `rejected` (Error body, fields relative to the item).
- Workout and nutrition logs are append-only in sync (create and delete); body metrics can be edited. An edit or delete with a stale or missing `base_updated_at` on an edited row is a `conflict`; re-sending an identical item is `unchanged`; a deleted item stays deleted.
- `GET /sync/pull?cursor=`: changes ordered by (`updated_at`, kind, id), `limit` across kinds, tombstones included; the last page's cursor is `now − 60 s`, so the client applies items idempotently.
- Synced workouts update personal records but never adapt the plan.

## Hardening (NFR-SEC, NFR-SCALE)

Request IDs, CORS limited to the app origins, security headers, body limit 1 MiB (9 MiB on upload), HTTPS only with HSTS at the proxy, no secrets, tokens or full emails in logs (user id only), dependency audit in CI, DB pool and workers sized for 500 sessions.
