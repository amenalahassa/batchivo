---
name: deploy-dev
description: Bring the local dev environment up to date with the current code — back up the dev database, review the pending Alembic migrations and their risk, apply them, and print the commands to start the backend and frontend. Use when the user asks to deploy, migrate or refresh the local dev environment, or to "test on dev".
metadata:
  author: batchivo
---

# Deploy to local dev

Brings the **local** dev stack (docker-compose `batchivo-postgres`, `batchivo-redis`, the
FastAPI backend and the Vite frontend) up to date with the code on disk. It never touches
staging or production: those deploy only through Woodpecker CI and ArgoCD (Constitution VII).

Work through the steps in order. Stop and ask the user before any step marked **ASK**. Finish
with the report in step 8, even when an earlier step stopped the run.

## 1. Guard: confirm this is the dev database

- Read `DATABASE_URL` from `backend/.env`. Never print the password.
- Continue only if the host is `localhost`, `127.0.0.1` or `batchivo-postgres`, and `ENVIRONMENT`
  in `backend/.env` is `development`. Otherwise stop and say why.

## 2. Infrastructure up

```bash
docker compose up -d postgres redis
docker ps --filter name=batchivo- --format "{{.Names}} {{.Status}}"
```

Wait until `batchivo-postgres` reports `healthy`. If Redis is not running, say so: the backend
starts without it, but carts, rate limiting and Celery jobs (catalogue scenarios) need it.

## 3. Dependencies

Install only what changed since the last run:

```bash
cd backend && poetry install --extras dev
cd frontend && npm install
```

Run `poetry install` when `backend/poetry.lock` or `backend/pyproject.toml` changed since the
last commit the user deployed, and `npm install` when `frontend/package-lock.json` changed. When
unsure, run both; they are idempotent.

## 4. Migration state

```bash
cd backend
poetry run alembic current
poetry run alembic heads
poetry run alembic history -r current:heads --verbose
```

- If `current` equals `heads`, report "database already at head" and skip to step 7.
- If there is more than one head, stop: the migration graph needs a merge revision, which is a
  code change and not this skill's job.

## 5. Impact review of every pending migration

Open each pending file under `backend/alembic/versions/`. For each one, record:

| Field | What to look for |
|---|---|
| Kind | schema-only (`add_column`, `create_table`, index), **data** (`op.execute` with `UPDATE`/`INSERT`/`DELETE`, `bulk_insert`), **destructive** (`drop_column`, `drop_table`, constraint swap, type change) |
| Computed values | Does it change a figure the cost engine derives: rates, policy rows, fee rules, prices? The constitution requires a per-record delta report for such a migration (`backend/scripts/cost_delta_report.py`); say whether one exists under `specs/*/delta-*.md`. |
| Reversibility | Read `downgrade()`. Flag any that are lossy (for example, the Tier 3 pricing migration collapses price history to the current row on downgrade). |
| Locks and size | Large `UPDATE`s or table rewrites on big tables. On a dev DB this is usually minor; say the row counts. |

Then check for **schema drift** caused by the backend's dev startup. `init_db()` in
`backend/app/database.py` runs `Base.metadata.create_all` when `ENVIRONMENT=development`. If the
backend was started before migrating, it created new tables but no new columns, and the
migration that creates those tables will then fail with "already exists". For every table a
pending migration creates (`op.create_table`), check whether it already exists and how many rows
it holds:

```sql
SELECT to_regclass('public.<table>') IS NOT NULL AS exists;
SELECT count(*) FROM <table>;
```

- Exists and empty: it is a `create_all` artefact. It may be dropped so the migration can create
  it properly (**ASK**, listing the tables).
- Exists with rows: stop. Report the table and its row count, and do not drop it.

Give the user a short risk summary: what changes, which data steps run, what cannot be cleanly
reversed, and what the user will see differently (for example, costs that move by design).

## 6. Backup, then migrate (ASK)

Always take a backup first:

```bash
mkdir -p backups/dev
docker exec batchivo-postgres pg_dump -U batchivo -d batchivo -Fc > backups/dev/batchivo-$(date +%Y%m%d-%H%M%S).dump
```

`backups/` is gitignored. Confirm the file is non-empty.

After the user confirms:

1. Drop any approved `create_all` artefacts from step 5.
2. Run `cd backend && poetry run alembic upgrade head`.
3. Verify: `poetry run alembic current` equals `heads`.

If the upgrade fails, show the error, leave the database as it is, and give the restore command
rather than running it:

```bash
docker exec -i batchivo-postgres pg_restore -U batchivo -d batchivo --clean --if-exists < backups/dev/<file>.dump
```

## 7. Start commands

Print these for the user to run in separate terminals; do not start long-running servers
yourself unless asked:

```bash
# Backend API (http://localhost:8000, docs at /docs)
cd backend && poetry run uvicorn app.main:app --reload

# Frontend (http://localhost:5173)
cd frontend && npm run dev

# Optional: Celery worker, needed for catalogue scenario runs and scheduled tasks
cd backend && poetry run celery -A app.tasks.celery_app worker --loglevel=info
```

Mention that the backend must start **after** migrating (see the drift note in step 5).

## 8. Report

End with:

- migrations applied (revision ids), or "already at head";
- the backup file path;
- risks and visible changes from step 5;
- anything skipped or stopped, and why;
- the start commands from step 7.
