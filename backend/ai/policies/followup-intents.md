# Follow-up intents policy

This file documents the current Python intent inference policy. It is not a runtime parser in this slice.

## Event-list triggers

Event-list triggers include concepts such as events, eventos, alertas, incidentes, abiertos/open, activos, console/consola, recuperados/recovered, critical/críticos, warning, and info.

## Availability follow-up triggers

Availability follow-up triggers include estatus, estado, siguen/sigue, disponibilidad, chequeo/checa, verifica/verificar, revisa/revisar, funcionando, reachable, working, and availability.

## Named-area matching

Named-area follow-ups match latest same-user `event_list` metadata fields: `ci_name`, `ci_id`, `ci_hostname`, `ci_location_name`, and `message`.

Stopwords include operational filler such as dame, actual, sitio, disponibilidad, chequeo, verifica, revisar, equipos, funcionando, and como.

`availability_check_batch` remains capped at 5 CIs.
