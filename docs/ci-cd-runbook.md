# CI/CD Runbook

> **Status: stub**. The full runbook is authored in PR6 (`cicd/cd-lane`).
> See `openspec/changes/ci-cd-pipeline/tasks.md` T6.2.

This document is the operator-facing reference for the next-gen CI/CD pipeline.
It complements the self-hosted runner setup guide (`docs/self-hosted-runner.md`,
PR6 / T6.1) and the alert contract declared in the CD workflow (PR6 / T6.4).

## Deployment

**TBD — completed in PR6.** PR6 wires `scripts/safe-rebuild.sh` to the
self-hosted runner job; this section will document the deploy procedure,
pre-flight checks, and the GitHub Issue alert label `cd-failure`.

## Failure Recovery

**TBD — completed in PR6.** PR6 documents how to recover from a failed CD
run by replaying the pre-rebuild backup captured at the start of that deploy
(via `scripts/pre-rebuild-backup.sh`, invoked from `scripts/safe-rebuild.sh`).

## Rollback Policy

**TBD — completed in PR6.** PR6 records the v1 rollback policy:

- No automatic service rollback in v1.
- Smoke lane (PR5) is the deployment gate; on failure the CD workflow fails and
  raises a GitHub Issue labeled `cd-failure`.
- A human restores service state by replaying the pre-rebuild backup.
- Image-tag rollback and DB restore automation are explicitly deferred to a
  future change.

## Cross-References

- Proposal: `openspec/changes/ci-cd-pipeline/proposal.md`
- Spec: `openspec/changes/ci-cd-pipeline/specs/ci-cd-pipeline/spec.md`
- Design: `openspec/changes/ci-cd-pipeline/design.md`
- Tasks: `openspec/changes/ci-cd-pipeline/tasks.md`
