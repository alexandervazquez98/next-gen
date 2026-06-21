#!/bin/sh
set -eu

usage() {
    cat <<'USAGE'
Usage: sh scripts/validate-env.sh [--check-backup-dir] [--print-backup-dir]

Validates that .env contains every variable declared in .env.example without
sourcing either file. Optionally validates the resolved BACKUP_DIR for deploys.

Options:
  --check-backup-dir  Fail if the resolved BACKUP_DIR does not exist or is not writable.
  --print-backup-dir  Print the resolved BACKUP_DIR to stdout after validation.
USAGE
}

check_backup_dir=0
print_backup_dir=0

while [ "$#" -gt 0 ]; do
    case "$1" in
        --check-backup-dir)
            check_backup_dir=1
            ;;
        --print-backup-dir)
            print_backup_dir=1
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

failures=0

fail() {
    printf 'ERROR: %s\n' "$1" >&2
    failures=$((failures + 1))
}

warn() {
    printf 'WARN: %s\n' "$1" >&2
}

trim_value() {
    printf '%s\n' "$1" | awk '
        {
            sub(/\r$/, "")
            sub(/^[[:space:]]+/, "")
            sub(/[[:space:]]+$/, "")
            if ($0 ~ /^".*"$/) {
                sub(/^"/, "")
                sub(/"$/, "")
            } else if ($0 ~ /^'\''.*'\''$/) {
                sub(/^'\''/, "")
                sub(/'\''$/, "")
            }
            print
        }
    '
}

env_value() {
    file=$1
    key=$2

    awk -v key="$key" '
        /^[[:space:]]*(#|$)/ { next }
        {
            sub(/\r$/, "")
            line = $0
            sub(/^[[:space:]]*export[[:space:]]+/, "", line)
            if (line ~ "^[[:space:]]*" key "[[:space:]]*=") {
                sub("^[[:space:]]*" key "[[:space:]]*=", "", line)
                sub(/^[[:space:]]+/, "", line)
                sub(/[[:space:]]+$/, "", line)
                if (line ~ /^".*"$/) {
                    sub(/^"/, "", line)
                    sub(/"$/, "", line)
                } else if (line ~ /^'\''.*'\''$/) {
                    sub(/^'\''/, "", line)
                    sub(/'\''$/, "", line)
                }
                print line
                exit
            }
        }
    ' "$file"
}

env_names() {
    file=$1

    awk '
        /^[[:space:]]*(#|$)/ { next }
        {
            sub(/\r$/, "")
            line = $0
            sub(/^[[:space:]]*export[[:space:]]+/, "", line)
            if (match(line, /^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*[[:space:]]*=/)) {
                name = substr(line, RSTART, RLENGTH)
                sub(/=.*/, "", name)
                sub(/^[[:space:]]+/, "", name)
                sub(/[[:space:]]+$/, "", name)
                print name
            }
        }
    ' "$file" | sort -u
}

has_env_name() {
    file=$1
    key=$2

    awk -v key="$key" '
        /^[[:space:]]*(#|$)/ { next }
        {
            sub(/\r$/, "")
            line = $0
            sub(/^[[:space:]]*export[[:space:]]+/, "", line)
            if (line ~ "^[[:space:]]*" key "[[:space:]]*=") {
                found = 1
                exit
            }
        }
        END { exit found ? 0 : 1 }
    ' "$file"
}

is_sensitive_var() {
    case "$1" in
        JWT_SECRET_KEY|POSTGRES_PASSWORD|NEO4J_PASSWORD|SECRET|*_SECRET|*_SECRET_KEY|*_PASSWORD|*_TOKEN|*_API_KEY)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

is_unsafe_sensitive_value() {
    key=$1
    value=$2
    lowered=$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')

    case "$lowered" in
        password|changeme|change-me|change_me|secret|default|example|example-secret|your-secret|your_secret|yourstrongpassword|replace-me|replace_me|todo|test|admin|nexgen_password|neo4j|jwt_secret_key|jwt-secret-key)
            return 0
            ;;
        *changeme*|*change-me*|*replace-me*|*placeholder*|*example*|*default*|*yourstrongpassword*)
            return 0
            ;;
    esac

    case "$key" in
        JWT_SECRET_KEY)
            [ "${#value}" -lt 32 ] && return 0
            ;;
        POSTGRES_PASSWORD|NEO4J_PASSWORD)
            [ "${#value}" -lt 12 ] && return 0
            ;;
    esac

    return 1
}

resolve_backup_dir() {
    if [ "${BACKUP_DIR+x}" ]; then
        if [ "$BACKUP_DIR" ]; then
            printf '%s\n' "$BACKUP_DIR"
        else
            printf '%s\n' '.docker/backups'
        fi
        return
    fi

    if [ -f .env ]; then
        value=$(env_value .env BACKUP_DIR)
        value=$(trim_value "$value")
        if [ "$value" ]; then
            # Expand a leading ~ or ~/ to $HOME so the value is usable as a
            # path. ~/foo expands to /home/<user>/foo; ~user/foo would
            # require getent — not supported here, fall through to tilde-
            # literal path which the caller will see as missing.
            case "$value" in
                "~") value=$HOME ;;
                "~/"*) value=$HOME/${value#"~/"} ;;
            esac
            printf '%s\n' "$value"
            return
        fi
    fi

    printf '%s\n' '.docker/backups'
}

validate_backup_dir() {
    backup_dir=$1

    if [ ! -d "$backup_dir" ]; then
        fail "BACKUP_DIR does not exist: $backup_dir. Create it first, for example: mkdir -p $backup_dir"
        return
    fi

    if [ ! -w "$backup_dir" ]; then
        fail "BACKUP_DIR is not writable: $backup_dir"
        return
    fi

    test_file="$backup_dir/.validate-env-write-test"
    if ! : > "$test_file"; then
        fail "Could not write to BACKUP_DIR: $backup_dir"
        return
    fi
    rm -f "$test_file"
}

validate_postgres_ports() {
    [ -f .env ] || return

    postgres_host=$(env_value .env POSTGRES_HOST)
    postgres_host=$(trim_value "$postgres_host")
    [ "$postgres_host" ] || postgres_host=postgres

    postgres_internal_port=$(env_value .env POSTGRES_INTERNAL_PORT)
    postgres_internal_port=$(trim_value "$postgres_internal_port")
    [ "$postgres_internal_port" ] || postgres_internal_port=5432

    if [ "$postgres_host" = "postgres" ] && [ "$postgres_internal_port" != "5432" ]; then
        fail "POSTGRES_INTERNAL_PORT must be 5432 when POSTGRES_HOST=postgres; use POSTGRES_EXTERNAL_PORT for the host published port."
    fi

    if has_env_name .env POSTGRES_PORT; then
        postgres_port=$(env_value .env POSTGRES_PORT)
        postgres_port=$(trim_value "$postgres_port")
        if [ "$postgres_host" = "postgres" ] && [ "$postgres_port" ] && [ "$postgres_port" != "5432" ]; then
            fail "POSTGRES_PORT=$postgres_port looks like a host/external port, but POSTGRES_HOST=postgres requires internal port 5432. Use POSTGRES_EXTERNAL_PORT=$postgres_port instead."
        fi
    fi
}

if [ ! -f .env.example ]; then
    fail '.env.example is missing; cannot validate the environment contract.'
fi

if [ ! -f .env ]; then
    fail '.env is missing. Copy .env.example to .env and fill production-safe values before deploy/rebuild.'
fi

if [ -f .env.example ] && [ -f .env ]; then
    env_names .env.example | while IFS= read -r key; do
        [ "$key" ] || continue

        if ! has_env_name .env "$key"; then
            printf 'ERROR: .env is missing variable from .env.example: %s\n' "$key" >&2
            exit 10
        fi

        value=$(env_value .env "$key")
        value=$(trim_value "$value")

        if is_sensitive_var "$key"; then
            if [ -z "$value" ]; then
                printf 'ERROR: sensitive variable is empty in .env: %s\n' "$key" >&2
                exit 10
            fi

            # Catch copied .env.example secrets after safe parse/trim/unquote; never log values.
            example_value=$(env_value .env.example "$key")
            example_value=$(trim_value "$example_value")
            if [ "$value" = "$example_value" ]; then
                printf 'ERROR: sensitive variable still matches .env.example placeholder: %s\n' "$key" >&2
                exit 10
            fi

            if is_unsafe_sensitive_value "$key" "$value"; then
                printf 'ERROR: sensitive variable appears unsafe/default in .env: %s\n' "$key" >&2
                exit 10
            fi
        elif [ -z "$value" ]; then
            warn "optional/dev variable is present but empty in .env: $key"
        fi
    done || failures=$((failures + 1))
fi

backup_dir=$(resolve_backup_dir)
validate_postgres_ports
if [ "$check_backup_dir" -eq 1 ]; then
    validate_backup_dir "$backup_dir"
fi

if [ "$failures" -gt 0 ]; then
    printf '\nEnvironment validation failed. Update .env from .env.example before deploy/rebuild.\n' >&2
    exit 1
fi

printf 'Environment validation passed.\n' >&2

if [ "$print_backup_dir" -eq 1 ]; then
    printf '%s\n' "$backup_dir"
fi
