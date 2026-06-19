# event_list deterministic template

Use this reviewed structure for `event_list` harness responses.

## Eventos observados / Observed events

Include count, applied filters, severity, status, CI, message, and `last_seen` when present.

## Diagnóstico observado / Observed diagnosis

Limit diagnosis to symptoms evidenced by event data: latency or threshold breach, availability or ping-check symptoms, and event status.

## Límites / Limitations

Event-list data alone does not confirm root cause or event resolution. It does not prove congestion, power, cabling, firewall, service health, stable/optimal state, or closure.

## Siguiente chequeo sugerido / Suggested next checks

Suggest checks without claiming they already ran. Include a truncated notice when `truncated` is true.
