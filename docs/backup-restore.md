# Backup And Restore Runbook

Use this runbook before Docker rebuilds or releases. Docker Compose commands do not auto-run the safety scripts. Operators must run the validation and backup scripts manually before any direct rebuild or deploy command.

## Quick Path

1. Update code on the deploy host: `git pull origin main` or checkout the intended release branch/tag.
2. Review `.env` against `.env.example` and add any new required values.
3. Run `sh scripts/safe-rebuild.sh` for the full safe rebuild flow.
4. Verify services with `docker compose ps` and confirm backend, frontend, snmp-engine, PostgreSQL, and Neo4j health checks are healthy.
5. Confirm backup files exist under `BACKUP_DIR`, default `.docker/backups`.

Do not run `docker compose down -v` as part of rebuilds. That deletes named volumes and can destroy database state.

### Data volumes vs build-artifact volumes

Safe rebuilds deliberately distinguish **data volumes** from **build-artifact volumes**. Treat them differently:

| Volume kind | Example | Safe-rebuild behavior | Operator recovery |
| --- | --- | --- | --- |
| Data volume (bind mount or named) | `postgres` data, `neo4j` data, `BACKUP_DIR` mount | Preserved across every rebuild | Never run `docker compose down -v`, `docker volume rm`, or delete data directories. |
| Build-artifact anonymous volume | Dev `frontend /app/node_modules` | Renewed automatically by `safe-rebuild.sh` when `frontend/pnpm-lock.yaml` changes | Run `sh scripts/refresh-frontend-deps.sh` to renew only the `frontend` anonymous volume without rebuilding images. |

If a stale `node_modules` symptom appears after a `safe-rebuild.sh` (for example `Failed to resolve import "sonner" from context/AuthContext.tsx`), do not delete volumes. Use the narrow recovery path:

```sh
sh scripts/refresh-frontend-deps.sh        # actual renew
sh scripts/refresh-frontend-deps.sh --dry-run  # preview only
```

The `frontend-prod` service has no anonymous volume, so the renew flag is a no-op for production. `--renew-anon-volumes` is intentionally scoped to the `frontend` service so it never reaches data volumes.

Run the scripts from Linux/macOS/Git Bash/WSL, not PowerShell. On Windows PowerShell, use Git Bash or WSL for the safe rebuild command.

## Manual Deploy Flow

Choose one of these paths after pulling code. Do not skip validation and backup when you run Docker Compose directly.

### Full Safe Rebuild

Use this path when you want the script to validate `.env`, create the backup directory when safe, run backups, rebuild, restart, and show service status.

```sh
git pull origin main
# Review/update .env from .env.example before continuing.
sh scripts/safe-rebuild.sh
# Or, during a Neo4j maintenance window when APOC export is unavailable:
# sh scripts/safe-rebuild.sh --neo4j-offline
docker compose ps
docker compose logs --tail=100 backend
```

`safe-rebuild.sh` already handles the backup directory checks that `sh scripts/validate-env.sh --check-backup-dir` performs in the manual backup-only flow.

### Backup-Only Then Direct Compose

Use this path only when you need to run Docker Compose commands yourself.

```sh
git pull origin main
# Review/update .env from .env.example before continuing.
sh scripts/validate-env.sh --check-backup-dir
sh scripts/pre-rebuild-backup.sh
docker compose build
docker compose up -d
docker compose ps
docker compose logs --tail=100 backend
```

Run `docker compose build` and `docker compose up -d` only after validation and backup succeed. Docker Compose does not call `validate-env.sh`, `pre-rebuild-backup.sh`, or `safe-rebuild.sh` for you.

## Check-Only Commands

Use these before a deploy when you want to inspect the scripts and Compose config without changing containers:

```sh
sh scripts/safe-rebuild.sh --dry-run
sh -n scripts/*.sh
shellcheck -x scripts/*.sh monitor_performance.sh docker/neo4j/entrypoint.sh
docker compose config --quiet
```

## Environment Gate

For the recommended deploy path, `scripts/safe-rebuild.sh` runs this validation before it creates the backup directory. For manual validation, run:

```sh
sh scripts/validate-env.sh --check-backup-dir
```

The validator is intentionally conservative for production-sensitive values:

| Check | Behavior |
| --- | --- |
| `.env.example` vs `.env` | Fails when `.env` is missing any variable declared in `.env.example`, which catches stale deploy env files after new config is added. |
| Safe parsing | Reads assignments as text and never sources `.env` or `.env.example`, so arbitrary shell code is not executed. |
| Sensitive values | Fails empty or obvious placeholder/default values for secrets and passwords such as `JWT_SECRET_KEY`, `POSTGRES_PASSWORD`, and `NEO4J_PASSWORD`. |
| PostgreSQL ports | Fails when `POSTGRES_HOST=postgres` is paired with an internal port other than `5432`; host exposure belongs in `POSTGRES_EXTERNAL_PORT`. |
| Dev-only values | Warns, rather than fails, for empty non-sensitive values to avoid making local/dev config brittle. |
| `BACKUP_DIR` | Resolves shell env first, then `.env`, then `.docker/backups`; with `--check-backup-dir`, fails if the directory does not exist or is not writable. |

The validator does not create directories or secrets. If it fails, update `.env` from `.env.example`, replace placeholder secrets with real values, or create the backup directory explicitly for manual use.

## Safe Rebuild Flow

Run this manually after updating code on the deploy host. Docker Compose direct commands do not trigger it automatically:

```sh
sh scripts/safe-rebuild.sh
```

The script performs the deploy preflight and rebuild in order:

| Step | Behavior |
| --- | --- |
| Env validation | Runs `scripts/validate-env.sh --print-backup-dir` without sourcing `.env` or creating secrets. |
| Host backup dir | Refuses unsafe values such as `/`, `/tmp`, `/var/tmp`, or empty paths, then creates the resolved directory when safe. |
| Compose validation | Runs `docker compose config --quiet`. |
| Mount application | Runs `docker compose up -d --no-build postgres neo4j backend` so existing containers pick up `/backups` without deleting volumes. |
| Container verification | Verifies `/backups` exists and is writable in `postgres`, `neo4j`, and `backend`. |
| Backup and rebuild | Runs `scripts/pre-rebuild-backup.sh`, then `docker compose build`, then `docker compose up -d`. |

Use `sh scripts/safe-rebuild.sh --dry-run` to print the flow without creating directories, rebuilding images, or restarting containers. The dry run still validates `.env` and resolves `BACKUP_DIR`.

Use `sh scripts/safe-rebuild.sh --neo4j-offline` only during a maintenance window. It still creates the PostgreSQL dump, but it passes `--neo4j-offline` to `pre-rebuild-backup.sh`, which stops only Neo4j, runs a `neo4j-admin` dump, and starts Neo4j again before the rebuild continues.

## Manual Fallback

Use this only when you need to run each step by hand. Unlike `safe-rebuild.sh`, `pre-rebuild-backup.sh` stays strict and expects `BACKUP_DIR` to already exist. Docker Compose direct commands do not auto-run these safety checks.

```sh
sh scripts/validate-env.sh --print-backup-dir
mkdir -p .docker/backups
sh scripts/validate-env.sh --check-backup-dir
docker compose config --quiet
docker compose up -d --no-build postgres neo4j backend
docker compose exec -T postgres sh -c 'test -d /backups && test -w /backups'
docker compose exec -T neo4j sh -c 'test -d /backups && test -w /backups'
docker compose exec -T backend sh -c 'test -d /backups && test -w /backups'
sh scripts/pre-rebuild-backup.sh
docker compose build
docker compose up -d
docker compose ps
```

If `BACKUP_DIR` is customized, create and validate that resolved path instead of `.docker/backups`. Refuse volatile or overly broad paths such as `/`, `/tmp`, `/var/tmp`, and their subdirectories.

## What The Script Does

| Area | Behavior |
| --- | --- |
| `BACKUP_DIR` | Resolves shell env first, then `.env`, then `.docker/backups`; validates that the resolved host directory exists and is writable before dumping. |
| Env validation | Calls `scripts/validate-env.sh --check-backup-dir` before Docker Compose checks or dumps. In the recommended flow, `scripts/safe-rebuild.sh` creates and verifies the directory before this strict check runs. |
| PostgreSQL | Runs `pg_dump -Fc` inside the `postgres` service using the container environment. |
| Neo4j | Attempts an online APOC Cypher export when `apoc.export.cypher.all` is available. |
| Neo4j fallback | Writes an operator note explaining `sh scripts/pre-rebuild-backup.sh --neo4j-offline` when online export is unavailable. |
| Neo4j offline mode | With `--neo4j-offline`, stops only Neo4j, creates a timestamped `neo4j_YYYYMMDD_HHMMSS_dump/` directory under `BACKUP_DIR`, runs `neo4j-admin database dump`, and starts Neo4j again. |
| Docker safety | Uses `docker compose config`, `ps`, and `exec`; the default path never stops services or removes volumes. Offline Neo4j mode stops and restarts only `neo4j` during the maintenance window. |

Generated files use UTC timestamps, for example `postgres_20260524_153000.dump`.

## PostgreSQL Restore

Use this when restoring PostgreSQL from a dump. Choose the exact dump file from `BACKUP_DIR`.

This is destructive to the target database. Stop backend and worker services before the restore so they cannot write during `dropdb`, then restart them only after you verify the restore.

```sh
docker compose stop backend snmp-engine
docker compose exec -T postgres sh -c 'dropdb -U "$POSTGRES_USER" "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
docker compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists "$1"' sh /backups/postgres_YYYYMMDD_HHMMSS.dump
docker compose exec -T postgres sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
docker compose up -d backend snmp-engine
```

Confirm the target environment before running it. If verification fails, do not restart backend or workers until the database state is understood.

## Neo4j Online Export Restore

If the script created `neo4j_YYYYMMDD_HHMMSS.cypher`, restore it into an empty or disposable Neo4j target with:

```sh
docker compose exec -T neo4j sh -c '
  neo4j_user=${NEO4J_AUTH%%/*}
  neo4j_password=${NEO4J_AUTH#*/}
  cypher-shell -u "$neo4j_user" -p "$neo4j_password" -f "$1"
' sh /backups/neo4j_YYYYMMDD_HHMMSS.cypher
```

This replay can duplicate data if the target is not empty. Use it for a clean restore target unless you have reviewed the Cypher content.

## Neo4j Offline Dump Workflow

Neo4j Community/dev images do not provide Enterprise online backup. A full `neo4j-admin database dump` is an offline maintenance action.

Run this only when you intentionally accept a Neo4j service interruption:

```sh
sh scripts/pre-rebuild-backup.sh --neo4j-offline
# Or as part of the full rebuild flow:
sh scripts/safe-rebuild.sh --neo4j-offline
```

The offline mode:

1. Creates the normal PostgreSQL dump first.
2. Stops only the `neo4j` service.
3. Creates a timestamped `neo4j_YYYYMMDD_HHMMSS_dump/` directory under `BACKUP_DIR`.
4. Runs:

   ```sh
   docker compose run --rm --no-deps --entrypoint neo4j-admin neo4j database dump neo4j --to-path=/backups/neo4j_YYYYMMDD_HHMMSS_dump --overwrite-destination=true
   ```

5. Starts `neo4j` again even when the dump command fails.

After the command completes, confirm the dump directory exists under `BACKUP_DIR`, then check Neo4j health with `docker compose ps` and application smoke tests.

Restore an offline dump into a stopped, empty Neo4j data directory only after separately preserving the current data directory:

```sh
docker compose stop neo4j
docker compose run --rm --no-deps --entrypoint neo4j-admin neo4j database load neo4j --from-path=/backups/neo4j_YYYYMMDD_HHMMSS_dump --overwrite-destination=true
docker compose up -d neo4j
```

Do not delete `docker/neo4j/data` unless you have an explicit, tested restore plan and a separate copy of the current data.

## Pre-Release Checklist

- [ ] `sh scripts/safe-rebuild.sh` completed successfully from a POSIX shell.
- [ ] PostgreSQL dump exists in `BACKUP_DIR`.
- [ ] Neo4j has an APOC export file, an offline dump directory, or an offline-dump-required note.
- [ ] No command uses `docker compose down -v`.
