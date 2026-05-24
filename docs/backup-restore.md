# Backup And Restore Runbook

Use this runbook before Docker rebuilds or releases. The safe path validates `.env`, verifies the backup directory, creates a PostgreSQL dump, and attempts a Neo4j online export without deleting containers, volumes, or data directories.

## Quick Path

1. Update code on the deploy host: `git pull` or checkout the intended release branch/tag.
2. Compare and validate env: `sh scripts/validate-env.sh --check-backup-dir`.
3. If validation says `BACKUP_DIR` is missing, create the host directory, for example: `mkdir -p ./docker/backups`.
4. Run the safety backup: `sh scripts/pre-rebuild-backup.sh`.
5. Rebuild and restart safely: `docker compose build && docker compose up -d`.
6. Verify services: `docker compose ps` and check the frontend/backend health in the browser or API.

Do not run `docker compose down -v` as part of rebuilds. That deletes named volumes and can destroy database state.

On Windows PowerShell, create the default backup directory with `New-Item -ItemType Directory -Force -Path .\docker\backups`, then run validation and backup from Git Bash or WSL. The scripts expect POSIX shell syntax; PowerShell is only shown here for directory creation.

## Environment Gate

Run this before every deploy/rebuild:

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
| `BACKUP_DIR` | Resolves shell env first, then `.env`, then `./docker/backups`; with `--check-backup-dir`, fails if the directory does not exist or is not writable. |

The validator does not create directories or secrets. If it fails, update `.env` from `.env.example`, replace placeholder secrets with real values, or create the backup directory explicitly.

## What The Script Does

| Area | Behavior |
| --- | --- |
| `BACKUP_DIR` | Resolves shell env first, then `.env`, then `./docker/backups`; validates that the resolved host directory exists and is writable before dumping. |
| Env validation | Calls `scripts/validate-env.sh --check-backup-dir` before Docker Compose checks or dumps. |
| PostgreSQL | Runs `pg_dump -Fc` inside the `postgres` service using the container environment. |
| Neo4j | Attempts an online APOC Cypher export when `apoc.export.cypher.all` is available. |
| Neo4j fallback | Writes an operator note explaining the offline dump command when online export is unavailable. |
| Docker safety | Uses `docker compose config`, `ps`, and `exec`; it never stops services or removes volumes. |

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

## Neo4j Full Dump Limitation

Neo4j Community/dev images do not provide Enterprise online backup. A full `neo4j-admin database dump` is an offline maintenance action.

Run this only when you intentionally accept a Neo4j service interruption:

```sh
docker compose stop neo4j
docker compose run --rm --no-deps --entrypoint neo4j-admin neo4j database dump neo4j --to-path=/backups --overwrite-destination=true
docker compose up -d neo4j
```

Restore an offline dump into a stopped, empty Neo4j data directory only after separately preserving the current data directory:

```sh
docker compose stop neo4j
docker compose run --rm --no-deps --entrypoint neo4j-admin neo4j database load neo4j --from-path=/backups --overwrite-destination=true
docker compose up -d neo4j
```

Do not delete `docker/neo4j/data` unless you have an explicit, tested restore plan and a separate copy of the current data.

## Pre-Release Checklist

- [ ] `BACKUP_DIR` exists on the host and is writable.
- [ ] `sh scripts/validate-env.sh --check-backup-dir` passes after updating code.
- [ ] `sh scripts/pre-rebuild-backup.sh` completed successfully from a POSIX shell.
- [ ] PostgreSQL dump exists in `BACKUP_DIR`.
- [ ] Neo4j has either an APOC export file or an offline-dump-required note.
- [ ] Rebuild uses `docker compose build && docker compose up -d`.
- [ ] No command uses `docker compose down -v`.
