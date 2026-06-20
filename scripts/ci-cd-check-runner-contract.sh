#!/bin/sh
# Runner contract validator for the CD lane.
#
# Invoked as the FIRST step of .github/workflows/cd.yml on the production
# self-hosted runner (labels: self-hosted, linux, x64, production,
# next-gen, cd). If this script exits non-zero, the CD job fails loud —
# the runner is misconfigured and a deploy must NOT proceed.
#
# Contract (per openspec/changes/ci-cd-pipeline/specs/ci-cd-pipeline/spec.md
# R8, R10, and design.md "Self-hosted runner labels"):
#   1. docker                — command must be on PATH
#   2. Docker Compose v2     — `docker compose version` reports v2.x
#   3. .env                  — present in the runner workdir
#   4. BACKUP_DIR            — set, exists, writable by the runner user
#   5. gh auth status        — gh CLI installed and authenticated
#
# Library mode: when sourced with RUNNER_CONTRACT_LIB_ONLY=1 the script
# returns early without running the contract. This mirrors the
# SAFE_REBUILD_LIB_ONLY pattern used by scripts/test-safe-rebuild-* tests
# and lets the test script source shared helpers if they are ever
# extracted. (Currently no helpers are exported; this is a forward-
# compatible hook.)

set -eu

if [ "${RUNNER_CONTRACT_LIB_ONLY:-0}" = "1" ]; then
    # shellcheck disable=SC2317
    return 0 2>/dev/null || {
        printf 'ERROR: RUNNER_CONTRACT_LIB_ONLY is only supported when sourcing this script for tests.\n' >&2
        exit 2
    }
fi

failures=0

fail() {
    printf 'ERROR: %s\n' "$1" >&2
    failures=$((failures + 1))
}

# 1. docker on PATH.
if ! command -v docker >/dev/null 2>&1; then
    fail 'docker is not installed (see docs/self-hosted-runner.md#prerequisites).'
fi

# 2. Docker Compose v2 plugin. The v1 standalone binary (docker-compose,
#    hyphen) is rejected because we need the v2 subcommand syntax
#    (`docker compose ...`). The presence of the v2 subcommand itself
#    is the test; we then parse the major version and require >= 2.
if command -v docker >/dev/null 2>&1; then
    if ! docker compose version >/dev/null 2>&1; then
        fail 'docker compose v2 plugin is required (the v2 subcommand `docker compose` failed). Install the docker-compose-plugin.'
    else
        compose_version_output=$(docker compose version 2>/dev/null || printf '')
        major=$(printf '%s' "$compose_version_output" | sed -n 's/.*[Vv]ersion[[:space:]]*v\?\([0-9]\+\).*/\1/p')
        if [ -z "$major" ] || [ "$major" -lt 2 ] 2>/dev/null; then
            fail "Docker Compose v2 or later required (got: ${compose_version_output})."
        fi
    fi
fi

# 3. .env present in the runner workdir. safe-rebuild.sh reads it via
#    scripts/validate-env.sh; without it the deploy step fails anyway,
#    but failing here gives a cleaner error.
if [ ! -f .env ]; then
    fail ".env not found in $(pwd). Copy .env.example to .env and populate production secrets."
fi

# 4. BACKUP_DIR set, exists, writable.
if [ -z "${BACKUP_DIR:-}" ]; then
    fail 'BACKUP_DIR is not set. Export BACKUP_DIR in the runner environment or set it in .env.'
else
    if [ ! -d "$BACKUP_DIR" ]; then
        fail "BACKUP_DIR does not exist: $BACKUP_DIR. Run: mkdir -p $BACKUP_DIR"
    elif [ ! -w "$BACKUP_DIR" ]; then
        fail "BACKUP_DIR is not writable: $BACKUP_DIR. Fix ownership: chown -R runner:runner $BACKUP_DIR"
    else
        test_file="$BACKUP_DIR/.runner-contract-write-test.$$"
        if ! : > "$test_file" 2>/dev/null; then
            fail "Could not write to BACKUP_DIR: $BACKUP_DIR"
        else
            rm -f "$test_file"
        fi
    fi
fi

# 5. gh CLI authenticated. The cd-failure issue step needs to post as
#    the workflow bot via GITHUB_TOKEN, which gh picks up automatically
#    when GITHUB_TOKEN is in the env. We also check gh auth status so
#    manual ops (operator-driven deploys from the runner host) keep
#    working.
if ! command -v gh >/dev/null 2>&1; then
    fail 'gh CLI is not installed. See https://cli.github.com/manual/installation.'
elif ! gh auth status >/dev/null 2>&1; then
    fail 'gh is not authenticated. Run: gh auth login (or set GITHUB_TOKEN).'
fi

if [ "$failures" -gt 0 ]; then
    printf '\nRunner contract failed (%d issue(s)). Fix the runner before retrying.\n' "$failures" >&2
    exit 1
fi

printf 'Runner contract OK (docker, compose v2, .env, BACKUP_DIR, gh).\n'
