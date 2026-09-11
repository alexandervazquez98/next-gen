# syntax=docker/dockerfile:1.4
#
# BuildKit cache mounts (#453 slice 2):
#   /var/cache/apt — survives across rebuilds so apt-get update does not
#     re-download the apt index when an unrelated file changes.
#   /root/.cache/pip — pip writes downloaded wheels here, so when
#     `requirements.txt` changes and only a few new wheels are needed,
#     pip does not re-download everything.
#
# `sharing=locked` mirrors across concurrent build steps on the same cache
# directory without corrupting partial writes. BuildKit is enabled by
# default in Docker 20.10+; the `# syntax=` directive at the top ensures
# the `--mount=type=cache` flag is recognised by older Docker versions
# too.
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./

# Install OS tools used by health checks, backups, and pg_dump.
# postgresql-client provides pg_dump for backup-service tests
# (see issue #474 test-infra unblock).
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    apt-get update \
    && apt-get install -y --no-install-recommends iputils-ping postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Note: pip's `--no-cache-dir` flag (previously set here) is removed because
# it disables the cache mount above. With the mount, BuildKit owns pip's
# cache lifecycle and writes only happen when wheels change.
# requirements-dev.txt installs testcontainers[postgres] + pytest plugins
# needed for the full backend pytest suite to run inside this image
# (issue #474 test-infra unblock).
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    pip install -r requirements.txt -r requirements-dev.txt

COPY engines /app/engines
COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
