# Tasks

Schedule and owners follow `docs/Plan_implementacji.xlsx` (D20) with the split of D21. Specs: `requirements.md`, `algorithms.md`, `api-rules.md`, `database/init/01_schema.sql`, `docs/database/mongo_buffer.md`, `docs/api/openapi.yaml`.

| Role | Person | Area |
| --- | --- | --- |
| DATA | Kyryl | `database/`, `backend/app/db/` (models, repositories, queries), `backend/alembic/`, `ai-service/`, `scripts/`, `docker-compose.yml`, `.env.example`, `.github/` |
| API | Maksym | `backend/app/` except `db/`: endpoints, auth, domain logic, OpenAPI |
| APP | Oleksandr | `mobile/` |

Rules: one task = one branch (`db/`, `api/`, `app/`, `docs/` + id) = one PR, reviewed by someone else. Start a task only when its dependencies are merged. "Done" always includes the definition of done in `CLAUDE.md`. Unfinished tasks of a stage move to the start of the next one and are named in the end-of-week call. Status is given only for started work.

| Stage | Dates | DATA | API | APP |
| --- | --- | --- | --- | --- |
| 1 Foundation | 12–18 Oct | DB-00 | B-01, D-03 | M-01, D-09 |
| 2 Data, auth, profile | 19 Oct – 1 Nov | DB-01 … DB-06, D-05 | B-02 … B-06, B-10, B-28 | M-02 … M-07 |
| 3 AI scanner and logs | 2–22 Nov | A-01, DB-07 … DB-09 | B-08 … B-13, B-15, B-17, B-19 … B-21 | M-09 … M-11, M-13 … M-15, M-17, M-18 |
| 4 Analytics, feedback, reports | 23–29 Nov | DB-10 … DB-12 | B-14, B-16, B-22, B-23, B-25, B-26 | M-08, M-12, M-16, M-19, M-23 |
| Stretch (D22) | after the owner's core work | DB-13 | B-07, B-27, B-26 push, B-25 export | M-04 social, M-20, M-19 push and export |
| 5 Tests and optimisation | 30 Nov – 6 Dec | T-01, T-03, T-04, T-08, Z-01 | T-02, T-05 | T-06, T-07, M-21, M-22, Z-02 |

---

## Stage 1 · Foundation (12–18 Oct)

**DB-00 · ERD to PostgreSQL, docker-compose** · DATA · Status: done (`01_schema.sql`, PostgreSQL + MongoDB in compose).

**B-01 · Backend skeleton** · API · Status: merged (PR #13) with app factory, settings, `/api/v1/health`, logging, error handler, pytest, and the pure domain functions for B-10, B-15 (records), B-16 and B-23 (compliance, prediction).
Open: request IDs, CORS, security headers, body size limits, backend Dockerfile and compose service; `/health` switches to the shared engine once DB-01 is merged.
Done: `docker compose up -d` serves `/api/v1/health`; tests and lint pass in CI (DB-05).

**D-03 · OpenAPI contract** · API, reviewed by APP · Reqs: all FR · Depends: requirements, `api-rules.md` · Status: skeleton merged (PR #12); `x-todo` marks the fields that wait for DB-01.
Do: `docs/api/openapi.yaml`: every endpoint below with schemas, error model, codes, pagination, bearer auth, upload limits. Each operation's fields are completed by the task that implements it; afterwards it changes only by a contract PR reviewed by API and APP (no gate G1). Still missing from the skeleton: `PATCH /users/me`, `/users/me/excluded-foods`, `PATCH /training-sessions/{id}`, `PATCH /session-exercises/{id}`, `PUT/DELETE /workouts/{id}`, `DELETE /body-metrics/{id}`, `PATCH/DELETE /nutrition-logs/{id}`, `DELETE /meals/recognitions/{id}`, `GET /notifications`, `DELETE /devices/push-token`; `405 method_not_allowed` in the `Error.code` enum.

| Area | Endpoints |
| --- | --- |
| Auth | `POST /auth/register`, `/login`, `/refresh`, `/logout`, `/password/forgot`, `/password/reset`, `/google`, `/apple` |
| Account | `GET/PATCH /users/me`, `POST /users/me/email`, `/password`, `/delete`; `GET/PUT /users/me/profile`; `GET/POST/PATCH/DELETE /users/me/injuries`; `GET/PUT /users/me/allergies`, `/excluded-foods`; `GET /injury-types`, `/allergens` |
| Library | `GET /muscle-groups`, `/exercises`, `/exercises/{id}`, `/exercises/{id}/alternatives?session_exercise_id=`, `/foods`, `/foods/{id}`, `/food-categories` |
| Plans | `GET /nutrition/targets`; `POST /training-plans/generate`, `GET /training-plans/active`, `GET /training-plans/{id}`, `POST /training-plans/{id}/accept`, `PATCH /training-sessions/{id}`, `PATCH /session-exercises/{id}`, `PUT /session-exercises/{id}/swap`; `POST /diet-plans/generate`, `GET /diet-plans/active`, `GET /diet-plans/{id}`, `POST /diet-plans/{id}/accept` |
| Logs | `GET /sessions/next`; `POST/GET /workouts`, `PUT/DELETE /workouts/{id}`; `POST/GET /body-metrics`, `DELETE /body-metrics/{id}`; `POST/GET /nutrition-logs`, `PATCH/DELETE /nutrition-logs/{id}`; `GET /nutrition/daily-summary`, `/nutrition/suggestions` |
| Recognition | `POST /meals/recognitions` (multipart), `GET /meals/recognitions/{id}`, `POST .../items`, `PATCH/DELETE .../items/{index}`, `POST .../confirm`, `DELETE /meals/recognitions/{id}` |
| Analytics | `GET /analytics/summary?period=`, `/analytics/charts/{metric}?period=`, `/analytics/goal-prediction`; `POST/GET /reports`, `GET /reports/{id}`, `/reports/{id}/export?format=pdf|csv` |
| Schedule | `GET/PUT /reminders`, `GET /notifications`, `POST/DELETE /devices/push-token` |
| Sync | `POST /sync/push`, `GET /sync/pull?cursor=` |

Done: every FR reachable; the spec lints; APP approved the contract PRs.

**M-01 · App scaffolding** · APP · Status: merged (PR #11) with Expo + TypeScript, Expo Router tabs, settings screen, theme tokens, light/dark with saved preference.
Open: environment config, API client generated from the OpenAPI, mock server from the contract, central error handling.
Done: runs on an Android emulator against the mock server; lint and tests in CI.

**D-09 · Screen inventory** · APP
Do: navigation map and wireframes for screens without a mockup in chapter 7 (forgot/reset password, settings, libraries, workout session, recognition review, body metrics, reports, offline states); light and dark tokens; validation rules mirrored from the API.
Done: every FR with a UI part has a screen.

---

## Stage 2 · Data, auth and profile (19 Oct – 1 Nov)

### DATA

**DB-01 · Schema extension, models, Alembic baseline** · Reqs: all data-bearing FR, FR-U5, NFR-REL · Depends: DB-00
Do: extend `01_schema.sql` with what the specs need, then SQLAlchemy 2.0 models in `backend/app/db/models/` and an Alembic baseline (from then on schema changes are migrations). Names and types are yours to choose; keep D19 naming.

| # | Change |
| --- | --- |
| 1 | `app_user.timezone` (IANA, default `Europe/Warsaw`) |
| 2 | `user_profile`: age CHECK 16–100, height 120–250; add `experience_level`, `equipment` (new enum none/home/gym). `target_value` = target weight |
| 3 | `muscle_group.region` (upper/lower/core) |
| 4 | `exercise`: `equipment` enum instead of `required_equipment`; `is_compound`, `is_bodyweight`; exactly one primary group (partial unique index) |
| 5 | `injury.affected_muscle_group_id` FK instead of the VARCHAR; new `injury_type_excluded_exercise` |
| 6 | New `allergen`, `user_allergen`, `food_item_allergen`, `user_excluded_food` |
| 7 | `food_item`: unique name, `is_active`, `is_vegetarian`, `is_vegan`, `diet_role` (protein/carb/vegetable/fruit/dairy/fat/dish), `suitable_meal_types`, `default_portion_g`, `min_portion_g`, `max_portion_g`, `portion_step_g`, nullable unique `recognition_label` |
| 8 | `meal.day_index` 1–7; `diet_plan.diet_type`, `meals_per_day` |
| 9 | `training_plan`: `experience_level`, `equipment` (snapshot), `skipped_muscle_group_ids`; `training_session.session_name`, unique weekday per plan |
| 10 | `session_exercise.planned_weight` nullable without default; `original_exercise_id` |
| 11 | `workout_log.rpe_rating` nullable; `workout_set.completed`, `workout_set.rpe`; new `plan_adjustment`; `personal_record.e1rm` |
| 12 | `nutrition_log.planned_meal_id` (FK to `meal`, SET NULL) |
| 13 | `client_uuid` (unique), `updated_at`, `deleted_at` on `workout_log`, `nutrition_log`, `body_metrics`; one live measurement per day |
| 14 | `progress_report`: nullable `weight_difference` and `avg_cals_daily`; compliance %, `key_lifts`, `irregular_data`, `is_auto`; unique period per user and type |
| 15 | `notification.data`, `sent_at`; new `reminder`, `device_push_token`, `refresh_token`, `password_reset_token`, `oauth_identity` |

Done: `alembic upgrade head` and `downgrade base` work on an empty database; a test deletes a user and finds no owned row in any table; `setup.md` still works.

**DB-02 · Reference seeds** · Depends: DB-01
Do: `database/seed/` with muscle groups (`algorithms.md` 3), injury types with average healing days, allergens (EU 14 plus lactose), food categories; idempotent loader, the name is the key.
Done: running the loader twice gives identical data.

**DB-03 · Exercise seed** · Reqs: FR-P1–P3, P8 · Depends: DB-02
Do: exercises with every field, secondary groups and `injury_type_excluded_exercise` rows (conservative, not medical advice); equipment tiers of `algorithms.md` 4.2. Coverage script: goal main groups × equipment × level, report gaps (allowed, FR-P3 handles them, but each is deliberate).
Done: no empty field; coverage report committed; Kyryl spot-checked the exclusions.

**DB-04 · Food seed** · Reqs: FR-N2, N3, P6, P8 · Depends: DB-02
Do: per 100 g values from USDA FoodData Central or Polish tables, categories, allergens, flags, role, portions (bounds multiples of the step), `recognition_label` for Food-101 labels; unmapped labels listed in `database/seed/food101_unmapped.txt`. Enough items per role and meal type for vegetarian and vegan plans (including high-protein vegan options at breakfast). Validation script with the kcal rule of `algorithms.md` 0.
Done: validation passes; a sample (dish allergens included) spot-checked against the source.

**DB-05 · CI and compose** · Depends: DB-01
Do: GitHub Actions: ruff, pytest with PostgreSQL and MongoDB services, seed load and validation, mobile lint/test job for APP; compose services for `backend` and a mail catcher (Mailpit); `.env.example` updated.
Done: CI fails on a deliberately broken seed row and on a failing test.

**DB-06 · Library and eligibility queries** · Reqs: FR-P2, P6, P8, A1 · Depends: DB-03, DB-04
Do: repositories for exercises and foods (filters, text search, pagination, order of `api-rules.md`) and eligibility queries of `algorithms.md` 4.2, 4.3 and 5.2.
Done: tests prove an injury-excluded exercise and a food with a user's allergen are never returned.

**D-05 · AI model feasibility** · Reqs: FR-N1–N4, NFR-PERF · Due: before stage 3
Do: download `BinhQuocNguyen/food-recognition-model` (its `classification_model.h5` is listed at 121 bytes, possibly a pointer without weights); check the weights load and the label list; run ≥ 50 photos including Polish meals; top-1, top-3, CPU latency. Go if top-3 ≥ 80 % on Food-101 photos and ≥ 60 % on Polish meals with the request under 10 s; otherwise another Food-101 classifier or fine-tuned EfficientNet-B0 (interface unchanged).
Done: verdict with numbers in `docs/ai_evaluation.md`; D12 updated.

### API

**B-02 · Security primitives** · Reqs: FR-U2, NFR-SEC · Depends: B-01, DB-01
Do: bcrypt, JWT access and refresh with rotation, family revocation and reuse detection, `get_current_user`, auth rate limiting, object-level authorization helper (`api-rules.md`).
Done: tests for expired, tampered, revoked and reused tokens.

**B-03 · Register, login, refresh, logout** · Reqs: FR-U1, U2 · Depends: B-02
Done: duplicate email gives the contract error; wrong password and unknown email answer the same; passwords never logged or returned.

**B-04 · Password reset** · Reqs: FR-U3 · Depends: B-03, DB-05
Do: hashed single-use token, SMTP sender, rules of `api-rules.md`.
Done: an end-to-end test reads the mail from Mailpit and resets; reusing the token fails.

**B-05 · Account settings and deletion** · Reqs: FR-U4, U5 · Depends: B-03 (Mongo and photo part: DB-07)
Done: after deletion an audit query finds nothing for the user in PostgreSQL, MongoDB or `PHOTO_DIR`.

**B-06 · Profile, injuries, allergies, excluded foods** · Reqs: FR-U6, U7 · Depends: B-03, B-10, DB-02
Done: boundary tests (29/30/300/301 kg and the other ranges); one error per invalid or missing field; `tdee` recomputed on change.

**B-10 · Energy and macro targets** · Reqs: FR-P4, P5 · Depends: B-01
Do: `algorithms.md` 1–2 in the constants module; `GET /nutrition/targets`.
Status: domain function merged with B-01. Open: the endpoint.
Done: the four vectors pass.

**B-28 · Contract conformance in CI** · Depends: D-03, DB-05
Do: a test comparing the generated OpenAPI with the frozen YAML for every implemented operation (a pending list must equal the missing operations), schemathesis against the running app.
Done: CI blocks an undeclared change to a response schema.

### APP

**M-02 · Design system** · Reqs: NFR-UX · Depends: M-01
Do: tokens, shared components (button, input, card, tabs, chart card, toast, empty/loading/error states), layouts for 4.7–6.7 in, in both themes (tokens from M-01).
Done: no horizontal overflow at 4.7 in.

**M-03 · Auth session** · Reqs: FR-U2 · Depends: M-01
Do: tokens in `expo-secure-store`, refresh interceptor, session restore, logout, auth guard.
Done: an expired access token is refreshed transparently; a failed refresh opens login.

**M-04 · Login and registration** · Reqs: FR-U1, U2 · Depends: M-03
Done: server validation errors appear next to the right field. Google and Apple buttons are stretch (S-01).

**M-05 · Forgot and reset password** · Reqs: FR-U3 · Depends: M-04, B-04
Done: the mailed deep link opens the app and completes a reset against the dev backend.

**M-06 · Profile wizard** · Reqs: FR-U6, U7 · Depends: M-04, B-06
Do: age, sex, weight, height, PAL, goal, level, equipment, injuries, allergies, with client validation matching the API.
Done: out-of-range values cannot be submitted; finishing lands on Home.

**M-07 · Home** · Depends: M-02
Do: Quick Actions (Training Plan, Diet Plan, AI Food Scanner, Analytics).
Done: every tile navigates to its feature (placeholder until built).

---

## Stage 3 · AI scanner and activity logs (2–22 Nov)

### DATA

**A-01 · ai-service** · Reqs: FR-N2, NFR-PERF · Depends: D-05
Do: container with the chosen model loaded at startup from stored weights, `/predict` (type and size check, resize, top-K labels with confidence, model name and version) and `/health`; compose service with resource limits.
Done: starts offline; median inference time documented.

**DB-07 · Mongo buffer repository and photo cleanup** · Reqs: FR-N4, U5 · Depends: DB-01
Do: repository for `meal_recognitions` per `mongo_buffer.md` (create, get, update items, delete, purge a user), indexes ensured at startup, every read filters `expiresAt > now`; cleanup function for photos of expired recognitions (never deletes when MongoDB is unreachable).
Done: tests prove an expired, not yet deleted document is never returned.

**DB-08 · Label matching and confirm** · Reqs: FR-N2, N3, N4 · Depends: DB-04, DB-07
Do: map candidates to foods, default portions, nutrition, `low_confidence`, `allergy_warning` (`algorithms.md` 11); confirm function writing `nutrition_log` and items in one transaction, then deleting the document.
Done: an unknown label gives `food_item_id: null`; a failure inside confirm leaves PostgreSQL unchanged and the document intact.

**DB-09 · Log repositories** · Reqs: FR-A2, A3, R1, R2 · Depends: DB-01
Do: workouts (exercises, sets, idempotency by `client_uuid`, soft delete, personal record detection with e1RM), body metrics (one live row per day, current weight sync), nutrition logs (items, rounded totals), daily totals (`api-rules.md` Logs).
Done: the same `client_uuid` twice stores one row; record and rounding tests pass.

### API

**B-08 · Exercise library** · Reqs: FR-P8, A1 · Depends: DB-06
Done: alternatives never include an injury-excluded exercise; with `session_exercise_id` they match the swap check.

**B-09 · Food library** · Reqs: FR-P8 · Depends: DB-06
Done: search by name and category with pagination; values per 100 g; inactive foods hidden.

**B-11 · Training plan generator** · Reqs: FR-P1–P3, P7 · Depends: B-06, DB-06
Done: property test over goal × level × equipment × injuries: every required group covered, nothing excluded; p95 ≤ 3 s on seeded data.

**B-12 · Diet plan generator** · Reqs: FR-P6, P7 · Depends: B-10, DB-06
Done: every goal × diet type × meals per day without allergies passes `algorithms.md` 5.5; a food with a user's allergen is never selected; p95 ≤ 3 s.

**B-13 · Swap and plan edits** · Reqs: FR-A1 · Depends: B-08, B-11
Done: a swap keeps sets, reps, rest, weight; rejects other groups and injury-excluded exercises; archived plans give 409.

**B-15 · Workouts** · Reqs: FR-A2 · Depends: B-11, DB-09
Do: `POST/GET/PUT/DELETE /workouts`, `GET /sessions/next`, new records in the answer.
Done: RPE outside 1–10 rejected; a record stored only for a real improvement.

**B-17 · Body metrics** · Reqs: FR-R1 data, FR-U6 · Depends: DB-09
Done: history kept; the newest measurement updates the profile weight and TDEE.

**B-19 · Recognition upload and analysis** · Reqs: FR-N1–N3 · Depends: A-01, DB-08
Done: end to end ≤ 10 s in the test setup; an allergen is flagged.

**B-20 · Recognition review and confirm** · Reqs: FR-N4 · Depends: B-19
Done: edits recalculate nutrition; confirm creates the log; discard deletes the document and photo.

**B-21 · Nutrition logs and daily summary** · Reqs: FR-A3, R2 · Depends: B-12, DB-09
Done: totals equal the sum of the items; hunger validated.

### APP

**M-09 · Libraries** · Reqs: FR-P8 · Depends: M-02. Done: long lists scroll smoothly with pagination.

**M-10 · Training plan screens** · Reqs: FR-P1, P3, P7, A1 · Depends: M-06
Do: generation form, day tabs, accept, regenerate, insufficient-exercises message with suggestions, swap sheet, edits.
Done: the 422 suggestions are shown; a swap updates the plan at once.

**M-11 · Diet plan screens** · Reqs: FR-P4–P7 · Depends: M-06
Do: TDEE and target header, daily targets, meals with product cards and macros, accept, regenerate, diet type, allergies and excluded foods.
Done: displayed values equal the API response.

**M-13 · Workout session** · Reqs: FR-A2, A4, A5 · Depends: M-10
Do: log sets (reps, weight, completed, optional set RPE), rest timer, overall RPE at the end, show adjustments and new records.
Done: RPE ≥ 9 or a failed set is sent and the resulting change is shown.

**M-14 · Nutrition logging** · Reqs: FR-A3 · Depends: M-11
Do: manual add from the library or a planned meal, hunger before and after, daily totals against targets.
Done: totals update after each entry.

**M-15 · AI Food Scanner** · Reqs: FR-N1–N4 · Depends: M-02, D-03
Do: camera or gallery, upload with progress, review (items, grams, replace, add, remove, confidence, allergy warnings), confirm or discard, slow-request and error handling with retry.
Done: corrected grams change the totals before confirming; an allergy warning is visible before saving.

**M-17 · Body metrics** · Reqs: FR-R1 data · Depends: M-02. Done: entries appear in history and in the weight chart.

**M-18 · Analytics screen** · Reqs: FR-R1–R5 · Depends: M-02, D-03
Do: Week / Month / 3 Months, metric tiles, goal prediction with irregular-data warning, weight, workouts, calories and tonnage charts, compliance %, "not enough data" state. Built against the mock until B-23.
Done: loading, no data, normal and warning states reachable.

---

## Stage 4 · Analytics, feedback loop, reports (23–29 Nov)

### DATA

**DB-10 · Analytics queries** · Reqs: FR-R1–R3, R5 · Depends: DB-09
Do: the queries for `algorithms.md` 7 and 8: metrics, series, the counts that `app/domain/compliance.py` needs, minimum-data rule (D21: the math stays in Max's domain module).
Done: hand-computed fixtures match; the 6/7-day boundary is tested.

**DB-11 · Goal prediction data** · Reqs: FR-R4 · Depends: DB-10
Do: query for the weigh-ins of the last 28 days, target weight and 28-day workout compliance, in the shape `app/domain/prediction.py` takes.
Done: fixtures for regular, irregular, flat and wrong-direction data give the statuses of `algorithms.md` 9 end to end.

**DB-12 · Index review** · Reqs: NFR-PERF, NFR-SCALE · Depends: DB-10
Do: `EXPLAIN ANALYZE` of generator, log and analytics queries on seeded data with a year of history for test users; add indexes in a migration.
Done: no sequential scan on large tables in those queries; results noted in the PR.

### API

**B-16 · Adaptation and progression** · Reqs: FR-A4, A5 · Depends: B-15 · Status: domain function merged with B-01; change request: the reserve signal needs sets at `≥ planned_weight` and progression is `planned_weight + step`, not lowest set + step (vector K). Open: wiring into `POST /workouts`.
Done: vectors A–K of `algorithms.md` 6 pass; no `plan_adjustment` without a signal.

**B-23 · Analytics and goal prediction endpoints** · Reqs: FR-R1–R5 · Depends: DB-10, DB-11 · Status: compliance and prediction domain functions merged with B-01.
Do: endpoints combining DB-10/DB-11 queries with the domain functions. Done: answers equal the DB-10/DB-11 fixtures.

**B-25 · Reports** · Reqs: FR-R1 · Depends: B-23
Do: generate, list, detail of `progress_report` (`api-rules.md`). Export is stretch S-04.
Done: report figures equal the analytics for the same period.

**B-14 · Schedule and reminders** · Reqs: FR-P9 · Depends: B-11, B-12
Do: `GET/PUT /reminders`, `PATCH /training-sessions/{id}`, `GET /notifications`.
Done: the schedule round-trips; a weekday clash gives 409.

**B-26 · Scheduler process** · Reqs: FR-N4 (cleanup), FR-R7 · Depends: DB-07
Do: one process running idempotent jobs every 15 min; core job: expired-photo cleanup. Weekly report and push delivery are stretch S-03.
Done: no orphan photo remains after expiry.

**B-22 · Meal suggestions** · Reqs: FR-N5 · Depends: B-21, B-10
Done: suggestions never exceed remaining kcal × 1.05 and never contain an allergen.

### APP

**M-12 · Schedule and local reminders** · Reqs: FR-P9 · Depends: M-10, M-11, B-14
Done: a reminder fires at the set time on a real Android 10+ device; denied permission is handled.

**M-23 · Dark mode pass** · Reqs: NFR-UX · Depends: M-02. Theme switch and saved preference exist (M-01). Done: every screen renders in both themes.

**M-08 · Settings** · Reqs: FR-U4–U6 · Depends: M-06, B-05
Do: edit profile, change email and password, delete account (double confirmation), theme switch, reminders, logout.
Done: after deletion local data is cleared and login is shown.

**M-16 · Meal suggestions** · Reqs: FR-N5 · Depends: M-14, B-22. Done: suggestions refresh after a new log; one tap adds one.

**M-19 · Reports** · Reqs: FR-R1 · Depends: M-18, B-25. Done: list and detail show the API figures.

---

## Stretch (D22)

Started by an owner only after their core tasks of the current stage are merged. Built in this order; cut from the end of the D22 list.

| ID | Feature | DATA | API | APP |
| --- | --- | --- | --- | --- |
| S-01 | Google sign-in, then Apple (needs an Apple Developer account) | – | B-07: verify provider token, link by verified email, `oauth_identity` | M-04 buttons |
| S-02 | Offline sync (NFR-OFF) | DB-13: change queries by cursor with tombstones | B-27: `/sync/push`, `/sync/pull` (`api-rules.md` Sync) | M-20: `expo-sqlite` store, sync queue, offline banner, online-only messages |
| S-03 | Weekly report and push (FR-R7) | – | B-26: weekly job (`algorithms.md` 12), Expo push, push-token endpoints | M-19: register token, notification opens the report |
| S-04 | Export (FR-R6) | – | B-25: PDF and CSV | M-19: export and share |

Done: S-01 a forged or expired provider token is rejected and an existing email account is linked, not duplicated. S-02 a workout and a nutrition entry made in airplane mode reach the server once after reconnecting; replaying a push changes nothing. S-03 a double run creates one report per user and week. S-04 the file opens in an external app with the on-screen figures.

---

## Stage 5 · Tests and optimisation (30 Nov – 6 Dec)

**T-01 · CI completion** · DATA · Do: coverage report, dependency audit (pip-audit, npm audit), all jobs required on `main`.

**Z-01 · Backups and production-like stack** · DATA · Reqs: NFR-SEC, NFR-REL
Do: compose production profile with a TLS reverse proxy (HTTPS only, HSTS), secrets outside the repo, `pg_dump` backup job, restore test.
Done: a backup restores into a clean instance; the API answers only over HTTPS.

**T-04 · Load test** · DATA · Reqs: NFR-SCALE, NFR-PERF
Do: size the DB pool and workers, then Locust with 500 concurrent sessions against a baseline; plan generation ≤ 3 s; photo analysis ≤ 10 s on a throttled 4G profile.
Done: results table with pass or fail per NFR.

**T-03 · AI accuracy** · DATA · Do: rerun the D-05 evaluation on the final pipeline (top-1, top-3, latency, effect of default portions); add to `docs/ai_evaluation.md`.

**T-08 · GDPR deletion audit** · DATA + API · Done: written audit with the queries showing nothing left in PostgreSQL, MongoDB, photos or logs.

**T-02 · Integration and requirement tests** · API
Do: replace the mock with the real stack together with APP, fix contract drift, run scenarios S1–S3 (chapter 6.1), the FR-P2 property test and the FR-A4 negative test, complete pytest coverage.
Done: every FR in the matrix below has a passing test or a recorded defect.

**T-05 · Security review** · API · Do: the `api-rules.md` checklist: user A cannot read user B, token tampering, brute force, reset enumeration, upload abuse, injection, HTTPS only. Done: no open high or critical finding.

**M-21 · Performance and compatibility** · APP · Reqs: NFR-PERF, NFR-COMP. Done: interactions ≤ 300 ms on the reference device; release build ~200 MB or less.

**M-22 · Mobile tests** · APP · Do: Jest, component tests, Maestro flows for registration + profile, plan generation, meal scan, workout logging, analytics.

**T-06 · Compatibility** · APP · Done: device matrix (Android 10+, 4.7–6.7 in, light and dark) with results.

**T-07 · Usability** · APP · Do: Nielsen heuristic review, sessions with 3 users on four tasks (register and profile, generate a plan, scan a meal, read analytics), SUS questionnaire. Done: severity 1–2 findings fixed or accepted.

**Z-02 · Release build** · APP · Done: signed Android build works against the production-like server.

**T-09 · Release acceptance (6 Dec)** · ALL · Do: demo scenario end to end on the release build; sign the matrix below.

After 6 Dec: **W-01** thesis documentation in Polish (diagrams and chapters matching the code, test results, user manual); **W-02** developer docs (README, OpenAPI docs, seed guide).

---

## Traceability

| Req | Build | Verify |
| --- | --- | --- |
| FR-U1, U2 | B-02, B-03, M-03, M-04 | T-02, T-05 |
| FR-U3 | B-04, M-05 | T-02, T-05 |
| FR-U4 | B-05, M-08 | T-02 |
| FR-U5 | DB-01, DB-07, B-05, M-08 | T-08 |
| FR-U6, U7 | DB-01, B-06, B-10, M-06, M-08 | T-02 |
| FR-U8 | S-01 | T-02, T-05 |
| FR-P1–P3 | DB-03, DB-06, B-11, M-10 | T-02 |
| FR-P4, P5 | B-10, M-11 | T-02 |
| FR-P6 | DB-04, DB-06, B-12, M-11 | T-02 |
| FR-P7 | B-11, B-12, M-10, M-11 | T-02 |
| FR-P8 | DB-03, DB-04, DB-06, B-08, B-09, M-09 | T-02 |
| FR-P9 | B-14, M-12 (push: S-03) | T-02 |
| FR-A1 | DB-06, B-08, B-13, M-10 | T-02 |
| FR-A2 | DB-09, B-15, M-13 | T-02 |
| FR-A3 | DB-09, B-21, M-14 | T-02 |
| FR-A4, A5 | B-16, M-13 | T-02 (A4 negative test) |
| FR-N1–N3 | D-05, A-01, DB-04, DB-08, B-19, M-15 | T-02, T-03 |
| FR-N4 | DB-07, DB-08, B-20, B-26, M-15 | T-02 |
| FR-N5 | B-22, M-16 | T-02 |
| FR-R1–R3, R5 | DB-09, DB-10, B-23, B-25, M-17, M-18, M-19 | T-02 |
| FR-R4 | DB-11, B-23, M-18 | T-02 |
| FR-R6 | S-04 | T-02 |
| FR-R7 | S-03 | T-02 |
| NFR-PERF | B-11, B-12, A-01, DB-12, M-21 | T-04 |
| NFR-SCALE | B-01, DB-12 | T-04 |
| NFR-COMP | M-21 | T-06 |
| NFR-SEC | B-02, Z-01 | T-05 |
| NFR-REL | DB-01, DB-08 | T-02, Z-01 |
| NFR-UX | M-02, M-23 | T-06, T-07 |
| NFR-OFF | S-02 | T-02 |
