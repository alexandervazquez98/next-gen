# Archive Report — feat-324-vpn-sdwan-satellite-link-simulation (Slice 1 — partial)

## Status

**PASS — PARTIAL ARCHIVE (Slice 1 only)**

Slice 1 (data model + catalog primitives) was implemented, verified, and is being archived. Slice 2 (polling/health) and Slice 3 (visual/filter) were not started; their spec files exist in the change folder but are intentionally NOT synced to the canonical specs tree.

## Scope statement

**Partial archive.** Only the work that landed in Slice 1 is being archived as completed. The branch is force-chained (3 stacked-to-main slices), so:

- `vpn-tunnel-relations` capability: FULLY implemented in Slice 1, synced to canonical spec.
- `category-technology-icons` capability: PARTIALLY modified in Slice 1 (4 new icon keys), merged into canonical spec. Slice 3 will further modify it (tunnel health styling).
- `tunnel-monitoring` capability: NOT implemented in Slice 1, NOT synced. Slice 2 owns it.

Slice 2 and Slice 3 will run their own propose/spec/design/tasks/apply/verify/archive cycles against the next branch in the chain and produce their own archive folders.

## Archive date

2026-06-27

## Issue

`alexandervazquez98/next-gen#324` — `feat(network): VPN, SD-WAN, and satellite link simulation`

## Change ID

`feat-324-vpn-sdwan-satellite-link-simulation`

## Branch SHA at archive

`634b6eb` — `docs(sdd): commit planning artifacts + Slice 1 verify report before archive` (this archive operation's docs commit, created immediately before the archive commit).

The 5 implementation/SDD commits already on the branch (on top of base `89dba95`):

1. `f59bc78` — `test(sdd): RED failing tests for vpn_tunnel/sd_wan/satellite/vpn_hub primitives`
2. `0aa8ff5` — `feat(sdd): GREEN model + catalog primitives for VPN/SD-WAN/satellite`
3. `480b895` — `docs(sdd): apply-progress for Slice 1 (model + catalog primitives)`
4. `26d31c4` — `docs(sdd): mark Slice 1 tasks complete in tasks.md`
5. `2f4ef6f` — `docs(sdd): clarify budget overrun risk in apply-progress`

Plus this archive operation:

6. `634b6eb` — `docs(sdd): commit planning artifacts + Slice 1 verify report before archive` (stages untracked SDD planning docs)
7. _<to be created>_ — `chore(sdd): archive Slice 1 of feat-324-vpn-sdwan-satellite-link-simulation — branch at 89dba95`

## Main SHA at archive

NOT YET MERGED. Branch `feat/324-vpn-sdwan-satellite-link-simulation` is ready for review at the archive commit; PR to be opened by the user or next session. The cycle base on `main` was `89dba95`.

## Linked PR

NOT YET OPENED. The orchestrator will surface PR/push decisions to the user after this archive operation completes.

## Files archived (full list)

| File | Size | Notes |
|------|------|-------|
| `openspec/changes/archive/2026-06-27-feat-324-vpn-sdwan-satellite-link-simulation-slice-1/proposal.md` | 66 lines | Full proposal; Slice 1/2/3 scope, success criteria for all three slices. |
| `openspec/changes/archive/2026-06-27-feat-324-vpn-sdwan-satellite-link-simulation-slice-1/design.md` | 94 lines | Full design; Slice 1 table is what was implemented. Slice 2/3 design sections are forward-looking reference. |
| `openspec/changes/archive/2026-06-27-feat-324-vpn-sdwan-satellite-link-simulation-slice-1/tasks.md` | 166 lines | Slice 1 tasks all checked; Slice 2/3 tasks unchecked (planned but not applied). |
| `openspec/changes/archive/2026-06-27-feat-324-vpn-sdwan-satellite-link-simulation-slice-1/apply-progress.md` | 371 lines | Slice 1 TDD evidence (RED → GREEN), spec coverage table, deviations, Slice boundary declaration. |
| `openspec/changes/archive/2026-06-27-feat-324-vpn-sdwan-satellite-link-simulation-slice-1/verify-report.md` | 137 lines | Slice 1 verify verdict: PASS. Backend touched tests 51/51; frontend full suite 490/490. |
| `openspec/changes/archive/2026-06-27-feat-324-vpn-sdwan-satellite-link-simulation-slice-1/specs/vpn-tunnel-relations/spec.md` | 75 lines | Delta spec; 4 requirements, 8 scenarios. |
| `openspec/changes/archive/2026-06-27-feat-324-vpn-sdwan-satellite-link-simulation-slice-1/specs/category-technology-icons/spec.md` | 21 lines | Delta spec; 1 ADDED requirement, 2 scenarios. |
| `openspec/changes/archive/2026-06-27-feat-324-vpn-sdwan-satellite-link-simulation-slice-1/specs/tunnel-monitoring/spec.md` | 86 lines (with NOTE marker) | Delta spec for Slice 2; kept in archive with NOTE marker (not synced). 4 requirements, 11 scenarios. |
| `openspec/changes/archive/2026-06-27-feat-324-vpn-sdwan-satellite-link-simulation-slice-1/archive-report.md` | this file | Cycle summary. |

## Specs synced (Slice 1 only)

### NEW canonical: `vpn-tunnel-relations`

- **Path**: `openspec/specs/vpn-tunnel-relations/spec.md`
- **Action**: Created as authoritative spec (was not previously in canonical tree).
- **Content**: Mirrored from the delta spec at `openspec/changes/.../specs/vpn-tunnel-relations/spec.md` with no delta framing — the 4 requirements and 8 scenarios are now the source of truth for the capability.
- **Coverage**: 100% of the delta spec; every Slice 1 scenario has a matching test in the implementation commits (see `apply-progress.md` Spec coverage table).

### MODIFIED canonical: `category-technology-icons`

- **Path**: `openspec/specs/category-technology-icons/spec.md`
- **Action**: Appended one ADDED Requirement ('Tunnel and VPN Hub Icon Keys') with 2 scenarios, mirroring the #325 archive's additive merge mechanic. The previous 5 requirements (Category Icon Association, Initial Technology Defaults, Admin Icon Selection Experience, System-Wide Technology Rendering, Category Payload Compatibility) are preserved untouched.
- **Reasoning**: The delta spec for Slice 1 was purely ADDED (4 new icon keys: `vpn_tunnel`, `sd_wan_tunnel`, `satellite_link`, `vpn_hub`); no existing requirement was MODIFIED or REMOVED, so no destructive merge was needed. The "[Slice 3] Tunnel health styling stays separate" scenario is intentionally kept in the canonical spec even though Slice 3 hasn't shipped, because it documents a stable contract that the implementation already honors (icons are technology-only, never health).

## Specs NOT synced (and why)

### `tunnel-monitoring`

- **Decision**: NOT synced to canonical tree.
- **Rationale**: Slice 1 did not implement any tunnel monitoring. The spec file was created during the spec phase as forward-looking documentation for Slice 2. The verification report explicitly confirms "Slice 2 polling/health and Slice 3 visual/filter work were explicitly out of scope and were checked for drift." Syncing this spec now would lie about what was implemented and tested; Slice 2's archive must sync it once the polling/health work is actually landed.
- **What Slice 2 will sync**: 4 requirements (Tunnel State Collection, ICMP Degradation Context, Health Rollup State Machine, Tunnel Health Endpoint and Samples) and 11 scenarios once `poll_tunnels()` / `rollup_tunnel_health()` / `GET /api/tunnels/{link_id}/health` ship.

## `tunnel-monitoring/spec.md` handling

**Choice: KEPT IN ARCHIVE FOLDER with NOTE marker at the top of the file.**

The spec was left at `openspec/changes/archive/2026-06-27-feat-324-vpn-sdwan-satellite-link-simulation-slice-1/specs/tunnel-monitoring/spec.md` with this header line immediately under the H1:

> **NOTE**: Tunnel-monitoring spec is pending Slice 2 implementation. Not synced to canonical specs tree. Slice 2's archive will sync this spec to `openspec/specs/tunnel-monitoring/spec.md` once its polling/health work lands.

**Why kept (not removed):**

1. **Audit trail preservation.** The full `proposal.md`, `design.md`, and `tasks.md` describe all three slices. Removing the Slice 2 spec would create a gap in the audit trail that future maintainers would have to reverse-engineer from the proposal/design.
2. **No risk of confusion.** The NOTE marker makes the deferred status explicit at the top of the file. Anyone opening the archive folder immediately sees that this is a known, intentional deferral — not a forgotten sync.
3. **Matches existing archive convention.** The 2026-06-21 `renew-frontend-node-modules-volumes` archive explicitly preserved the delta spec in the archive folder with the comment "Delta spec mirrored for traceability at `openspec/changes/archive/2026-06-21-renew-frontend-node-modules-volumes/specs/frontend-dependency-volume-renewal/spec.md`." The same pattern applies here for a deferred delta.
4. **Slice 2 will find it.** When Slice 2's archive agent runs, it can copy `specs/tunnel-monitoring/spec.md` from this archive folder into the active change folder (or simply re-author it from the unchanged proposal/design), then sync it to canonical.

## Out-of-scope items deferred (Slice 2 and Slice 3)

These are explicitly NOT archived as completed work — they remain in the design/proposal/tasks as forward-looking plans:

1. Slice 2 — `backend/engines/snmp_worker.py` polling path (tunnel isolation from HAS_METRIC / Event / CI status).
2. Slice 2 — `backend/services/tunnel_health.py` (vendor registry, authority sample, ICMP degradation, rollup).
3. Slice 2 — `backend/repositories/topology_repo.py` `set_link_health_sample` (`SET r += $sample`).
4. Slice 2 — `backend/routers/tunnels.py` with `GET /api/tunnels/{link_id}/health`.
5. Slice 2 — Router registration in `backend/main.py` / `server.py`.
6. Slice 3 — `frontend/utils/tunnelHealthStyles.ts` (`mapHealthToStyle`).
7. Slice 3 — `frontend/services/tunnelHealth.ts` (`fetchTunnelHealth` + cache with 5s TTL).
8. Slice 3 — `NetworkVisualizer.tsx`, `VisualRelationshipEditor.tsx` tunnel link rendering + tooltip.
9. Slice 3 — `MonitoringConsole.tsx` `tunnelOnly` filter toggle.
10. Vendor-complete OID/CLI coverage (deferred to a future change per the proposal's out-of-scope list).

## Stable contracts handed to Slice 2 and Slice 3

| Contract | Source | Status |
|----------|--------|--------|
| `Node.public_ip: Optional[str]` with `ipaddress.ip_address` validator | `backend/models/core.py` | ✅ Landed |
| `Link.medium: Optional[Literal['vpn','sd_wan','satellite']]` | `backend/models/core.py` | ✅ Landed |
| `validate_tunnel_endpoint_hub` wired into `create_link` / `update_link` (HTTP 400 before persistence) | `backend/services/link_service.py` | ✅ Landed |
| `ALLOWED_TUNNEL_MEDIUMS`, `VPN_HUB_LAYER` | `backend/services/link_service.py` | ✅ Landed |
| `CategoryIconKey` includes `vpn_tunnel`, `sd_wan_tunnel`, `satellite_link`, `vpn_hub` | `frontend/types.ts` | ✅ Landed |
| `GraphLink.medium?` (frontend type) | `frontend/types.ts` | ✅ Landed |
| `CATEGORY_ICON_KEY_SET`, `CATEGORY_ICON_CATALOG` (with Material Symbols `vpn_key`, `hub`, `satellite_alt`, `vpn_lock`) | `frontend/utils/categoryIcons.ts` | ✅ Landed |
| `CATEGORY_NAME_TO_ICON` (EN + ES `vpn_hub` defaults) | `frontend/utils/categoryIcons.ts` | ✅ Landed |
| `normalizeCategoryName` strips combining diacritics (Unicode NFD) | `frontend/utils/categoryIcons.ts` | ✅ Landed (justified deviation; mirrors #325 diacritic fix) |

## Risks accepted (from `verify-report.md`)

| Severity | Risk | Mitigation in code | Residual exposure |
|---|---|---|---|
| SUGGESTION | The literal `python -m pytest` fails in this worktree because `/usr/bin/python` has no `pytest`; verify used a temp uv venv outside the repo. | Document/standardize a backend test runner wrapper or checked-in environment bootstrap for future verifiers. | None for Slice 1; future Slice 2/3 verifiers will hit the same path. |
| SUGGESTION | No explicit `/api/nodes` read round-trip test for top-level `public_ip`. | Existing passing coverage verifies model/service/repository persistence and validation. | Add a router-level test in a follow-up hardening task if product requires top-level API shape rather than metadata exposure. |
| WARNING | Slice 1 exceeded the 400-line forecast (954 insertions / 18 deletions across 11 code+test files; 1491 lines total including SDD artifacts). | The orchestrator already decided to use `size:exception` for this PR. Production code is ~325 lines (within the original budget); overshoot is concentrated in strict-TDD test files. | Self-contained slice; does NOT touch Slice 2/3 territory. |
| WARNING | Pre-existing backend test pollution (~95 tests fail when running the full backend suite due to inter-test state). | Per-file green evidence captured; Slice 1 tests are green in isolation and in the 3-file targeted run (51/51). | The full-suite pollution is pre-existing, not introduced by Slice 1. Do not fail subsequent slice verify phases on this noise. |

## Commits included in this archive operation

| # | SHA | Subject |
|---|-----|---------|
| 1 | `634b6eb` | `docs(sdd): commit planning artifacts + Slice 1 verify report before archive` (stages the 6 untracked SDD docs) |
| 2 | _<to be created>_ | `chore(sdd): archive Slice 1 of feat-324-vpn-sdwan-satellite-link-simulation — branch at 89dba95` |

The archive commit (2) is the one that physically `git mv`s the change folder into the archive subdirectory, creates `openspec/specs/vpn-tunnel-relations/spec.md`, appends the new requirement to `openspec/specs/category-technology-icons/spec.md`, and writes this `archive-report.md`.

## Lessons learned

- **Strict-TDD RED/GREEN pair travels through the archive unchanged.** The `f59bc78` RED + `0aa8ff5` GREEN pair is the canonical evidence that Slice 1 was test-driven. The archive never rewrites commits; it only moves folders and syncs specs. The verify-report.md and apply-progress.md capture the RED → GREEN transition for the audit trail.

- **Partial archive mechanic: stage untracked SDD docs BEFORE the archive commit.** The `apply-progress.md` and `tasks.md` were committed by the prior SDD chore commits (`480b895`, `26d31c4`, `2f4ef6f`), but `proposal.md`, `design.md`, `specs/`, and `verify-report.md` were still untracked at archive time. Committing them with a dedicated `docs(sdd): commit planning artifacts + Slice 1 verify report before archive` commit (a) keeps the working tree clean for the subsequent `git mv`, and (b) makes it explicit in `git log` that the docs landed BEFORE the archive operation rather than being moved from a working-copy state.

- **Delta specs that arrive "too early" (Slice 2 in the Slice 1 change folder) need a clear deferral marker.** The cleanest pattern is: keep the file in the archive folder with a top-of-file NOTE marker, and document the deferral decision in `archive-report.md`. Removing the file would have lost audit-trail context; syncing it would have lied about what was implemented.

- **ADDED-only deltas against a MODIFIED canonical spec merge cleanly with a simple append.** The `category-technology-icons` delta for Slice 1 was purely ADDED (4 new icon keys, no requirement was modified), so the merge was a straight append of one new `### Requirement: ...` block after the last existing requirement. No destructive MODIFIED/REMOVED operations were needed. The #325 archive used the same additive append for its `Radio and Network Role Catalog Entries` + `Bilingual Catalog Discovery` requirements.

- **`size:exception` is the right escape valve for strict-TDD bash/Python test files.** Slice 1's 954 changed lines vs. the 400-line forecast reflects the cost of strict-TDD: every GREEN task needs a matching RED test in the same reviewable work unit, and backend `pytest` test files tend to grow linearly with scenario count. The orchestrator's `size:exception` decision keeps the budget policy intact while letting the strict-TDD discipline drive the actual line count.

## Outstanding work (for the next slice cycles)

- [ ] Slice 2 — propose/spec/design/tasks/apply/verify/archive its own branch (poll_tunnels, rollup_tunnel_health, /api/tunnels/{link_id}/health, tunnel-monitoring spec sync).
- [ ] Slice 3 — propose/spec/design/tasks/apply/verify/archive its own branch (tunnelHealthStyles helper, NetworkVisualizer/VisualRelationshipEditor/MonitoringConsole rendering + tooltip, tunnelOnly filter, category-technology-icons MODIFIED sync for tunnel health styling).
- [ ] Open PR (PR 1 of 3, Slice 1 only) to main. Branch is ready for review at the archive commit.
- [ ] After Slice 1 merges: Slice 2 rebases on the Slice 1 merge commit.

## Cycle stats

- 8 SDD phases (explore → propose → spec → design → tasks → apply → verify → archive)
- 7 commits on branch `feat/324-vpn-sdwan-satellite-link-simulation` at archive time (5 implementation/SDD commits on top of base `89dba95` + 1 docs staging commit + 1 archive commit)
- 1491 insertions / 18 deletions in the implementation + tests + SDD docs (Slice 1 only)
- 2 new/updated canonical specs at `openspec/specs/`
- 3 archived delta specs in the archive folder (1 synced, 2 preserved for traceability)
- 0 tunnel-monitoring files synced (intentional — Slice 2 owns this)
- Branch ready for review; PR to be opened by user or next session
