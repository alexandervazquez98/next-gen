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
- [`docs/domain/business-model.md`](docs/domain/business-model.md) - vocabulario de dominio, relaciones `CI -> BusinessService -> ServiceCatalog`, snapshot/fallback y bootstrap manual.
- [`docs/itsm/event-flow.md`](docs/itsm/event-flow.md) - lifecycle del evento, ownership, SLA, escalacion y puntos de integracion Jira/ServiceNow.
- [`docs/reference/modelo_entidad_relacion.md`](docs/reference/modelo_entidad_relacion.md) - referencia tecnica de entidades, relaciones y payloads relevantes.
- [`CONTEXT.md`](CONTEXT.md) - contexto funcional y roadmap del sistema.

## API relevante

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

Backups PostgreSQL: `BACKUP_DIR` define la ruta del host (`./docker/backups` si no se configura otro valor). Dentro del contenedor la ruta persistente es fija: `/backups`. La configuracion guardada de backups solo puede usar `/backups` o subrutas como `/backups/daily`; cualquier ruta fuera de ese mount se normaliza a `/backups` para no escribir en almacenamiento efimero del contenedor.

## Tests focalizados

- Desde la raiz del repo:
  - Backend: `python -m pytest backend/tests/test_event_service_smoke.py backend/tests/test_routers_metrics_events.py backend/tests/test_snmp_service_snapshots.py`
  - Frontend: `pnpm --dir frontend run test:run -- hooks/queries/resourceQueries.test.tsx components/__tests__/EventDetailModal.acceptance.test.tsx`

## Estado actual

- El modal de detalle ya consume contexto real de negocio e ITSM mediante endpoint dedicado.
- Los eventos nuevos conservan snapshot historico; los viejos siguen funcionando con fallback por relaciones actuales.
- La integracion externa con Jira/ServiceNow sigue pendiente; el contrato ya deja listo el punto de acople.
