# FitPlan Pro backend

FastAPI application, API prefix `/api/v1`. Uses Python 3.12 and [uv](https://docs.astral.sh/uv/).

## Run

```bash
cd backend
uv run alembic upgrade head               # create or update the PostgreSQL schema
uv run uvicorn app.main:app --reload      # http://localhost:8000/api/v1/docs
```

Settings come from the repository `.env` (see `.env.example`). Start the data stores first with `docker compose up -d` from the repository root; without them `/api/v1/health` answers `degraded`.

## Check

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

CI (DB-05) runs the same commands.

### Contract conformance (B-28)

`tests/contract/` fails when the app drifts from `docs/api/openapi.yaml`:

- every served operation must exist in the contract with the same `operationId`, parameters, request body and response schemas (`drift.py`); contract operations that are not implemented yet must be listed in `tests/contract/pending.py`, and that list must equal what the app does not serve (remove an operation there when you implement it);
- schemathesis generates requests from the contract for every implemented operation and validates the responses.

A route with parameters or a body passes `responses=VALIDATION_ERROR_RESPONSE` (from `app.core.errors`), so its 422 is documented with the contract `Error` model instead of FastAPI's `HTTPValidationError`.

## Layout

| Path | Contents |
| --- | --- |
| `app/main.py` | App factory, lifespan (MongoDB client), routers |
| `app/core/` | Settings, JSON logging, error model of the contract |
| `app/api/v1/` | Routers, one module per tag |
| `app/services/` | Use cases that combine the domain with storage |
| `app/domain/` | Pure functions of `docs/instructions/algorithms.md`; `constants.py` holds every constant |
| `app/db/` | DATA: `base.py` (declarative base, naming convention), `enums.py`, `session.py` (sync and async engines, D17), `models/` (one module per schema module) |
| `alembic/` | DATA: migrations; `0001_baseline` creates the whole schema |

Drivers (decisions D17, D18): psycopg 3 for PostgreSQL, PyMongo async for MongoDB.
