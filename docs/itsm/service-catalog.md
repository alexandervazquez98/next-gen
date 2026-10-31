# Catálogo de servicios con UX ITIL

El formulario de creación y edición del catálogo de servicios usa vocabularios controlados, responsables definidos, identificadores estables y una unidad de SLA explícita. Esto reduce los rechazos por datos inconsistentes y aplica las prácticas de ITIL Service Portfolio Management, Service Design y Service Operation.

## Flujo rápido

1. Abre **ITSM → Service Catalog** y selecciona **Create Service Catalog**.
2. Completa los campos controlados. El backend genera el `service_id`; no se escribe manualmente.
3. El SLA se introduce con su unidad; la UI lo convierte a minutos antes de enviarlo.
4. Al guardar, la API responde `201` y la pantalla muestra el `service_id` asignado en modo de solo lectura.
5. En modo de edición, el `service_id` existente permanece visible y no se puede modificar.

## Contrato de campos

| Campo | Control en la UI | Fuente o regla | Contrato persistido |
|---|---|---|---|
| `service_id` | Solo lectura después de crear | Generado por el backend como `sc-{slug}-{nanoid}` | Identificador inmutable |
| `value_stream` | Desplegable | `GET /api/dictionaries?key=value_stream&active=true` | Debe ser un valor activo del diccionario gestionado |
| `owner_team` | Desplegable | `GET /api/owners` | Grupo propietario existente |
| `category` | Desplegable | `GET /api/categories` | Taxonomía canónica de servicio |
| `tier` | Desplegable | `GET /api/dictionaries?key=tier&active=true` | `bronze`, `silver`, `gold` o `platinum` |
| `criticality` | Desplegable | `GET /api/dictionaries?key=criticality&active=true` | `low`, `medium`, `high` o `critical` |
| `sla_target_minutes` | Número + unidad | `minutes`, `hours` o `days`; `hours` es la unidad inicial | Siempre un entero en minutos |

El contrato de API continúa usando `sla_target_minutes: int`. La conversión ocurre únicamente en la interfaz:

| Unidad | Factor |
|---|---:|
| `minutes` | × 1 |
| `hours` | × 60 |
| `days` | × 1440 |

## Taxonomía canónica de categorías

Las categorías de servicio alineadas con ITIL son:

- Infrastructure & Platform
- Application Services
- End User Computing
- IT Security
- Telecommunications
- Business Services
- Workspace
- Consulting & Advisory

El seed de arranque las agrega a las categorías CMDB heredadas. `GET /api/categories` conserva el contrato `{name, icon_key}` y expone ambos conjuntos sin eliminar las categorías existentes.

## Tier y criticality

Los controles son independientes. La matriz siguiente es una recomendación operativa; el backend no deriva un valor ni bloquea combinaciones contradictorias.

| Tier | Criticality recomendada |
|---|---|
| `bronze` | `low` |
| `silver` | `medium` |
| `gold` | `high` |
| `platinum` | `critical` |

Los vocabularios se siembran de forma idempotente durante el arranque y se consumen tanto desde el formulario como desde la importación XLSX.

## Contrato HTTP

### Crear un servicio

`POST /api/itsm/service-catalog` acepta un payload sin `service_id` y responde `201 Created`:

```http
POST /api/itsm/service-catalog
Content-Type: application/json

{
  "name": "Corporate access",
  "description": "Managed corporate access service",
  "service_type": "service_request",
  "value_stream": "deliver",
  "owner_team": "Network Operations",
  "category": "Infrastructure & Platform",
  "tier": "gold",
  "criticality": "high",
  "sla_target_minutes": 240
}
```

La respuesta incluye el `service_id` asignado. Un `service_id` explícito y duplicado conserva el contrato histórico `400 Bad Request` y nunca sobrescribe la fila existente.

### Consultar un diccionario gestionado

```http
GET /api/dictionaries?key=tier&active=true
```

Respuesta:

```json
[
  {"value": "bronze", "label": "Bronze"},
  {"value": "silver", "label": "Silver"},
  {"value": "gold", "label": "Gold"},
  {"value": "platinum", "label": "Platinum"}
]
```

Sin el parámetro `key`, `GET /api/dictionaries` conserva el listado legacy del gestor CMDB.

## Importación XLSX

La interfaz de importación mantiene su interfaz pública. La plantilla sigue requiriendo `service_id`; la autogeneración del formulario no cambia las reglas del archivo importado.

- `value_stream` se valida contra el diccionario gestionado.
- Si el workbook contiene columnas `tier` o `criticality`, sus valores se validan contra los mismos diccionarios que alimentan los desplegables.
- Un workbook sin esas columnas opcionales conserva el comportamiento anterior.
- Las filas rechazadas no modifican el catálogo; el importador devuelve el error estructurado por fila y campo.

## Comportamiento de arranque

En una instalación limpia:

1. El bootstrap aplica las migraciones ITSM.
2. El seeder idempotente crea `tier` y `criticality`.
3. El seeder de categorías agrega la taxonomía canónica sin retirar las categorías CMDB.

## Fuera de alcance

- Cambiar `sla_target_minutes: int` por otro wire format.
- Derivar automáticamente `criticality` desde `tier`.
- Migrar registros históricos que ya contengan textos libres.
- Cambiar la interfaz pública de la importación XLSX.

## Referencias

- `frontend/components/ItsmServiceCatalogPage.tsx`
- `backend/routers/itsm_service_catalog.py`
- `backend/routers/dictionaries.py`
- `backend/services/itsm_service_catalog_service.py`
- `backend/services/itsm_imports/catalog_import.py`
- `openspec/changes/feat-service-catalog-itil-ux/`
