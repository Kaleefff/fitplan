# FitPlan Pro

Mobile application for training and nutrition planning (engineering thesis, Lublin University of Technology).

## Structure

- `backend/` – FastAPI application
- `database/` – PostgreSQL schema, MongoDB init, seed data
- `mobile/` – React Native (Expo) application
- `docs/instructions/` – requirements, decisions, algorithms, API rules, tasks, setup

## Getting started

`cp .env.example .env`, set passwords, `docker compose up -d`. Details and troubleshooting: [docs/instructions/setup.md](docs/instructions/setup.md).

## Workflow

Rules for people and agents are in [CLAUDE.md](CLAUDE.md); the work plan is [docs/instructions/tasks.md](docs/instructions/tasks.md).
