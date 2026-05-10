# Mass Metric Dictionary Flow

## Propósito

Este documento explica cómo NEX-GEN permite aplicar métricas de monitoreo de forma masiva a CIs usando "Diccionarios" — plantillas pre-cargadas de OIDs organizadas por marca y modelo de equipo.

## Modelo de datos

### MetricDictionary

```text
MetricDictionary (Neo4j node)
├── id: string           — UUID, primary key
├── name: string         — nombre legible, e.g. "Cisco Catalyst-2960 - Basic"
├── brand: string         — marca exacta, e.g. "Cisco" (REQUIRED)
├── model: string         — modelo exacto, e.g. "Catalyst-2960" (REQUIRED)
├── metrics: list[str]    — metric_ids referenciando MetricDef nodes
├── polling_interval: int — segundos entre muestreos (default: 60)
├── created_at: datetime
└── updated_at: datetime
```

**Constraint:** brand + model son obligatorios y únicos. No existen wildcards — cada combinación marca/modelo tiene su propio diccionario.

### AppliedDictionary

```text
AppliedDictionary (Neo4j node)
├── id: string              — UUID
├── ci_id: string           — ID del CI objetivo
├── dictionary_id: string    — referencia a MetricDictionary.id
├── excluded_metrics: list[str] — métricas del diccionario a excluir
├── extra_metrics: list[str]     — métricas custom agregar
└── applied_at: datetime
```

**Relaciones:**
```
(CI)-[:HAS_DICTIONARY]->(AppliedDictionary)
(AppliedDictionary)-[:REFERENCE_DICTIONARY]->(MetricDictionary)
```

## Flujo end-to-end

```text
1. CARGAR DICCIONARIO (one-time setup)
   └→ Admin crea MetricDictionary con brand+model + lista de metric_ids
   └→ Cada metric_id apunta a un MetricDef existente (sin duplicar OIDs)

2. SELECCIONAR CIs DESTINO
   └→ GET /api/dictionaries/{id}/target-cis
   └→ Retorna todos los CIs donde brand+model matchean exactamente
   └→ Usuario selecciona cuáles aplicar (checkboxes)

3. PREVIEW (validación SNMP real)
   └→ POST /api/dictionaries/{id}/preview
   └→ Query SNMP paralelo a cada CI seleccionado (batch 20)
   └→ Retorna valor actual y status: OK / WARNING / CRITICAL / NO_DATA
   └→ NO_DATA indica que el OID no responde en ese equipo

4. APLICAR
   └→ POST /api/dictionaries/{id}/apply
   └→ Crea AppliedDictionary overlay por cada CI
   └→ MERGE idempotente — seguro ejecutar varias veces

5. RECONCILE (en segundo plano)
   └→ reconcile_node_metrics() corre periódicamente
   └→ Calcula métricas efectivas por CI:
      effective = (applicable ∪ dictionary_metrics) - excluded ∪ extra
   └→ Crea/elimina relaciones HAS_METRIC según effective set
```

## Endpoints API

### Dictionary CRUD

| Método | Path | Descripción |
|--------|------|-------------|
| GET | `/api/dictionaries` | Lista todos los diccionarios |
| POST | `/api/dictionaries` | Crea diccionario nuevo (CI_EDIT) |
| GET | `/api/dictionaries/{id}` | Obtiene diccionario por ID |
| PUT | `/api/dictionaries/{id}` | Actualiza diccionario (CI_EDIT) |
| DELETE | `/api/dictionaries/{id}` | Elimina diccionario + AppliedDictionary (CI_EDIT) |

### Mass Apply

| Método | Path | Descripción |
|--------|------|-------------|
| GET | `/api/dictionaries/{id}/target-cis` | Lista CIs matching brand+model |
| POST | `/api/dictionaries/{id}/apply` | Aplica diccionario a CIs seleccionados |
| POST | `/api/dictionaries/{id}/preview` | Preview SNMP readings antes de aplicar |

### Per-CI Customization

| Método | Path | Descripción |
|--------|------|-------------|
| GET | `/api/cis/{ci_id}/applied-dictionary` | Ver diccionario aplicado + exclusiones |
| PUT | `/api/cis/{ci_id}/dictionary-exclusions` | Actualizar excluidas/incluidas |
| DELETE | `/api/cis/{ci_id}/applied-dictionary` | Quitar diccionario del CI |

## Componentes Frontend

| Componente | Propósito |
|------------|-----------|
| `DictionaryManager.tsx` | CRUD de diccionarios — crear, editar, eliminar |
| `DictionaryMassApply.tsx` | Seleccionar CIs, preview, aplicar |
| `CIDictionaryCustomization.tsx` | Personalizar métricas por CI post-aplicación |

## Casos de uso

### Switch con puertos no usados

```text
1. Diccionario "Cisco Catalyst-2960 - Ports" incluye:
   - ifStatus, ifOctets, ifErrors para cada puerto

2. Apply a Switch-Core-01 (48 puertos)

3. Post-apply: personalizar
   - Puerto 13-48 excluidos (no están en uso)
   - Solo se monitorean GigabitEthernet1/0/1 a 1/0/12

4. reconcile_node_metrics() solo crea HAS_METRIC para los 12 puertos activos
```

### Validación antes de aplicar

```text
1. Usuario selecciona 20 switches para aplicar diccionario

2. Preview muestra:
   - 15 switches: todas las métricas responden OK/WARNING
   - 4 switches: algunos OIDs returnan NO_DATA (modelo diferente)
   - 1 switch: sin SNMP configurado

3. Usuario desmarca los 5 problemáticos
4. Aplica solo a los 15 confirmados
```

## Validación y Testing

- **49 tests** cubriendo router, service y reconcile


## Referencias cruzadas

- `docs/itsm/event-flow.md` — cómo los eventos de métricas se generan
- `docs/reference/modelo_entidad_relacion.md` — modelo completo de entidades
- `backend/services/metric_service.py` — reconcile_node_metrics()
- `backend/services/dictionary_service.py` — CRUD y preview
