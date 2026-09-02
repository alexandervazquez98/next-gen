# syntax=docker/dockerfile:1.4
#
# BuildKit cache mounts (#453 slice 2):
#   /var/cache/apt — survives across rebuilds so apt-get update does not
#     re-download the apt index when an unrelated file changes.
#   /root/.cache/pip — pip writes downloaded wheels here so partial
#     requirement changes only re-download the delta.
#
# See backend/Dockerfile for the same pattern. Two pip-install RUN steps
# (one for backend requirements, one for engine requirements) share the
# same /root/.cache/pip mount with sharing=locked so concurrent builds
# don't corrupt partial writes.
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for networking and postgres.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    iputils-ping \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install backend dependencies (includes sqlalchemy, psycopg2).
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    pip install -r requirements.txt

# Install engine specific dependencies.
COPY engines/requirements.txt requirements-engine.txt
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    pip install -r requirements-engine.txt

# Copy Codebases
COPY . /app/backend
COPY engines /app/engines

# Set Python Path to backend so 'from repositories ...' works
ENV PYTHONPATH=/app/backend

CMD ["python", "-u", "engines/snmp_worker.py"]
