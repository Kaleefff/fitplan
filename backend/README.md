# FitPlan Pro backend

FastAPI application, API prefix `/api/v1`. Uses Python 3.12 and [uv](https://docs.astral.sh/uv/).

## Run

```bash
cd backend
uv run alembic upgrade head               # create or update the PostgreSQL schema
uv run uvicorn app.main:app --reload      # http://localhost:8000/api/v1/docs
```

Settings come from the repository `.env` (see `.env.example`). Start the data stores first with `docker compose up -d` from the repository root; without them `/api/v1/health` answers `degraded`.

Auth needs `JWT_SECRET` (at least 32 random bytes, e.g. `python -c "import secrets; print(secrets.token_urlsafe(48))"`) in `.env`; without it the app starts but issuing or checking a token fails. Other auth settings (`BCRYPT_ROUNDS`, `AUTH_RATE_LIMIT`, `AUTH_RATE_WINDOW_SECONDS`) have the defaults of `api-rules.md`.

Docker image: `docker build -t fitplan-backend backend` from the repository root; the compose service comes with DB-05.

### Hardening (api-rules.md)

`app/core/middleware.py`, in the order a request passes them:

- `X-Request-ID` ([asgi-correlation-id](https://github.com/snok/asgi-correlation-id)): a valid UUID from the client is kept, otherwise a new one; returned on every response and added to every log line as `request_id`.
- CORS only for `CORS_ORIGINS`, a JSON list (empty by default; the native Android app sends no `Origin`). Expo web: `CORS_ORIGINS='["http://localhost:8081"]'`.
- Security headers: the defaults of [secure](https://github.com/TypeError/secure); the Swagger UI page has no CSP, because it loads from a CDN.
- Body limit 1 MiB, 9 MiB on `POST /meals/recognitions` (`MAX_BODY_BYTES`, `MAX_UPLOAD_BODY_BYTES`): 413 `payload_too_large`, by `Content-Length` or by the bytes read.

## Check

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

## Layout

| Path | Contents |
| --- | --- |
| `app/main.py` | App factory, lifespan (MongoDB client), routers |
| `app/core/` | Settings, JSON logging, error model of the contract, hardening middleware |
| `app/api/v1/` | Routers, one module per tag |
| `app/services/` | Use cases that combine the domain with storage |
| `app/domain/` | Pure functions of `docs/instructions/algorithms.md`; `constants.py` holds every constant |
| `app/db/` | DATA: `base.py` (declarative base, naming convention), `enums.py`, `session.py` (sync and async engines, D17), `models/` (one module per schema module) |
| `alembic/` | DATA: migrations; `0001_baseline` creates the whole schema |

Drivers (decisions D17, D18): psycopg 3 for PostgreSQL, PyMongo async for MongoDB.
