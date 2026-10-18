# FitPlan Pro

Mobile application for training and nutrition planning (engineering thesis, Lublin University of Technology).

## Structure

- `backend/` – FastAPI application (Python)
- `database/` – PostgreSQL schema and seed data
- `mobile/` – React Native (Expo) application

## Local setup

1. `cp .env.example .env`
2. `docker compose up -d`

## Workflow

Branch from `main` using a prefix (`db/`, `api/`, `app/`), open a Pull Request, get one approval, merge.

## Getting started

See [docs/instructions/setup.md](docs/instructions/setup.md) for local setup and troubleshooting.
