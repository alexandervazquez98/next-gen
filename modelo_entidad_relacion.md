# Modelo Entidad-Relacion (NEX-GEN ITOM)

Documento tecnico de referencia para las entidades persistidas y los contratos que hoy alimentan la consola operativa.

## 1. Neo4j / Grafo operacional

### `Node` / `CI`

| Campo | Tipo | Notas |
| --- | --- | --- |
| `id` | `str` | Identificador canonico del CI |
| `label` | `str` | Nombre visible |
| `type` | `str` | Categoria base |
| `status` | `str` | Estado general |
| `ip` | `str?` | Hostname/IP |
| `locationName` | `str?` | Sitio legible |
| `metadata` | `dict?` | Fallback transitorio, no fuente canonica del modal |
| `owner` | `str?` | Grupo responsable legacy |
| `brand`, `model`, `serialNumber`, `firmwareVersion` | `str?` | Inventario |

### `MetricDef`

| Campo | Tipo | Notas |
| --- | --- | --- |
| `id` | `str` | Identificador de metrica |
| `protocol` | `str` | SNMP, ICMP, HTTP, etc. |
| `oid` | `str?` | OID o referencia tecnica |
| `warning`, `critical` | `float?` | Umbrales |
| `operator` | `str?` | `>=`, `<=`, `==`, `!=` |
| `criticality` | `int?` | Mapeo base a severidad |
| `applicable_to` | `dict?` | Reglas de aplicabilidad |

### `BusinessService`

| Campo | Tipo | Notas |
| --- | --- | --- |
| `id` | `str` | Identificador del servicio |
| `name` | `str` | Nombre de negocio |
| `tier` | `str?` | Tier operativo opcional |
| `owner_t1` | `str?` | Responsable esperado T1 |
| `owner_t2` | `str?` | Responsable esperado T2 |
| `owner_t3` | `str?` | Responsable esperado T3 |
| `impacted_users_count` | `int?` | Magnitud estimada de impacto |

### `ServiceCatalog`

| Campo | Tipo | Notas |
| --- | --- | --- |
| `id` | `str` | Identificador del SLA/catálogo |
| `category` | `str` | Categoria funcional del servicio |
| `service_tier` | `str?` | Tier opcional para segmentar el SLA |
| `sla_minutes` | `int?` | Objetivo de tiempo |

### `Event`

| Campo | Tipo | Notas |
| --- | --- | --- |
| `id` | `str` | Identificador del evento |
| `ci_id` | `str` | Referencia canonica al CI |
| `metric_id` | `str` | Metrica detonante |
| `status` | `str` | `OPEN`, `ACK`, `RECOVERED`, `CLOSED` |
| `severity` | `str` | `CRITICAL`, `WARNING`, `INFO` |
| `message` | `str` | Mensaje operativo |
| `created_at` | `datetime` | Apertura |
| `last_seen` | `datetime?` | Ultima observacion |
| `ack`, `ack_at`, `ack_by` | `bool/datetime/str?` | Ownership actual |
| `closed_at`, `closed_by`, `recovered_at` | `datetime/str?` | Cierre/recuperacion |
| `comments` | `list[str]?` | Timeline append-only |
| `business_service_id` | `str?` | Snapshot |
| `business_service_name` | `str?` | Snapshot |
| `business_service_tier` | `str?` | Snapshot |
| `owner_t1`, `owner_t2`, `owner_t3` | `str?` | Snapshot |
| `impacted_users` | `int?` | Snapshot |
| `site` | `str?` | Snapshot |
| `service_catalog_id` | `str?` | Snapshot |
| `service_category` | `str?` | Snapshot |
| `service_tier` | `str?` | Snapshot |
| `sla_minutes` | `int?` | Snapshot |

## 2. Relaciones relevantes

| Relacion | Origen | Destino | Proposito |
| --- | --- | --- | --- |
| `HAS_METRIC` | `CI` | `MetricDef` | Asignacion de metrica |
| `HAS_EVENT` | `CI` | `Event` | Eventos abiertos / historicos |
| `TRIGGERED_BY` | `Event` | `MetricDef` | Metrica que disparo el evento |
| `BELONGS_TO` | `CI` | `BusinessService` | Mapeo de negocio |
| `USES_SLA` | `BusinessService` | `ServiceCatalog` | SLA esperado |
| `DEPENDS_ON`, `HOSTED_ON`, `CONNECTS_TO` | `CI` | `CI` | Topologia |

## 3. Contratos API relevantes

### Resumen (`GET /api/events`)

- Mantiene payload liviano para polling.
- Sigue exponiendo `ci_node_id` por compatibilidad legacy.
- NO incluye `business_context` ni `itsm_context`.

### Detalle (`GET /api/events/{event_id}`)

```json
{
  "event": {
    "id": "evt-001",
    "ci_id": "ci-001",
    "ci_ref": {
      "id": "ci-001",
      "label": "Router-01",
      "hostname": "10.0.0.1",
      "location_name": "Madrid HQ"
    }
  },
  "business_context": {
    "source": "snapshot|resolved|mixed|unavailable",
    "business_service": { "id": "svc-001", "name": "Corp-WAN" },
    "service_catalog": { "id": "sla-001", "category": "NETWORK", "sla_minutes": 60 },
    "impacted_users": 350,
    "sla_remaining_minutes": 25,
    "site": "Madrid HQ"
  },
  "itsm_context": {
    "assignment_state": "unassigned|assigned",
    "assigned_to": null,
    "opened_by": "system",
    "escalation_tier": "T1|T2|T3|null",
    "external_ticket": null
  }
}
```

## 4. Identificadores normalizados

- `ci_ref.id` es el identificador canonico del CI en el endpoint de detalle.
- `ci_id` sigue siendo la referencia del evento al CI.
- `ci_node_id` queda relegado al resumen por compatibilidad con consumidores existentes.

## 5. Persistencia relacional

### TimescaleDB / PostgreSQL

- `metric_values(time, node_id, metric_id, value)` mantiene historico de telemetria.

### IAM / PostgreSQL

- `users` mantiene credenciales, permisos, ubicaciones y `tier` operativo del usuario autenticado.

## 6. Lecturas relacionadas

- `README.md`
- `docs/domain/business-model.md`
- `docs/itsm/event-flow.md`
