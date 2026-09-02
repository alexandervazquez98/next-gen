#!/bin/sh
set -eu

usage() {
    cat <<'USAGE'
Usage: sh scripts/pre-rebuild-backup.sh [--skip-neo4j] [--neo4j-offline]

Creates a pre-rebuild PostgreSQL dump and attempts a safe Neo4j backup.
The script never runs destructive Docker commands and never removes volumes.

Options:
  --skip-neo4j      Only create the PostgreSQL dump.
  --neo4j-offline   Stop only Neo4j, run a neo4j-admin dump, then restart Neo4j.
USAGE
}

skip_neo4j=0
offline_neo4j=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --skip-neo4j)
            skip_neo4j=1
            ;;
        --neo4j-offline)
            offline_neo4j=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage >&2
            exit 2
            ;;
    esac
    shift
done

if [ "$skip_neo4j" -eq 1 ] && [ "$offline_neo4j" -eq 1 ]; then
    printf 'ERROR: --skip-neo4j and --neo4j-offline cannot be used together.\n' >&2
    exit 2
fi

compose() {
    docker compose "$@"
}

require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        printf 'Missing required command: %s\n' "$1" >&2
        exit 1
    fi
}

require_running_service() {
    service_name=$1
    container_id=$(compose ps -q "$service_name")
    if [ -z "$container_id" ]; then
        printf 'Service is not running: %s\n' "$service_name" >&2
        printf 'Start services with docker compose up -d before running this backup.\n' >&2
        exit 1
    fi
}

write_neo4j_limitation_note() {
    note_path=$1
    cat > "$note_path" <<'NOTE'
Neo4j online export was not created because APOC export is unavailable or not enabled.

Neo4j Community/dev images do not provide Enterprise online backup. A full
neo4j-admin database dump is an offline maintenance action: stop only the Neo4j
service explicitly, run the dump, then start Neo4j again. Do not use docker
compose down -v.

Operator command during a maintenance window:
  sh scripts/pre-rebuild-backup.sh --neo4j-offline
NOTE
}

run_neo4j_offline_dump() {
    dump_dir_name=$1
    dump_host_dir=$backup_dir/$dump_dir_name

    printf 'Stopping Neo4j for offline dump maintenance window...\n'
    if ! compose stop neo4j; then
        printf 'ERROR: could not stop Neo4j; offline dump was not attempted.\n' >&2
        exit 1
    fi

    if ! mkdir -p "$dump_host_dir"; then
        printf 'ERROR: could not create Neo4j dump directory: %s\n' "$dump_host_dir" >&2
        printf 'Restarting Neo4j before exiting.\n' >&2
        compose up -d neo4j
        exit 1
    fi

    printf 'Creating Neo4j offline dump under /backups/%s\n' "$dump_dir_name"
    if compose run --rm --no-deps --entrypoint neo4j-admin neo4j \
        database dump neo4j \
        --to-path="/backups/$dump_dir_name" \
        --overwrite-destination=true; then
        printf 'Neo4j offline dump created under: %s\n' "$dump_host_dir"
        dump_status=0
    else
        printf 'ERROR: Neo4j offline dump failed. Restarting Neo4j before exiting.\n' >&2
        dump_status=1
    fi

    printf 'Restarting Neo4j after offline dump attempt...\n'
    compose up -d neo4j

    if [ "$dump_status" -ne 0 ]; then
        exit "$dump_status"
    fi
}

if [ "${PRE_REBUILD_BACKUP_LIB_ONLY:-0}" = "1" ]; then
    # shellcheck disable=SC2317
    return 0 2>/dev/null || {
        printf 'ERROR: PRE_REBUILD_BACKUP_LIB_ONLY is only supported when sourcing this script for tests.\n' >&2
        exit 2
    }
fi

require_command docker

printf 'Validating .env and BACKUP_DIR before backup...\n'
backup_dir=$(sh scripts/validate-env.sh --check-backup-dir --print-backup-dir)
timestamp=$(date -u '+%Y%m%d_%H%M%S')
postgres_file="postgres_${timestamp}.dump"
neo4j_file="neo4j_${timestamp}.cypher"
neo4j_dump_dir="neo4j_${timestamp}_dump"
neo4j_note="neo4j_${timestamp}_offline-dump-required.txt"

printf 'Validating Docker Compose configuration...\n'
compose config >/dev/null
printf 'Validated BACKUP_DIR: %s\n' "$backup_dir"

require_running_service postgres

printf 'Creating PostgreSQL dump: /backups/%s\n' "$postgres_file"
# NOTE on expected warnings: TimescaleDB's `_timescaledb_catalog.hypertable`,
# `_timescaledb_catalog.chunk`, and `_timescaledb_catalog.continuous_agg`
# tables form circular foreign-key relationships by design. `pg_dump` is
# conservative and emits:
#   pg_dump: warning: there are circular foreign-key constraints on this table
#   pg_dump: detail: hypertable / chunk / continuous_agg
# on every dump against a Timescale-backed database. The dumps are
# correct, restorable, and unaffected by this artefact. The
# `--disable-triggers` hint in the warning only applies to a schema-only
# restore on an empty database; the standard data+schema restore used
# here is untouched. If you need to silence these warnings in operator
# logs, pipe the dump's stderr through `2>&1 | grep -v 'circular
# foreign-key constraints on this table'` or wrap the pg_dump call
# accordingly; do NOT suppress them globally — they are the only signal
# that proves pg_dump read the schema successfully. See issue #453.
# shellcheck disable=SC2016
compose exec -T postgres sh -c '
    set -eu
    : "${POSTGRES_USER:?POSTGRES_USER is required}"
    : "${POSTGRES_DB:?POSTGRES_DB is required}"
    : "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
    PGPASSWORD=$POSTGRES_PASSWORD pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f "$1"
' sh "/backups/$postgres_file"

if [ "$skip_neo4j" -eq 1 ]; then
    printf 'Skipping Neo4j export by request.\n'
elif [ "$offline_neo4j" -eq 1 ]; then
    run_neo4j_offline_dump "$neo4j_dump_dir"
else
    require_running_service neo4j

    printf 'Attempting Neo4j online APOC export: /backups/%s\n' "$neo4j_file"
    # shellcheck disable=SC2016
    if compose exec -T neo4j sh -c '
        set -eu
        : "${NEO4J_AUTH:?NEO4J_AUTH is required}"
        neo4j_user=${NEO4J_AUTH%%/*}
        neo4j_password=${NEO4J_AUTH#*/}
        if cypher-shell -u "$neo4j_user" -p "$neo4j_password" \
            "SHOW PROCEDURES YIELD name WHERE name = '\''apoc.export.cypher.all'\'' RETURN count(*) AS available" \
            | grep -q "1"; then
            cypher-shell -u "$neo4j_user" -p "$neo4j_password" \
                "CALL apoc.export.cypher.all(\"$1\", {format: \"cypher-shell\"}) YIELD file RETURN file"
        else
            exit 42
        fi
    ' sh "/backups/$neo4j_file"; then
        printf 'Neo4j APOC export created: /backups/%s\n' "$neo4j_file"
    else
        note_path="$backup_dir/$neo4j_note"
        write_neo4j_limitation_note "$note_path"
        printf 'Neo4j APOC export unavailable; wrote operator note: %s\n' "$note_path"
    fi
fi

printf '\nPre-rebuild backup completed. Files are under: %s\n' "$backup_dir"
printf 'Safe rebuild command: sh scripts/safe-rebuild.sh\n'
printf 'Avoid destructive volume deletion commands such as: docker compose down -v\n'
