# next-gen Project Context

next-gen is a NOC/CMDB operational system for monitoring, events, metrics, availability, authentication, and operator UI.

## Stack

- Backend: Python, FastAPI, Pydantic, SQLAlchemy, Neo4j, PostgreSQL/TimescaleDB, polling workers.
- Frontend: React, TypeScript, Vite, Tailwind, Vitest.
- Local services: Docker Compose for backend dependencies and operational stack.

## SDD/TDD Policy

Use strict TDD when tests exist or can be reasonably created. If automated tests are not reasonable for a change, document manual evidence in the SDD verify phase.

## Detected Test Commands

- Frontend install: `cd frontend && corepack pnpm install --frozen-lockfile`
- Frontend test: `cd frontend && corepack pnpm test:run`
- Frontend watch: `cd frontend && corepack pnpm test`
- Backend install: `cd backend && python -m pip install -r requirements.txt -r requirements-dev.txt`
- Backend test: `cd backend && python -m pytest`

## Notes for Later SDD Phases

- Do not implement GitHub issue work during init.
- Keep proposed changes within the configured 400 changed-line review budget unless the user approves a delivery split.
- Store SDD artifacts under `openspec/`.
