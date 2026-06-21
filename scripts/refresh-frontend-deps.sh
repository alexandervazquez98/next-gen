#!/bin/sh
# Manual operator recovery for stale dev frontend dependencies.
#
# Why this exists
#   The dev `frontend` service bind-mounts source code into /app and
#   keeps /app/node_modules as an anonymous Docker volume for hot reload.
#   When frontend/pnpm-lock.yaml changes, the anonymous volume can mask
#   freshly built image dependencies. This script gives operators a
#   single-purpose command that recreates the frontend container with a
#   fresh anonymous volume WITHOUT touching data volumes, the database,
#   or any other service.
#
# What it does
#   Runs exactly one docker compose command:
#     docker compose up -d --force-recreate --renew-anon-volumes frontend
#   The --renew-anon-volumes flag is intentionally scoped to the
#   `frontend` service so other (future) anonymous volumes stay intact.
#
# Usage
#   sh scripts/refresh-frontend-deps.sh [--dry-run]
#
# Notes
#   - This script NEVER runs `docker compose down -v` or `docker volume rm`.
#   - It accepts only `--dry-run` and `-h|--help`. Any other flag is
#     rejected with usage on stderr and exit 2.

set -eu

usage() {
    cat <<'USAGE'
Usage: sh scripts/refresh-frontend-deps.sh [--dry-run]

Refreshes the dev frontend anonymous node_modules volume by recreating the
frontend container with a fresh anonymous volume. Scoped to the `frontend`
service only; does not delete data or backup volumes.

Options:
  --dry-run   Print the command that would run, without executing Docker.
  -h, --help  Show this help and exit.

This script intentionally does NOT support flags such as --skip-neo4j.
Its only responsibility is the frontend anonymous-volume renewal.
USAGE
}

dry_run=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --dry-run)
            dry_run=1
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

require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        printf 'Missing required command: %s\n' "$1" >&2
        exit 1
    fi
}

compose() {
    docker compose "$@"
}

run() {
    printf '+ %s\n' "$*"
    if [ "$dry_run" -eq 0 ]; then
        "$@"
    fi
}

require_command docker

printf 'Refreshing dev frontend anonymous node_modules volume...\n'
run docker compose up -d --force-recreate --renew-anon-volumes frontend
printf '\nFrontend dependencies refresh complete. Verify with: docker compose ps frontend\n'
printf 'Avoid destructive volume deletion commands such as: docker compose down -v\n'