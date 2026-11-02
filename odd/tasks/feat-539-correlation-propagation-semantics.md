# feat-539-correlation-propagation-semantics

**Objective:** implement issue #539's approved correlation-propagation contract as reviewable chained slices: canonical PhysicalLink connectivity, status-aware propagation, UNKNOWN severity degradation, PhysicalLink DOWN events, MANAGES/USES/PROVIDES propagation, and CONNECTS_TO medium filtering.
**Branch:** `feat/539-correlation-propagation-status-aware` from verified `main` @ `a04f702`; **Delivery:** `chain_strategy=stacked-to-main`, with each slice independently reviewable and the rollout flag default-off until the complete chain lands; **Test runner:** `python3.11 -m pytest` from `backend/`, plus Ruff, Black, and full-suite verification at each slice boundary.

## Specs

### S1 — Canonical PhysicalLink connectivity

> "Relaciones + backfill (Recomendado)"
>
> "PR2a — Canonical PhysicalLink connectivity
>
> - `PhysicalLinkRepo.create()` crea CI→PhysicalLink→CI.
> - `backend/migrations/011_*.cypher` hace backfill idempotente.
> - Las consultas de correlación exigen un nodo `:PhysicalLink` intermedio.
> - El borrado de una CI no deja endpoints/edges divergentes.
> - `/api/nodes/{id}/usage` conserva su semántica CI↔CI."

Acceptance: new PhysicalLinks create canonical `(:CI)-[:CONNECTED_VIA]->(:PhysicalLink)` edges; migration 011 rebuilds existing links idempotently; deleting an endpoint CI removes the affected PhysicalLink and its edges atomically; correlation traversals require a `:PhysicalLink` intermediate and never interpret dormant CI→CI seed edges as PhysicalLinks; the public node-usage count preserves its pre-#539 meaning—every relationship incident to the CI—while excluding only the newly introduced CI→PhysicalLink `CONNECTED_VIA` edges.

### S2 — UNKNOWN propagation creates a separate WARNING event

> "Crear evento propagado (Recomendado)"
>
> "CI-A evalúa una métrica y cruza un PhysicalLink UNKNOWN.
> → Se crea un Event PROPAGATED con severity WARNING.
> → root_cause_ci_id conserva la CI raíz.
> → El Event raíz NO cambia de severidad.
> → El operador ve la degradación explícita en el evento propagado."

Acceptance: the modern SNMP path creates an idempotent PROPAGATED Event at WARNING when propagation crosses an UNKNOWN PhysicalLink; the ROOT Event keeps its original severity; the child remains linked to the affected CI; the legacy path applies the same semantics so engines cannot erase WARNING severity or double-propagate; the default operator feed exposes the explicitly degraded child so the operator can see the WARNING downgrade, while ordinary PROPAGATED children remain collapsed into their ROOT to preserve the existing no-double-count behavior.

### S3 — PhysicalLink DOWN descendant event

> "CRITICAL (Recomendado)"
>
> "El evento `physical_link_down` se crea con severity CRITICAL, status OPEN y ambos endpoints en `affected_ci_ids`. El operador recibe una señal inequívoca de outage."

Acceptance: an observed UP→DOWN transition creates one `physical_link_down` Event with severity CRITICAL and status OPEN; its `root_cause_ci_id` is the PhysicalLink id; its `affected_ci_ids` contains both endpoints; it is attached to exactly one CI; concurrent bridge runs create at most one event.

### S4 — PhysicalLink DOWN event host

> "Endpoint A (Recomendado)"
>
> "ci_id = endpoint_a
> (HAS_EVENT) CI-A → Event
> affected_ci_ids = [endpoint_a, endpoint_b]
>
> El feed muestra una sola fila; el segundo endpoint sigue apareciendo como afectado."

Acceptance: the descendant Event's `ci_id` is endpoint A and its `HAS_EVENT` relationship targets endpoint A only; endpoint B remains present in `affected_ci_ids`; the operator feed does not duplicate the Event.

### S5 — PhysicalLink DOWN recovery

> "Pruner-limited (Recomendado)"
>
> "UP→DOWN: crea un Event OPEN CRITICAL.
> UP posterior: no recupera automáticamente el evento.
> El event-pruner existente termina cerrándolo según su política."

Acceptance: a later link recovery does not automatically recover the descendant Event; PR2c2 explicitly extends the existing Event-pruner to close an OPEN, unacknowledged `physical_link_down` Event once its known `created_at` age exceeds `EVENT_PRUNE_STALE_AFTER_SECONDS` (existing default 3600 seconds), recording `status = CLOSED`, `closed_at`, and the pruner actor as `closed_by`. The existing RECOVERED pruning predicate and the SSE "Clean recovered" path remain unchanged; an unknown/missing `created_at` is not eligible for automatic closure; adding the missing lock to manual `POST /api/events/prune` remains outside this slice.

### S6 — MANAGES / USES / PROVIDES propagation

> "4. **`MANAGES` / `USES` / `PROVIDES` default — `all_propagate`.** Sin flag, las 3 se añaden al traversal. Simple, riesgo aceptado."

Acceptance: when the rollout slice is enabled, all three relationship types propagate by default with no per-CI or per-metric relationship gate; ROOT and PROPAGATED semantics remain unchanged; the supported CI relationship whitelist remains untouched.

### S7 — CONNECTS_TO medium filter

> "3. **CONNECTS_TO con medium** — añadir filtro en el traversal:
> - **medium ∈ {None, "ethernet", "fiber", "copper"}** → propaga
> - **medium ∈ {"vpn", "sd_wan", "satellite"}** → no propaga automático (puede tener `relationship_propagates: true` explícito)"

Acceptance: the runtime predicate excludes `vpn`, `sd_wan`, and `satellite`; unset and legacy non-tunnel media continue to propagate; the supported CI relationship whitelist remains untouched.

### S8 — Cross-chain constraints

> "Do NOT modify `backend/services/relationship_types.py:7-13` (`SUPPORTED_CI_RELATIONSHIP_TYPES` stays at 6; only the traversal changes).
> Do NOT change depth default 3 without coordinating with `docs/correlation-topology-guide.md:115-125`.
> Do NOT introduce new `UserPermission` enum values.
> Do NOT change the ROOT vs PROPAGATED semantics — only the set of traversed relationships and the gates.
> Strict TDD: RED → GREEN for every work-unit commit."

Acceptance: each behavior-changing slice observes RED before implementation and GREEN afterward; depth remains 3; the supported CI relationship whitelist and permission model remain unchanged; each slice passes focused tests and the applicable full backend suite.

## Tasks

| ID | Title | Linked S# | Route | Status | Commit / evidence |
|----|-------|-----------|-------|--------|-------------------|
| T0 | Reconcile shipped PR1, runtime model, and maintainer decisions | S1-S8 | inline | done | PR1/#543/#547 verified; four product decisions selected; connectivity confirmed |
| T1 | Update the OpenSpec contract and correlation guide for the reconciled behavior | S1-S8 | delegated | done | `bbbf5ed` guide/proposal/feature plan; `5a34a7c` formal spec/tasks |
| T2 | PR2a1 — create PhysicalLink edges, backfill migration 011, delete lifecycle, and preserve usage semantics | S1, S8 | delegated | in progress | Implemented and independently verified; runtime commit pending |
| T3 | PR2a2 — add status-gated PhysicalLink traversal and propagate link/severity metadata through correlation caches | S1, S2, S8 | delegated | pending | Contract mapping: link crossing is one logical hop; depth 3; same-statement status read; `:PhysicalLink` intermediate mandatory |
| T4 | PR2b1 — implement modern SNMP separate WARNING PROPAGATED Events and idempotency guards | S2, S8 | delegated | pending | — |
| T5 | PR2b2 — align the legacy path and leased writer with modern propagation semantics | S2, S8 | delegated | pending | — |
| T6 | PR2c1 — implement the atomic PhysicalLink DOWN transition and descendant Event write | S3-S5, S8 | delegated | pending | — |
| T7 | PR2c2 — wire the DOWN event into the polling bridge, extend the pruner for stale link-down events, and wire the rollout flag | S3-S5, S8 | delegated | pending | — |
| T8 | PR3 — propagate MANAGES, USES, and PROVIDES relationships | S6, S8 | delegated | pending | — |
| T9 | PR4 — exclude tunnel media from CONNECTS_TO propagation | S7, S8 | delegated | pending | — |
| T10 | Run seam verification, reconcile every requirement, and close issue #539 | S1-S8 | inline | pending | — |

## Log

- **L1** (user, 2026-11-02): "Continuar la cadena aprobada #539: PR2 status-aware, PR3 relaciones restantes y PR4 filtro medium."
- **L2** (user, 2026-11-02): "Crear evento propagado (Recomendado)" — UNKNOWN must create a separate PROPAGATED Event at WARNING without changing the ROOT Event severity.
- **L3** (user, 2026-11-02): "CRITICAL (Recomendado)" — `physical_link_down` uses CRITICAL severity.
- **L4** (user, 2026-11-02): "Endpoint A (Recomendado)" — the descendant Event is hosted by endpoint A while both endpoints remain affected.
- **L5** (user, 2026-11-02): "Pruner-limited (Recomendado)" — a later UP does not automatically recover the descendant Event.
- **L6** (user, 2026-11-02): "Relaciones + backfill (Recomendado)" — confirm canonical CI→PhysicalLink relationships, idempotent backfill, deletion repair, and unchanged CI↔CI usage semantics.
- **L7** (orchestrator, 2026-11-02): Current-runtime reconciliation found three implementation gaps not visible in the stale PR1 document: PhysicalLink had no edge writer or backfill; the modern SNMP path intentionally created no PROPAGATED child Events while the legacy path did; and the bridge detected UP→DOWN but used a non-atomic status update. The contract now separates PR2 into connectivity/traversal, severity/event, and DOWN-event slices so each remains reviewable.
- **L8** (user, 2026-11-02): "Preservar conteo previo (Recomendado)" — `/api/nodes/{id}/usage` keeps every pre-existing incident-relationship contribution and excludes only the new CI→PhysicalLink `CONNECTED_VIA` edges.
- **L9** (user, 2026-11-02): "Extender pruner (Recomendado)" — an OPEN, unacknowledged `physical_link_down` Event is closed by the existing prune cadence after it exceeds `EVENT_PRUNE_STALE_AFTER_SECONDS` (current default 3600 seconds); a later PhysicalLink UP does not recover or pre-emptively close it.
- **L10** (orchestrator, 2026-11-02): Pruner mapping fixed the bounded extension invariants: preserve the RECOVERED predicate byte-for-byte, select only OPEN/unacknowledged `physical_link_down` rows with a known `created_at`, use the configured stale threshold, reuse existing prune metrics, leave the SSE "Clean recovered" path unchanged, and keep manual-prune locking outside this slice. The missing historical age gate on RECOVERED events remains separate debt.
- **L11** (orchestrator, 2026-11-02): T3 mapping locked the traversal semantics: `(ci)-[:CONNECTED_VIA]->(pl:PhysicalLink)<-[:CONNECTED_VIA]-(peer:CI)` is one logical hop, the pure-CI and link-aware paths remain depth 3, `pl.status` is read in the same Cypher statement and restricted to `{UP, UNKNOWN}`, direct CI→CI `CONNECTED_VIA` seed edges never match, and PhysicalLink ids never enter CI adjacency. Link id/status metadata must reach correlation caches so the later severity and DOWN slices can consume it without re-querying status.
- **L12** (orchestrator, 2026-11-02): T1/T2 verification completed. Parent evidence: 41 focused tests passed; Ruff, Black, and diff-check passed; full backend suite passed with 2612 tests and 2 skips; isolated Neo4j 5.15 migration 011 applied twice yielded two PhysicalLink edges, one preserved direct CI edge, one PhysicalLink, and zero orphans after endpoint deletion. Independent `gentle-ai-verify` reproduced the graph behavior in an isolated Neo4j 5.15 container, applied migration 011 three times with identical counts, and returned PASS with zero blockers. The five advisories are non-blocking follow-ups: repeated create behavior depends on the migration-009 uniqueness constraint, the missing-endpoint race surfaces a bare RuntimeError, deletion uses the endpoint array as source of truth, usage has live as well as structural proof, and relationship MERGE has no supporting index constraint.
- **L13** (orchestrator, 2026-11-02): T1 was committed as two reviewable slices: `bbbf5ed` (`docs(correlation): reconcile PhysicalLink propagation contract`) and `5a34a7c` (`docs(correlation): specify reconciled propagation requirements`). T2 runtime is implemented and verified and is the next isolated work-unit commit.
