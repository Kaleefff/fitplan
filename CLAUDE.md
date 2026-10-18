# FitPlan Pro

Engineering thesis project (Lublin University of Technology): mobile app for personalized training and diet plans with AI meal photo recognition. Code is written by AI agents, one per role, and supervised by three humans; a human may also write their own part by hand. Every generated change is reviewed by a human. Read this file fully before any work.

## Stack

- Backend: Python, FastAPI, SQLAlchemy 2.0, Alembic, Pydantic. API prefix `/api/v1`.
- PostgreSQL 17 (all persistent data) + MongoDB 8 (TTL buffer `meal_recognitions`, 6 h).
- `ai-service`: separate container, pretrained `BinhQuocNguyen/food-recognition-model` behind a `RecognitionProvider` interface.
- Mobile: React Native, Expo, TypeScript, expo-sqlite (offline), Android 10+ primary.
- Local environment: docker-compose. Never commit `.env`; extend `.env.example`.

## Source of truth

Merged code wins for anything that already exists (table and column names, types, constraints, file layout). If a document disagrees with merged code, fix the document in the same PR, or open a change request if the code is wrong. For everything not built yet, higher wins on conflict:

1. `docs/instructions/requirements.md` (binding requirement IDs)
2. `docs/instructions/decisions.md`
3. `docs/instructions/algorithms.md` (formulas, constants, test vectors)
4. `database/init/01_schema.sql` (PostgreSQL schema until the Alembic baseline of DB-01 replaces it) and `docs/database/mongo_buffer.md`
5. `docs/api/openapi.yaml` (the API contract, created by D-03; frozen once signed, changed only through a contract change PR reviewed by API and APP)
6. `docs/instructions/tasks.md` (what to do, who does it, in which week)

Files in `docs/database/legacy/` (`scheme_mysql.sql`, `ERD.png`) describe the previous semester's MySQL design. Do not use them.

## Ownership (do not edit outside your area)

- DATA: `database/`, `backend/app/db/`, `backend/alembic/`, seeds, `scripts/` for the DB.
- API: `backend/app/` except `db/`, `ai-service/`.
- APP: `mobile/`.
- `docs/` changes go in a `docs/` branch and need approval from every role whose area they touch.

## Workflow

- Follow `docs/instructions/tasks.md`. Do not start a task whose "Depends on" items are not merged.
- One task = one branch (`db/`, `api/`, `app/`, `docs/` + task id, e.g. `api/B-11-training-generator`) = one pull request, one human approval.
- The PR title starts with the task id; the description lists the FR/NFR ids implemented and how "Done when" was verified.
- Every PR includes tests and passes CI.
- Never merge your own PR. This applies to everyone, including the repository admin.

## When the spec is silent or contradictory

Do not invent behaviour. Append the question to `docs/instructions/questions.md` (task id, what is unclear, your proposed default), continue with other work, and mention it in the PR. A human answers by editing the docs.

## Rules that are easy to get wrong

- Algorithms: implement exactly `docs/instructions/algorithms.md`; its numeric vectors are the unit tests. Constants live in one module.
- Plans change only after an explicit signal (RPE >= 9 or an incomplete set, FR-A4). Never otherwise.
- Object-level authorization on every query: a user only reads and writes their own rows.
- Passwords: bcrypt, max 72 bytes (reject longer input). Tokens: access 15 min, refresh 30 days with rotation and reuse detection.
- Errors use the common model from the OpenAPI (`code`, `message`, `details[]`); validation is HTTP 422.
- Sync: client UUIDs, optimistic concurrency via `base_updated_at`, tombstones; logs are append-only.
- Code, identifiers and comments in English; thesis documentation in Polish. No secrets, tokens or full emails in logs.

## Definition of done (every task)

Code + tests green; linters clean; OpenAPI conformance (backend: `schemathesis` or contract tests; mobile: generated types unchanged); docs updated if behaviour changed; PR description cites FR ids.

## Commands

- Start data stores: `docker compose up -d`
- Reset data stores after a schema change (deletes local data): `docker compose down -v && docker compose up -d`
- Setup and troubleshooting: `docs/instructions/setup.md`
