# ITSM Event Flow

## Proposito

Este documento explica como NEX-GEN lleva un evento tecnico hacia un contexto operativo listo para incident management y futuras integraciones ITSM.

## Flujo end-to-end

```text
Metric breach
  -> worker normaliza severidad y mensaje
  -> crea o actualiza Event
  -> si el Event es nuevo, captura snapshot de negocio y SLA
  -> /api/events mantiene el resumen del stream
  -> /api/events/{event_id} resuelve detalle del modal
  -> operador reconoce, comenta, diagnostica y cierra
  -> futuro: adjunta / sincroniza ticket externo
```

## Estados del evento

- `OPEN`: evento nuevo, sin ownership activo.
- `ACK`: alguien tomo el caso o lo reconocio.
- `RECOVERED`: la condicion tecnica desaparecio, pero el evento puede seguir abierto para auditoria.
- `CLOSED`: incidente cerrado manualmente o por limpieza controlada.

## Ownership y asignacion

- `ack = true` + `ack_by` representan asignacion activa basica.
- El `itsm_context.assignment_state` traduce eso a `assigned` o `unassigned`.
- Los comentarios siguen siendo append-only y funcionan como timeline operacional.
- `Tomar caso` en frontend agrega comentario de ownership y luego hace `ack`.

## SLA: como se interpreta

### Fuente del SLA

1. Se intenta leer `sla_minutes` guardado en el snapshot del `Event`.
2. Si no existe snapshot, se intenta resolver desde `BusinessService -> ServiceCatalog`.
3. Si no hay fuente confiable, la API devuelve `sla_remaining_minutes = null`.

### Calculo

- `sla_remaining_minutes = sla_minutes - minutos_desde_created_at`
- Puede dar negativo; eso significa SLA vencido.
- La UI muestra alerta visual cuando el remanente es bajo o vencido.

### Estados de procedencia

- `snapshot`: todo sale del evento historico.
- `resolved`: todo sale del grafo actual.
- `mixed`: el backend mezclo snapshot con fallback para completar huecos.
- `unavailable`: no hay suficiente data para afirmar servicio, sitio o SLA.

## No-data states

Cuando falta contexto, el contrato devuelve `null` de forma explicita. Eso es IMPORTANTE:

- evita precision falsa
- evita inferencias desde metadata vieja del CI
- deja claro que el problema es de datos, no de rendering

La UI solo conserva `node.metadata` como fallback transitorio de rollout. No es la fuente canonica del dominio.

## Diagnostico y timeline

- `POST /api/events/{event_id}/diagnose` ejecuta diagnostico on-demand y persiste el resultado como comentario.
- `POST /api/events/{event_id}/comment` agrega notas operativas o cierres estructurados.
- El timeline del modal mezcla disparador inicial, ownership, notas, diagnosticos y cierres sin edicion destructiva.

## Cierre y auditoria

- El cierre normal exige causa raiz y nota descriptiva.
- El cierre forzado deja marca explicita en el timeline.
- `RECOVERED` sin ack ni comentarios puede limpiarse en lote con `/api/events/prune`.

## Puntos de integracion futura

El contrato ya deja el espacio para acoplar ITSM externo sin inflar el stream principal:

- `itsm_context.external_ticket.system`
- `itsm_context.external_ticket.key`
- `itsm_context.external_ticket.status`

Integraciones futuras esperadas:

- Jira: creacion de incident / bug con link al evento.
- ServiceNow: incidente o alert record con sincronizacion de estado.

## Reglas operativas para reviewers

Una entrega de esta capability NO esta completa si falta alguno de estos artefactos:

- `README.md`
- `docs/domain/business-model.md`
- `docs/itsm/event-flow.md`
- `modelo_entidad_relacion.md`

## Referencias cruzadas

- `README.md`
- `docs/domain/business-model.md`
- `modelo_entidad_relacion.md`
