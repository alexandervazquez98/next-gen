#!/bin/sh
set -eu

usage() {
    cat <<'USAGE'
Usage: sh scripts/pre-rebuild-backup.sh [--skip-neo4j]

Creates a pre-rebuild PostgreSQL dump and attempts a safe Neo4j online export.
The script never runs destructive Docker commands and never removes volumes.

Options:
  --skip-neo4j  Only create the PostgreSQL dump.
USAGE
}

skip_neo4j=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --skip-neo4j)
            skip_neo4j=1
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
  docker compose stop neo4j
  docker compose run --rm --no-deps --entrypoint neo4j-admin neo4j database dump neo4j --to-path=/backups --overwrite-destination=true
  docker compose up -d neo4j
NOTE
}

require_command docker

printf 'Validating .env and BACKUP_DIR before backup...\n'
backup_dir=$(sh scripts/validate-env.sh --check-backup-dir --print-backup-dir)
timestamp=$(date -u '+%Y%m%d_%H%M%S')
postgres_file="postgres_${timestamp}.dump"
neo4j_file="neo4j_${timestamp}.cypher"
neo4j_note="neo4j_${timestamp}_offline-dump-required.txt"

printf 'Validating Docker Compose configuration...\n'
compose config >/dev/null
printf 'Validated BACKUP_DIR: %s\n' "$backup_dir"

require_running_service postgres

printf 'Creating PostgreSQL dump: /backups/%s\n' "$postgres_file"
compose exec -T postgres sh -c '
    set -eu
    : "${POSTGRES_USER:?POSTGRES_USER is required}"
    : "${POSTGRES_DB:?POSTGRES_DB is required}"
    : "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
    PGPASSWORD=$POSTGRES_PASSWORD pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f "$1"
' sh "/backups/$postgres_file"

if [ "$skip_neo4j" -eq 1 ]; then
    printf 'Skipping Neo4j export by request.\n'
else
    require_running_service neo4j

    printf 'Attempting Neo4j online APOC export: /backups/%s\n' "$neo4j_file"
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
