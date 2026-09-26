# Archive Report: fix-484-event-recovery-jitter-packet-loss

**Archived**: 2026-09-17
**Issue**: [#484](https://github.com/alexandervazquez98/next-gen/issues/484)
**PR**: [#485](https://github.com/alexandervazquez98/next-gen/pull/485)
**Branch**: `fix-484-event-recovery-jitter-packet-loss`
**Mode**: Strict TDD
**Persistence**: OpenSpec

## Final State

- **Verdict**: PASS — archive-ready (after CRITICAL-1 fix round)
- **Requirements**: 5/5 COMPLIANT
- **Scenarios**: 10/12 strictly COMPLIANT (12/12 with NEEDS-MORE-EVIDENCE counted)
- **ADs**: 7/8 FOLLOWED, 1 PARTIAL (AD-2 placement — documented, user-visible equivalent)
- **Tests**: 2168 passed, 2 skipped, 4 pre-existing testcontainers deselected
- **Budget**: 1550 insertions / 50 deletions across 8 files

## What Shipped

1. `_recover_icmp_jitter_events` and `_recover_icmp_packet_loss_events` in `backend/engines/snmp_worker.py` — recovery writers symmetric with `_recover_icmp_latency_events` (line 1093), wired into `poll_snmp()` after line 1762.
2. `_inject_synthetic_breaches_for_down_cis` in `backend/engines/snmp_worker.py` — pure-Python helper that injects a CRITICAL synthetic breach row when a CI is DOWN by ICMP ping and the metric is configured (`:HAS_METRIC` verified via Cypher at start of cycle).
3. `PREDICATE_SITES` registry extended from 4 to 6 sites in `backend/tests/test_snmp_worker_recovery_writer_predicates.py`.
4. Spec delta in `openspec/changes/archive/2026-09-17-fix-484-event-recovery-jitter-packet-loss/specs/event-prune-recovery-lifecycle/spec.md` (5 ADDED Requirements).
5. CHANGELOG entry under next version's `### Fixed`.

## Process Notes

This change was archived **before merge** at the user's explicit instruction, overriding the repo convention that archive normally runs after merge. The PR (#485) is pending the `status:approved` label from a maintainer to merge.

The verify→fix→re-verify cycle caught a real logic inversion (CRITICAL-1: AD-3 was ambiguous, spec was explicit; the implementation followed the design summary instead of the spec). The fix applied strict-TDD discipline (RED test commit before GREEN impl commit), reversing the warning from the first verify.

## Commit Trail (12 commits on branch)

```
b0c1db4  style(backend): apply black formatting to CRITICAL-1 fix files
9cf2b79  docs(sdd): update fix-484 verify-report after CRITICAL-1 fix (verdict: pass)
6b12824  docs(sdd): correct AD-3 description for HAS_METRIC gate
4e7a9ea  fix(events): correct HAS_METRIC gate in synthetic breach injector (REQ-SYNTHETIC-BREACH-SCOPE)
03f669f  test(events): cover spec scenario for synthetic breach scope (REQ-SYNTHETIC-BREACH-SCOPE)
f4a8d22  docs(sdd): mark fix-484 apply phase tasks complete and progress notes
4e377b7  style(backend): apply black formatting to fix-484 test files
9437246  chore(release): changelog entry for #484
729aea8  test(events): extend recovery predicate regression to six sites
a5da286  fix(events): wire jitter and packet_loss recovery + synthetic breach on CI DOWN
f79235e  feat(events): recover OPEN ICMP packet_loss THRESHOLD_BREACH events
e7f6dec  feat(events): recover OPEN ICMP jitter THRESHOLD_BREACH events
039c674  feat(events): inject synthetic CRITICAL breach for unreachable CIs (jitter, packet_loss)
```

## Related

- Closes follow-up of #431 (PR #432 merged 2026-08-28 left this gap documented but unimplemented).
- Reuses the contract from `event-prune-recovery-lifecycle` spec; predicate site count goes from 4 to 6.
- The 153 OPEN legacy events (`<null>` event_type + `metric_name IS NULL`) are explicitly out of scope; tracked as a separate change.
