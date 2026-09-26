# chore-events-backfill-stuck-icmp-recovery-486

## Goal
Cerrar #486 con un one-shot backfill para los eventos OPEN pre-#485 que el forward fix de v1.17.1 (PR #485) no puede cerrar solo:
1. Eventos ICMP_JITTER / ICMP_PACKET_LOSS cuyo CI está actualmente DOWN o fue borrado del CMDB.
2. Eventos legacy con `event_type` o `metric_id` NULL (153 reportados al issue-open).

Owner: backend. Workstream separado para triage NULL-discriminators queda fuera de scope de este change.

## Decisiones tomadas en review (sin TBDs)

| # | Decisión | Default |
|---|---|---|
| 1 | `recovered_at` para eventos backfilled | `datetime()` al momento del run + `recovery_source = 'backfill'` |
| 2 | Política para 153 NULL-discriminators | Cierre conservador con `event_type = 'legacy-no-relevant'`, `recovered_at = backfill_run_at`, `backfill_origin = 'chore-events-backfill-486-legacy-null-discriminator'` |
| 3 | Exclusión MTTR | Añadir `AND e.event_type <> 'legacy-no-relevant'` al filtro en `get_availability_report` (defensa contra expansión futura de scope; el filtro `event_type='AVAILABILITY'` ya excluye jitter/packet_loss hoy) |

## Estado del SDD change (PR1 docs)

- Branch: `chore-events-backfill-stuck-icmp-recovery-486` (a crear desde `main` actual @ v1.17.4).
- Cambios PR1: solo artefactos SDD (`openspec/changes/.../proposal.md` + `design.md` + `tasks.md` + `specs/event-prune-recovery-lifecycle/spec.md`).
- Sin código de aplicación en PR1. PR2 y PR3 son los slices de código.

## Forecast de chained PRs (justificación del split)

| PR | Líneas estimadas | Contenido | Riesgo budget 400 |
|---|---|---|---|
| PR1 (este) | ~350 | Docs SDD + spec delta | OK |
| PR2 | ~350 | `backend/scripts/backfill_stuck_icmp_events.py` (dry-run) + `backend/tests/test_backfill_stuck_icmp_events.py` (inventario + buckets + dry-run) + runbook corto | OK |
| PR3 | ~300 | Cascade script completion + MTTR exclusion clause en `backend/services/event_service.py` + cascade tests | OK |

Total: 3 PRs encadenados. `feature-branch-chain` strategy (matching precedent `event-writer-coordination-observability`).

## Plan de tasks

1. Crear branch `chore-events-backfill-stuck-icmp-recovery-486` desde `main`.
2. PR1: escribir los 4 artefactos SDD. Self-review. Push. Abrir PR docs-only.
3. PR2 (post-merge PR1): escribir script dry-run + tests RED primero (Strict TDD). PR2 = solo lectura sobre Neo4j, sin mutaciones.
4. PR3 (post-merge PR2): cascade de mutación + MTTR exclusion + tests RED primero. Esta es la fase donde el daño es irreversible si la query está mal condicionada → snapshot pre-run en `apply-progress.md`.
5. Runbook de ejecución en target environment (operador, no bot).
6. CHANGELOG entry bajo próximo PATCH (v1.17.5 tentativo).
7. Archive del change después del merge final.

## Acceptance criteria (del issue #486)

- `stuck_post_485 = 0` después del run.
- `null_discriminators` queda como único bucket residual, entregado al workstream de triage.
- MTTR p50/p95 sin cambio (el filtro de `event_type` ya lo garantiza; la cláusula defensiva es para futuro).
- Audit marker `backfill_origin` presente en todas las filas backfilled, distinguible por origen.

## Riesgos clave

1. **Cascade Cypher mal condicionada puede cerrar eventos no objetivo.** Mitigación: tests RED sobre fixture con 1 ROOT + 2 PROPAGATED + 1 evento no relacionado + CI-deleted. Snapshot pre-run para rollback.
2. **CI puede transicionar UP→DOWN entre issue-open y run.** Mitigación: snapshot inmutable de availability al inicio del run, decisión contra snapshot.
3. **`legacy-no-relevant` rompe queries existentes que asumen event_type cerrado.** Mitigación: tests de regresión sobre queries que enumeran event_types.
4. **Doble cierre si el forward fix #485 corre durante el backfill.** Mitigación: idempotencia — el cascade filtra `status IN ['OPEN', 'ACK']`, los ya RECOVERED son no-op.

## Referencias

- Issue: #486
- Upstream PR: #485 (merged 2026-09-18, released v1.17.1)
- Recovery writers: `backend/engines/snmp_worker.py:1132` (`_recover_icmp_jitter_events`), `:1177` (`_recover_icmp_packet_loss_events`)
- Synthetic breach injector: `backend/engines/snmp_worker.py:1220` (`_inject_synthetic_breaches_for_down_cis`)
- MTTR query: `backend/services/event_service.py:687` (`get_availability_report`)
- Spec destino: `openspec/specs/event-prune-recovery-lifecycle/spec.md`
- Precedent archive: `openspec/changes/archive/2026-09-17-fix-484-event-recovery-jitter-packet-loss/`
- Config: `openspec/config.yaml` — `review_budget_changed_lines: 400`, `strict_tdd.test_first_required: true`
