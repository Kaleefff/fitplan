# Local setup

This guide gets the project's databases running on your machine. Follow the steps in order.

## Requirements

- Git
- Docker Desktop, running (wait for "Engine running")
- VS Code; accept the prompt to install the recommended extensions
- Windows: use the Git Bash terminal in VS Code (Terminal → dropdown next to + → Git Bash)

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

## 3. Start the databases

```bash
docker compose up -d
docker compose ps
```

After about 15 seconds both `fitplan-postgres` and `fitplan-mongo` should show `healthy`.
On the first start, PostgreSQL runs `database/init/01_schema.sql` and MongoDB runs `database/mongo-init/01_meal_recognitions.js` automatically.

## 4. Check that it works

Replace the user and password with the values from your `.env`.

```bash
docker exec fitplan-postgres psql -U fitplan -d fitplan -c "\dt"
docker exec fitplan-mongo mongosh -u fitplan -p YOUR_PASSWORD --authenticationDatabase admin --quiet --eval "db.getSiblingDB('fitplan').meal_recognitions.getIndexes()"
```

Expected: 26 tables, and 3 indexes on `meal_recognitions`.

## 5. Connect from tools

| Tool                      | Settings                                                                         |
| ------------------------- | -------------------------------------------------------------------------------- |
| DBeaver (PostgreSQL)      | Host `localhost`, port `5432`, database `fitplan`, user and password from `.env` |
| MongoDB Compass / mongosh | `mongodb://USER:PASSWORD@localhost:27017/?authSource=admin`                      |

## Daily use

| Command                        | What it does                                   |
| ------------------------------ | ---------------------------------------------- |
| `docker compose up -d`         | Start the databases in the background          |
| `docker compose stop`          | Stop them; data is kept                        |
| `docker compose down`          | Remove the containers; data is kept in volumes |
| `docker compose down -v`       | Remove the containers **and all data**         |
| `docker compose logs postgres` | Show the Postgres log (same for `mongo`)       |

## After the schema changes

Init scripts run only when the data volume is empty. After pulling a new version of `01_schema.sql`, reset the databases:

```bash
docker compose down -v
docker compose up -d
```

This deletes all local data. Only use it while the databases hold test data. |

## Git workflow

- Never commit directly to `main`.
- Before starting work: `git switch main`, `git pull`, then create a branch: `db/...` (Kyryl), `api/...` (Max), `app/...` (Alex).
- Commit small steps with clear messages and push your branch.
- Open a Pull Request on GitHub. Another team member reviews it before it is merged.
