# CLI Contract: VPS Operations

## Host CLI: `deploy/vps/batchivo` (POSIX sh, run by the provider in the bundle directory)

| Command | Effect | Exit codes |
|---------|--------|-----------|
| `install` | checks docker + compose, `.env` present with mode 600 (fixes it), required vars set; `compose pull`; `compose up -d`; waits for `/health` | 0 ok · 2 missing prerequisite or variable (each listed) · 3 health timeout |
| `init --shop-name NAME --owner-email EMAIL [--support-email EMAIL]` | runs `python -m app.ops.init` in the backend container | 0 ok · 4 already initialised (nothing changed) · 1 other error |
| `update VERSION` | backup check → backup → pin `VERSION` → pull → migrate → up → health → report; rollback on migration failure | 0 updated · 5 backup failed (nothing changed) · 6 migration failed (rolled back to previous version; backup key printed) · 3 health timeout after update · 2 `VERSION` missing or `latest` |
| `backup` | `python -m app.ops.backup run` then `prune` | 0 · 5 |
| `restore KEY` | stops backend, restores the dump, runs `alembic upgrade head`, starts backend | 0 · 1 |
| `status` | version, mode, container health, last backup, `.env` permissions, email domain status | 0 healthy · 1 degraded |

All commands print a final one-line result: `OK <command> <details>` or `FAILED <command> <reason>`.

## Python operations: `python -m app.ops.<module>` (inside the backend image)

### `app.ops.init`

Args: `--shop-name`, `--owner-email`, `--support-email` (optional), `--currency` (default `GBP`).
Steps: `alembic upgrade head`; refuse with exit 4 if any tenant or user exists; create tenant
(`tenant_type = three_d_print`), OWNER membership, optional support membership
(`is_support = true`, role ADMIN); send password-set emails (print the links when email is not
yet verified); print the DNS records the email provider needs for the sender domain.

### `app.ops.backup`

| Sub-command | Effect |
|-------------|--------|
| `check` | writes and deletes a probe object in the bucket; exit 5 on failure |
| `run` | `pg_dump` → gzip → upload (key and metadata in data-model §5); writes `last_backup.json` |
| `prune` | deletes objects older than `BACKUP_RETENTION_DAYS`, always keeps the newest |
| `restore KEY` | download → `psql` into an emptied database |
| `schedule` | long-running: daily at `BACKUP_SCHEDULE_HOUR` UTC runs `run` + `prune`; failures logged and sent to Sentry |
