# NEX-GEN Platform

NEX-GEN es una plataforma ITOM para operar infraestructura desde una CMDB basada en grafos, telemetria en tiempo real y una consola de eventos orientada a contexto operacional.

## Que resuelve

- Modela CIs, relaciones topologicas y definiciones de metricas sobre Neo4j.
- Recolecta telemetria via SNMP/ICMP y genera eventos con snapshot de contexto de negocio.
- Expone un backend FastAPI y un frontend React para monitoreo, diagnostico y gestion de incidentes.
- Mantiene el feed `/api/events` liviano y usa `GET /api/events/{event_id}` para el detalle enriquecido del modal.

## Arquitectura Rapida

| Capa | Stack | Responsabilidad |
| --- | --- | --- |
| Backend | Python, FastAPI, Pydantic | API, reglas de negocio, enriquecimiento de eventos, auth |
| Frontend | React, Vite, TypeScript, Tailwind | Console, inventario, visualizacion de topologia y modal de detalle |
| Grafo | Neo4j | CIs, relaciones, metricas, BusinessService, ServiceCatalog |
| Series temporales | TimescaleDB / PostgreSQL | Historico de metricas |
| Workers | SNMP / ICMP polling | Ingesta, thresholding y apertura/recuperacion de eventos |

## Flujo de detalle de evento

1. El worker detecta una brecha y crea/actualiza un `Event`.
2. Cuando el evento es nuevo, guarda snapshot de `BusinessService`, `ServiceCatalog`, owners, sitio e SLA.
3. La grilla sigue consultando `/api/events?status=ACTIVE`.
4. Al abrir el modal, el frontend consulta `/api/events/{event_id}`.
5. El backend devuelve `event`, `business_context` e `itsm_context`, priorizando snapshot y usando fallback del grafo para eventos historicos.

## Documentacion Canonica

- [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) - manual del operador: login, consola, eventos, metricas, troubleshooting.
- [`docs/AI_AGENT_GUIDE.md`](docs/AI_AGENT_GUIDE.md) - guia para agentes IA que operan via REST API: permisos, operaciones permitidas, guards y campos restringidos.
- [`docs/backup-restore.md`](docs/backup-restore.md) - runbook de backups pre-rebuild, restore PostgreSQL y limitaciones seguras de Neo4j.
- [`docs/polling-pipeline-runbook.md`](docs/polling-pipeline-runbook.md) - runbook operativo para habilitar, observar, hacer rollback y replay del pipeline escalable de polling.
- [`docs/polling-pipeline-tuning.md`](docs/polling-pipeline-tuning.md) - guia de tuning para workers, leases, batching, cache, DBs y benchmarks del polling pipeline.
- [`docs/snmp-scalable-engine.md`](docs/snmp-scalable-engine.md) - explicacion visual del nuevo motor SNMP escalable, con flujo de leases, result writer y diagrama Mermaid.
- [`docs/supply-chain.md`](docs/supply-chain.md) - politica de dependencias frontend: pnpm/Corepack, lockfile congelado y aprobacion explicita de build scripts.
- [`docs/domain/business-model.md`](docs/domain/business-model.md) - vocabulario de dominio, relaciones `CI -> BusinessService -> ServiceCatalog`, snapshot/fallback y bootstrap manual.
- [`docs/itsm/event-flow.md`](docs/itsm/event-flow.md) - lifecycle del evento, ownership, SLA, escalacion y puntos de integracion Jira/ServiceNow.
- [`docs/reference/modelo_entidad_relacion.md`](docs/reference/modelo_entidad_relacion.md) - referencia tecnica de entidades, relaciones y payloads relevantes.
- [`CONTEXT.md`](CONTEXT.md) - contexto funcional y roadmap del sistema.

## API relevante

### Auth y sesion

- `POST /api/auth/token` - login y emision de cookies de sesion.
- `POST /api/auth/refresh` - rotacion de access/refresh token. Puede devolver `429 Too Many Requests` con header `Retry-After` despues de intentos invalidos repetidos.
- `POST /api/auth/logout` - revoca refresh token y limpia cookies.

### Eventos

- `GET /api/events?status=ACTIVE` - resumen para polling del stream.
- `GET /api/events/{event_id}` - detalle enriquecido para el modal.
- `POST /api/events/{event_id}/ack` - reconocimiento.
- `POST /api/events/{event_id}/comment` - auditoria append-only.
- `POST /api/events/{event_id}/close` - cierre estructurado o forzado.
- `POST /api/events/{event_id}/diagnose` - diagnostico on-demand.

## Setup local

1. Copia variables base: `cp .env.example .env`.
2. Levanta servicios: `docker-compose up -d`.
3. Frontend: `http://localhost:3000`.
4. Backend docs: `http://localhost:8000/docs`.
5. Neo4j Browser: `http://localhost:7474`.

PostgreSQL dentro de Docker siempre debe usar `POSTGRES_HOST=postgres` y `POSTGRES_INTERNAL_PORT=5432`. Si necesitas exponer PostgreSQL en otro puerto del host, configura `POSTGRES_EXTERNAL_PORT=5433`; no uses `POSTGRES_PORT=5433` para servicios internos porque el contenedor PostgreSQL escucha en `5432` dentro de la red Docker.

Backups PostgreSQL/Neo4j y rebuild seguro: Docker Compose no ejecuta automaticamente los scripts de seguridad. Antes de usar `docker compose build` o `docker compose up -d` directamente, el operador debe validar `.env` y crear un backup manualmente.

Flujo recomendado:

1. Actualiza codigo: `git pull origin main`.
2. Revisa y actualiza `.env` usando `.env.example` como referencia.
3. Para rebuild completo seguro, ejecuta `sh scripts/safe-rebuild.sh`; este flujo ya valida `.env`, prepara `BACKUP_DIR`, ejecuta backup, reconstruye y muestra estado.
4. Para backup-only antes de Compose directo, ejecuta `sh scripts/validate-env.sh --check-backup-dir` y luego `sh scripts/pre-rebuild-backup.sh`.
5. Solo si validacion y backup terminaron bien, ejecuta `docker compose build && docker compose up -d`.
6. Verifica con `docker compose ps` y `docker compose logs --tail=100 backend`.

Comandos check-only: `sh scripts/safe-rebuild.sh --dry-run`, `sh -n scripts/*.sh`, `shellcheck -x scripts/*.sh monitor_performance.sh docker/neo4j/entrypoint.sh` y `docker compose config --quiet`. Ejecuta los scripts desde Linux/macOS/Git Bash/WSL, no desde PowerShell. No uses `docker compose down -v` en rebuilds porque elimina volumenes. Ver [`docs/backup-restore.md`](docs/backup-restore.md) para restore, fallback manual y limitaciones de Neo4j Community.

## Tests focalizados

- Desde la raiz del repo:
  - Backend: `python -m pytest backend/tests/test_event_service_smoke.py backend/tests/test_routers_metrics_events.py backend/tests/test_snmp_service_snapshots.py`
  - Frontend: `corepack pnpm --dir frontend run test:run -- hooks/queries/resourceQueries.test.tsx components/__tests__/EventDetailModal.acceptance.test.tsx`

## Local frontend dev (no Docker)

Si querés correr el frontend Vite/React directamente en tu maquina (sin
levantar el stack completo con `docker compose up`), este flujo es para vos.
**`docker compose up` ya cubre el frontend en su contenedor**, asi que no
uses esta guia si vas por Docker: ahi el compose monta `frontend/` y corre
la install adentro.

Pasos resumidos (detalle completo en `frontend/README.md`):

1. Habilita Corepack una vez por maquina: `corepack enable`.
2. Desde la raiz del repo: `corepack pnpm install --frozen-lockfile`.
3. Pre-flight de dependencias (opcional, recomendado): `corepack pnpm --dir frontend run check:deps`.
4. Dev server: `corepack pnpm --dir frontend run dev` (sirve en `http://localhost:3000`).
5. Tests focalizados: `corepack pnpm --dir frontend run test:run`.

Troubleshooting rapido para el error mas comun
(`Failed to resolve import "sonner" from context/AuthContext.tsx`): la
propia dependencia esta declarada en `frontend/package.json` y en el
lockfile, pero falta en `frontend/node_modules`. La causa tipica es no
haber corrido `corepack pnpm install --frozen-lockfile` despues de un
`git pull`. `pnpm run check:deps` detecta esto via el sentinel
`frontend/.frontend-deps-ok` y corre el install automaticamente.

Cuando el frontend corre dentro de Docker (lo normal con `docker compose up`)
y el lockfile cambio pero la imagen ya estaba construida, la propia
`safe-rebuild.sh` detecta el cambio y renueva solo el volumen anonimo de
`frontend /app/node_modules` con
`docker compose up -d --force-recreate --renew-anon-volumes frontend`. Si
necesitas hacerlo a mano despues de un cambio puntual del lockfile, usa
`sh scripts/refresh-frontend-deps.sh` (acepta `--dry-run` para previsualizar).
**No** borres volumenes con `docker compose down -v` ni `docker volume rm`:
esos comandos tambien eliminan datos de PostgreSQL/Neo4j.

## Estado actual

- El modal de detalle ya consume contexto real de negocio e ITSM mediante endpoint dedicado.
- Los eventos nuevos conservan snapshot historico; los viejos siguen funcionando con fallback por relaciones actuales.
- La integracion externa con Jira/ServiceNow sigue pendiente; el contrato ya deja listo el punto de acople.
