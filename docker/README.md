# `docker/` host-side state

This directory holds the **host-side bind-mount source paths** used by
`docker-compose.yml` (dev) and `docker-compose.prod.yml` (production
overlay). It is intentionally empty by default — runtime data is
written into it by the containers, never by the repo.

| Path | Mounted at | Owner in container | Notes |
|---|---|---|---|
| `postgres/data/` | `postgres:/var/lib/postgresql/data` | UID 999 (postgres) | gitignored; `.gitkeep` documents the R1 mitigation |
| `neo4j/data/`    | `neo4j:/data`            | UID 7474 (neo4j)   | gitignored; created lazily by compose on first run |
| `neo4j/logs/`    | `neo4j:/logs`            | UID 7474 (neo4j)   | gitignored; created lazily by compose on first run |

## R1 mitigation — `postgres/data/`

The compose bind-mount `./docker/postgres/data:/var/lib/postgresql/data`
fails on engines that refuse to auto-create the source directory. The
smoke workflow (`.github/workflows/smoke.yml`) does
`mkdir -p docker/postgres/data` before `docker compose up` to keep
runs deterministic on GitHub-hosted runners.

For local development you can either:

- let Docker auto-create the path (works on most engines ≥ 20.10), OR
- run `mkdir -p docker/postgres/data` once before `docker compose up`.

## R1 status

Documented and mitigated in PR5 of ci-cd-pipeline. See
`openspec/changes/ci-cd-pipeline/design.md` (R1) and
`.github/workflows/smoke.yml` (the `mkdir -p` step).
