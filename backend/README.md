# FitPlan Pro backend

FastAPI application, API prefix `/api/v1`. Uses Python 3.12 and [uv](https://docs.astral.sh/uv/).

## Run

```bash
cd backend
uv sync                                   # create .venv with all dependencies
uv run uvicorn app.main:app --reload      # http://localhost:8000/api/v1/docs
```

Settings come from the repository `.env` (see `.env.example`). Start the data stores first with `docker compose up -d` from the repository root; without them `/api/v1/health` answers `degraded`.

## Check

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

## Layout

| Path | Contents |
| --- | --- |
| `app/main.py` | App factory, lifespan (MongoDB client), routers |
| `app/core/` | Settings, JSON logging, error model of the contract |
| `app/api/v1/` | Routers, one module per tag |
| `app/services/` | Use cases that combine the domain with storage |
| `app/domain/` | Pure functions of `docs/instructions/algorithms.md`; `constants.py` holds every constant |
| `app/db/` | Models and sessions (DATA, task DB-01) |

Drivers (decisions D17, D18): psycopg 3 for PostgreSQL, PyMongo async for MongoDB.
