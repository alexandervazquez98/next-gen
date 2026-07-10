# ITSM Service Catalog y Ticket/Folios

El módulo ITSM separa la definición operativa de servicios de la gestión de folios. `ServiceCatalog` es la fuente de verdad para identidad, contexto operativo y SLA; los Ticket/Folios permiten registrar y avanzar solicitudes e incidentes sin alterar los flujos de eventos.

## Ruta rápida

1. Abra **ITSM** en la consola y elija **Service Catalog** (`/itsm/service-catalog`) para administrar servicios, o **Tickets** (`/itsm/tickets`) para operar folios.
2. Cree o actualice un servicio antes de referenciarlo desde un folio. Un folio puede no tener servicio asignado.
3. Cree un folio de tipo `request` o `incident`; comienza en `open`.
4. Aváncelo de a un estado por vez hasta `closed`; el cierre exige una razón.
5. Verifique los contratos focalizados con `python -m pytest backend/tests/test_itsm_service_catalog_service.py backend/tests/test_ticket_folio_service.py backend/tests/test_itsm_startup_checks.py` desde la raíz del repositorio.

## Qué opera este módulo

| Área | Comportamiento actual |
| --- | --- |
| Service Catalog | Registro operacional canónico de servicios y metadatos de SLA. Es independiente del catálogo de inventario. |
| Ticket/Folio | CRUD de solicitudes e incidentes, con referencia opcional a `service_catalog_id`. |
| Integridad | Los IDs de servicio y los `ticket_id` son únicos. Crear un folio con un `ticket_id` existente se rechaza con conflicto. |
| Auditoría | Las escrituras registran el usuario actuante y fechas de creación/actualización. |
| Eventos | No se crean, actualizan ni enlazan folios desde eventos en esta entrega. |

### Service Catalog

Cada servicio usa `service_id` como identidad canónica. El módulo conserva alias compatibles (`id`, `service_tier`, `sla_minutes`) para no romper lecturas existentes de SLA. Los campos operativos incluyen nombre, equipo owner, categoría, tier, criticidad, SLA objetivo y estado activo.

No hay borrado físico: la baja es lógica mediante desactivación. Esto preserva referencias históricas de SLA y separa el módulo ITSM del catálogo de inventario.

### Ticket/Folio

Un folio admite únicamente los tipos `request` e `incident`. `service_catalog_id` es la referencia autoritativa cuando se asigna un servicio; el backend valida que dicho servicio exista. Los folios cerrados son de solo lectura y quedan archivados al cerrarse.

## Lifecycle de folios

El lifecycle es lineal. No se permiten saltos, retrocesos ni reapertura:

```text
open -> in_progress -> in_validation -> resolved -> closed
```

| Regla | Resultado |
| --- | --- |
| Crear folio | Inicia en `open`. |
| Transición | Solo admite el próximo estado de la secuencia. |
| Cerrar | Requiere `closed_reason` y marca el folio como archivado. |
| Editar cerrado | Se rechaza; el folio es de solo lectura. |

La interfaz muestra solo la siguiente transición válida. Para cerrar, solicita la razón de cierre.

## Acceso y rutas

Los endpoints requieren sesión autenticada y permisos ITSM explícitos. El rol de sistema `OPERATOR` recibe `ITSM_VIEW` e `ITSM_EDIT` durante el seed y sus actualizaciones aditivas; `ADMIN` incluye todos los permisos.

| Recurso | Método y ruta | Permiso |
| --- | --- | --- |
| Listar Service Catalog | `GET /api/itsm/service-catalog` | `ITSM_VIEW` |
| Consultar Service Catalog | `GET /api/itsm/service-catalog/{service_id}` | `ITSM_VIEW` |
| Crear Service Catalog | `POST /api/itsm/service-catalog` | `ITSM_EDIT` |
| Actualizar Service Catalog | `PUT /api/itsm/service-catalog/{service_id}` | `ITSM_EDIT` |
| Desactivar Service Catalog | `POST /api/itsm/service-catalog/{service_id}/deactivate` | `ITSM_EDIT` |
| Listar folios | `GET /api/itsm/tickets` | `ITSM_VIEW` |
| Consultar folio | `GET /api/itsm/tickets/{ticket_id}` | `ITSM_VIEW` |
| Crear folio | `POST /api/itsm/tickets` | `ITSM_EDIT` |
| Actualizar folio | `PUT /api/itsm/tickets/{ticket_id}` | `ITSM_EDIT` |
| Transicionar folio | `POST /api/itsm/tickets/{ticket_id}/transition` | `ITSM_EDIT` |

La lista de folios admite los filtros `status`, `service_catalog_id` y `archived`, además de `limit`.

## Arranque, migración y recuperación operacional

Al iniciar, el backend ejecuta las comprobaciones ITSM antes de las migraciones de PostgreSQL. El flujo primero normaliza campos compatibles de `ServiceCatalog`, verifica integridad y luego aplica la migración Neo4j idempotente (constraints e índices).

| Situación | Política de arranque |
| --- | --- |
| IDs canónicos de `ServiceCatalog` duplicados | **Fail-fast**: el arranque se bloquea hasta resolverlos. |
| Nodo de catálogo sin identidad resoluble o con `service_id`/`id` incompatibles | **Fail-fast**: se bloquea para proteger la integridad de identidad. |
| Error operacional en backfill o preflight (por ejemplo, dependencia temporal no disponible) | Se registra la excepción y la API continúa arrancando. |
| Error al aplicar la migración idempotente | Se registra la excepción y la API continúa arrancando. |

La recuperación segura es corregir primero los conflictos de identidad reportados y reiniciar. No se debe resolver un bloqueador eliminando o reescribiendo snapshots de eventos.

## Límites explícitos

- No existe asociación automática entre eventos y Ticket/Folios.
- No se modifica el lifecycle, ownership ni snapshots SLA de eventos.
- No hay integración externa con Jira, ServiceNow u otro ITSM.
- No hay borrado físico de servicios ni folios.

La futura asociación evento-a-folio debe conservar esta separación y usar los IDs estables del catálogo y del folio, sin evitar las validaciones del lifecycle.

## Referencias

- [Propuesta OpenSpec](../../openspec/changes/itsm-service-catalog/proposal.md)
- [Diseño OpenSpec](../../openspec/changes/itsm-service-catalog/design.md)
- [Tareas y evidencia de implementación](../../openspec/changes/itsm-service-catalog/tasks.md)
- [Flujo ITSM de eventos](event-flow.md)
- [Modelo de negocio](../domain/business-model.md)
