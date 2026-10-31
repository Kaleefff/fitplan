# Local setup

This guide gets the project's databases running on your machine. Follow the steps in order.

## Requirements

- Git
- Docker Desktop, running (wait for "Engine running")
- VS Code; accept the prompt to install the recommended extensions
- Windows: use the Git Bash terminal in VS Code (Terminal → dropdown next to + → Git Bash)
- uv (Python package manager): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"` in PowerShell, then restart the terminal

## 1. Clone the repo

```bash
git clone https://github.com/Kaleefff/fitplan.git
cd fitplan
```

## 2. Create your `.env`

```bash
cp .env.example .env
```

Open `.env` and set your own passwords. Docker Compose reads only `.env`, never `.env.example`.
`.env` is in `.gitignore` and must never be committed. Check with `git check-ignore .env`; it should print `.env`.
Set `JWT_SECRET` as well (the command is in the comment above it); without it login and registration fail.

## 3. Start the services and create the schema

```bash
docker compose up -d --build
docker compose ps
```

After about 15 seconds `fitplan-postgres`, `fitplan-mongo` and `fitplan-backend` should show `healthy`, and `fitplan-mailpit` should be up.

The PostgreSQL schema is created by the Alembic migrations, and the reference data (muscle groups, injury types, allergens, food categories) by the seed loader:

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run python -m app.db.seed
cd ..
```

The loader can be run any time; a second run reports every row as `unchanged`.

## 4. Check that it works

Replace the user and password with the values from your `.env`.

```bash
docker exec fitplan-postgres psql -U fitplan -d fitplan -c "\dt"
docker exec fitplan-mongo mongosh -u fitplan -p YOUR_PASSWORD --authenticationDatabase admin --quiet --eval "db.getSiblingDB('fitplan').meal_recognitions.getIndexes()"
```

Expected: 36 tables plus `alembic_version`, and 3 indexes on `meal_recognitions` (`_id_`, `expiresAt_1`, `userId_1_status_1`).

The backend and the mail catcher:

```bash
curl http://localhost:8000/api/v1/health
```

Expected: `postgres` and `mongo` are `ok`. The Mailpit inbox (mails sent by the backend, e.g. password reset) is at http://localhost:8025.

## 5. Connect from tools

| Tool                      | Settings                                                                         |
| ------------------------- | -------------------------------------------------------------------------------- |
| DBeaver (PostgreSQL)      | Host `localhost`, port `5432`, database `fitplan`, user and password from `.env` |
| MongoDB Compass / mongosh | `mongodb://USER:PASSWORD@localhost:27017/?authSource=admin`                      |

## Daily use

| Command                                | What it does                                       |
| -------------------------------------- | -------------------------------------------------- |
| `docker compose up -d`                 | Start all services in the background               |
| `docker compose up -d --build backend` | Rebuild the backend after pulling backend changes  |
| `docker compose stop`                  | Stop them; data is kept                            |
| `docker compose down`                  | Remove the containers; data is kept in volumes     |
| `docker compose down -v`               | Remove the containers **and all data**             |
| `docker compose logs backend`          | Show a service's log (`postgres`, `mongo`, `mailpit` too) |

To run the backend with `uv run uvicorn` instead, stop the container first (`docker compose stop backend`) or change `BACKEND_PORT`, since both use port 8000.

## After the schema changes

The schema is managed by Alembic (`backend/alembic/`) and the reference data by `database/seed/`. After pulling, apply new migrations and seed changes:

```bash
cd backend
uv run alembic upgrade head
uv run python -m app.db.seed
```

To change the schema (DATA): edit the models in `backend/app/db/models/`, then run `uv run alembic revision --autogenerate -m "short description"`, review the generated file, and run `uv run alembic upgrade head`. `uv run alembic check` reports whether the models and the database still differ.

One-time switch (DB-01): a database created by the old `database/init/01_schema.sql` has no Alembic history. Reset it, which deletes local data:

```bash
docker compose down -v
docker compose up -d
cd backend && uv run alembic upgrade head
```

## Git workflow

- Never commit to `main`; it is protected.
- `git switch main && git pull`, then a branch named by task: `db/DB-02-reference-seeds`, `api/B-03-auth`, `app/M-04-login`, `docs/...`.
- Small commits with clear messages; push the branch and open a Pull Request. Someone else reviews and merges it (`CLAUDE.md`).
