#!/bin/sh
set -eu

usage() {
    cat <<'USAGE'
Usage: sh scripts/safe-rebuild.sh [--dry-run] [--skip-neo4j] [--neo4j-offline]

Safely bootstraps backup storage, creates a pre-rebuild backup, rebuilds images,
and restarts services without deleting Docker volumes.

Options:
  --dry-run        Print the deploy flow without creating directories or changing containers.
  --skip-neo4j     Pass through to pre-rebuild-backup.sh to skip the Neo4j backup.
  --neo4j-offline  Pass through to pre-rebuild-backup.sh to run a Neo4j offline dump.
USAGE
}

dry_run=0
skip_neo4j=0
offline_neo4j=0

while [ "$#" -gt 0 ]; do
    case "$1" in
        --dry-run)
            dry_run=1
            ;;
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

require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        printf 'Missing required command: %s\n' "$1" >&2
        exit 1
    fi
}

run() {
    printf '+ %s\n' "$*"
    if [ "$dry_run" -eq 0 ]; then
        "$@"
    fi
}

compose() {
    docker compose "$@"
}

normalize_backup_dir_for_check() {
    printf '%s\n' "$1" | awk '
        {
            gsub(/\\\\/, "/")
            gsub(/\/\/+/, "/")
            absolute = ($0 ~ /^\//)
            n = split($0, parts, "/")
            depth = 0

            for (i = 1; i <= n; i++) {
                part = parts[i]
                if (part == "" || part == ".") {
                    continue
                }
                if (part == "..") {
                    if (depth > 0 && stack[depth] != "..") {
                        delete stack[depth]
                        depth--
                    } else if (!absolute) {
                        depth++
                        stack[depth] = part
                    }
                    continue
                }
                depth++
                stack[depth] = part
            }

            normalized = absolute ? "/" : ""
            for (i = 1; i <= depth; i++) {
                normalized = normalized (i == 1 || normalized == "/" ? "" : "/") stack[i]
            }
            sub(/\/+$/, "", normalized)
            print normalized
        }
    '
}

refuse_unsafe_backup_dir() {
    backup_dir=$1
    normalized=$(normalize_backup_dir_for_check "$backup_dir")

    case "$normalized" in
        ''|/|.|..|/tmp|/tmp/*|/private/tmp|/private/tmp/*|/var/tmp|/var/tmp/*)
            printf 'ERROR: refusing unsafe BACKUP_DIR: %s\n' "$backup_dir" >&2
            printf 'Choose a durable app-owned directory such as .docker/backups.\n' >&2
            exit 1
            ;;
    esac
}

ensure_host_backup_dir() {
    backup_dir=$1

    if [ "$dry_run" -eq 1 ]; then
        printf '+ mkdir -p %s\n' "$backup_dir"
        printf '+ verify host BACKUP_DIR is writable: %s\n' "$backup_dir"
        return
    fi

    mkdir -p "$backup_dir"

    if [ ! -d "$backup_dir" ]; then
        printf 'ERROR: BACKUP_DIR is not a directory: %s\n' "$backup_dir" >&2
        exit 1
    fi

    if [ ! -w "$backup_dir" ]; then
        printf 'ERROR: BACKUP_DIR is not writable: %s\n' "$backup_dir" >&2
        exit 1
    fi

    test_file="$backup_dir/.safe-rebuild-write-test.$$"
    if ! : > "$test_file"; then
        printf 'ERROR: could not write to BACKUP_DIR: %s\n' "$backup_dir" >&2
        exit 1
    fi
    rm -f "$test_file"
}

verify_container_backups() {
    service_name=$1

    if [ "$dry_run" -eq 1 ]; then
        printf '+ docker compose exec -T %s sh -c verify /backups is writable\n' "$service_name"
        return
    fi

    compose exec -T "$service_name" sh -c '
        set -eu
        test -d /backups
        test -w /backups
        test_file="/backups/.safe-rebuild-write-test.$$"
        : > "$test_file"
        rm -f "$test_file"
    '
}

if [ "${SAFE_REBUILD_LIB_ONLY:-0}" = "1" ]; then
    return 0 2>/dev/null || {
        printf 'ERROR: SAFE_REBUILD_LIB_ONLY is only supported when sourcing this script for tests.\n' >&2
        exit 2
    }
fi

require_command docker

printf 'Validating .env without creating secrets...\n'
backup_dir=$(sh scripts/validate-env.sh --print-backup-dir)
refuse_unsafe_backup_dir "$backup_dir"

printf 'Resolved BACKUP_DIR: %s\n' "$backup_dir"
ensure_host_backup_dir "$backup_dir"

printf 'Validating Docker Compose configuration...\n'
run docker compose config --quiet

printf 'Applying backup mounts without rebuilding or deleting volumes...\n'
run docker compose up -d --no-build postgres neo4j backend

printf 'Verifying /backups inside containers...\n'
verify_container_backups postgres
verify_container_backups neo4j
verify_container_backups backend

printf 'Creating pre-rebuild backup...\n'
if [ "$skip_neo4j" -eq 1 ]; then
    run sh scripts/pre-rebuild-backup.sh --skip-neo4j
elif [ "$offline_neo4j" -eq 1 ]; then
    run sh scripts/pre-rebuild-backup.sh --neo4j-offline
else
    run sh scripts/pre-rebuild-backup.sh
fi

printf 'Building and restarting services...\n'
run docker compose build
run docker compose up -d

printf 'Applying ICMP latency/jitter sidecar migration...\n'
run docker compose exec -T backend python scripts/migrate_icmp_sidecar_metrics.py

printf '\nSafe rebuild flow completed. Current service status:\n'
run docker compose ps

cat <<'NEXT'

Next verification:
1. Confirm the PostgreSQL dump exists in BACKUP_DIR.
2. Confirm Neo4j has an APOC export, an offline dump directory, or an offline-dump-required note.
3. Check backend/frontend health in the browser or API.
4. Do not run docker compose down -v, docker volume rm, or delete data directories.
NEXT
