# Sync Report — issue-375-ai-chat-guardrails

status: synced

## Structured status and action context

- artifactStore: `openspec`
- change root: `openspec/changes/issue-375-ai-chat-guardrails`
- action mode: repo-local workspace
- action context: workspace root and edits are under `/Users/macbook/Library/CloudStorage/OneDrive-SharedLibraries-Onedrive/PROGRAMMING/next-gen/.worktrees/ai-chat-guardrails-orchestration`
- verify-report status: PASS
- verification evidence: `74 passed, 2 warnings`
- py_compile evidence: PASS
- strict TDD evidence: `TDD Cycle Evidence` present in `apply-progress.md`

## Domain sync results

- resolved domain specs in change artifact:
  - `openspec/changes/issue-375-ai-chat-guardrails/specs/ai-chat-harness-guardrails/spec.md`

### Domains synced

- `ai-chat-harness-guardrails`

### Canonical files updated

- created: `openspec/specs/ai-chat-harness-guardrails/spec.md`
- this was a first-write sync (canonical file did not exist)

### Requirement delta reconciliation

- **ADDED**: Permission failures and guardrail denials use distinct HTTP semantics
- **ADDED**: Guardrail evaluation occurs before chat harness execution
- **ADDED**: No harness execution when guardrails deny, escalate, or fail closed
- **ADDED**: Denied harness result is explicit, structured, persisted, and returned
- **ADDED**: Availability guard targets use canonical CI identity
- **ADDED**: Batch availability is fully guarded before ping
- **ADDED**: Batch unresolved references are handled deterministically and are not passed as guard targets
- **ADDED**: Event-list guard targets use `event_query:*` and must not create cooldown-producing success records
- **ADDED**: Allowed-path behavior remains backward-compatible in this slice
- **ADDED**: No Raven runtime integration and no provider-native tool calling
- **ADDED**: Regression tests cover denied and allowed harness paths
- **MODIFIED**: none
- **REMOVED**: none

## Sync guardrails and blockers

- active same-domain collisions: none detected
- destructive deltas requiring explicit approval: none
- renames present: none
- legacy flat spec layout conflict: resolved by syncing from `specs/ai-chat-harness-guardrails/spec.md`
- no blocking sync conditions remain

## Validation/commands checked

- `cat openspec/changes/issue-375-ai-chat-guardrails/verify-report.md`
- `cp openspec/changes/issue-375-ai-chat-guardrails/specs/ai-chat-harness-guardrails/spec.md openspec/specs/ai-chat-harness-guardrails/spec.md`
- `diff -u openspec/specs/ai-chat-harness-guardrails/spec.md openspec/changes/issue-375-ai-chat-guardrails/specs/ai-chat-harness-guardrails/spec.md`
- verification evidence recorded in:
  - `openspec/changes/issue-375-ai-chat-guardrails/verify-report.md`
  - `openspec/changes/issue-375-ai-chat-guardrails/apply-progress.md`

## Archive/sync readiness

- native filesystem canonical sync is now representable and complete for this change.
- if any follow-up deltas are introduced later (new `MODIFIED`/`REMOVED` blocks or additional requirement changes), they should be synced in a subsequent sync run; current state is clean.

## Next recommended

- `sdd-archive`
