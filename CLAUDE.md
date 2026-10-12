# FitPlan Pro

Engineering thesis project (Lublin University of Technology): mobile app for personalized training and diet plans with AI meal photo recognition.

## Stack
- Backend: Python, FastAPI, SQLAlchemy 2.0, Alembic
- Databases: PostgreSQL (persistent relational data), MongoDB (temporary buffer for AI recognition results, TTL cleanup)
- Mobile: React Native (Expo, TypeScript)
- Local environment: docker-compose

## Ownership
- database/, backend/app/db/, backend/alembic/ – Kyryl (data layer)
- backend/app/api/ – Maksym (business logic, API)
- mobile/ – Oleksandr (mobile client)

## Conventions
- PostgreSQL: snake_case table and column names, IDENTITY primary keys, TIMESTAMPTZ for dates
- Never commit .env; use .env.example
- Work on branches (db/, api/, app/), merge to main only via reviewed Pull Requests
- Code comments and identifiers in English; thesis documentation in Polish

## Commands
- Start databases: docker compose up -d
