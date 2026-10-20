# FitPlan Pro

Engineering thesis project (Lublin University of Technology): mobile app for personalized training and diet plans with AI meal photo recognition. Code is written by AI agents, one per role, supervised by three humans; a human may write their own part by hand. Every change is reviewed by a human. Read this file fully before any work.

## Stack

- Backend: Python, FastAPI, SQLAlchemy 2.0, Alembic, Pydantic. API prefix `/api/v1`.
- PostgreSQL 17 (all persistent data) + MongoDB 8 (TTL buffer `meal_recognitions`, 6 h). Drivers: psycopg 3, async in the API and sync in Alembic (D17); PyMongo async (D18).
- `ai-service`: separate container, pretrained Food-101 model behind a `RecognitionProvider` interface (D12, verified by D-05).
- Mobile: React Native, Expo, TypeScript; Android 10+ primary.
- Local environment: docker-compose. Never commit `.env`; extend `.env.example`.

## Source of truth

Merged code wins for what already exists (names, types, constraints, file layout). If a document disagrees with merged code, fix the document in the same PR, or raise a change request if the code is wrong. For what is not built yet, higher wins:

1. `docs/instructions/requirements.md` (requirement IDs)
2. `docs/instructions/decisions.md`
3. `docs/instructions/algorithms.md` (formulas, constants, test vectors)
4. `docs/instructions/api-rules.md` (API behaviour, security checklist)
5. `database/init/01_schema.sql` (until the Alembic baseline of DB-01) and `docs/database/mongo_buffer.md`
6. `docs/api/openapi.yaml` (the contract, D-03; changed only by a contract PR reviewed by API and APP)
7. `docs/instructions/tasks.md` (what, who, which stage)

`docs/database/legacy/` is the previous semester's MySQL design. Do not use it.

## Ownership (D21; do not edit outside your area)

- DATA (Kyryl): `database/`, `backend/app/db/` (models, repositories, queries), `backend/alembic/`, `ai-service/`, `scripts/`, `docker-compose.yml`, `.env.example`, `.github/`.
- API (Maksym): `backend/app/` except `db/`, including the pure domain functions in `backend/app/domain/`.
- APP (Oleksandr): `mobile/`.
- `docs/` changes go in a `docs/` branch, approved by every role they touch.

## Workflow

- Follow `tasks.md`. Do not start a task whose dependencies are not merged. Stretch tasks only after the owner's core tasks of the stage are merged (D22).
- One task = one branch (`db/`, `api/`, `app/`, `docs/` + task id, e.g. `api/B-11-training-generator`) = one PR. Title starts with the task id; description lists the requirement IDs and how "Done" was verified.
- Never merge your own PR, including the repository admin.
- If the spec is silent or contradictory, do not invent behaviour: add the question to `docs/instructions/questions.md` with a proposed default, continue with other work, mention it in the PR. A human answers by editing the specs.

## Rules that are easy to get wrong

- Algorithms exactly as `algorithms.md`; its vectors are unit tests; constants in one module.
- Plans change only after an explicit signal (RPE ≥ 9 or an incomplete set, FR-A4).
- Object-level authorization on every query.
- bcrypt, passwords 8–72 bytes; access token 15 min, refresh 30 days with rotation and reuse detection.
- Error model `{code, message, details[]}`; validation is 422.
- Creates of logs carry a `client_uuid`; deletes are soft.
- Code and identifiers in English, thesis documentation in Polish. No secrets, tokens or full emails in logs.

## Definition of done

Code and tests green in CI; linters clean; OpenAPI conformance (backend contract tests, mobile generated types unchanged); docs updated if behaviour changed; PR cites requirement IDs.

## Commands

- Start data stores: `docker compose up -d`
- Reset after a schema change (deletes local data): `docker compose down -v && docker compose up -d`
- Setup and troubleshooting: `docs/instructions/setup.md`
