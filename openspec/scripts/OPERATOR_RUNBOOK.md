# Operator Runbook: CMDB Orphan Topology Backfill

The `cmdb_backfill_orphans.py` script is an **offline, read-only** tool that
surfaces Access Points (APs) with no upstream `DEPENDS_ON | HOSTED_ON` edge in
the Neo4j topology. It is shipped under `openspec/scripts/` as part of the
P3a slice of issue #416 — no auto-write, no heuristics, no enrichment beyond
opaque CI IDs.

## When to use

Run this script when:

- An operator has been told that an AP may be missing its parent in the
  CMDB (for example, after a manual inspection of the topology graph or
  after seeing an "orphan" indicator in a downstream dashboard).
- The user wants a one-shot dump of the APs that need manual wiring
  before applying a topology fix in internal CMDB tooling.
- The on-call engineer wants a quick way to validate that a recent
  Neo4j migration did not leave new orphan APs behind.

The script is **not** a replacement for the production correlation engine
(`event-write-time-correlation`) and must never be run inside the API
process. Treat its output as read-only diagnostic data.

## Invocation

Export the Neo4j credentials from the sealed secret store (never
committed) and invoke the script with an output path that lives outside
the repository tree:

```bash
export NEO4J_URI='bolt://neo4j-host:7687'
export NEO4J_USER='<operator-user>'
export NEO4J_PASSWORD='<operator-password>'

python openspec/scripts/cmdb_backfill_orphans.py \
    --output "/tmp/$(date -u +%Y%m%dT%H%M%SZ)-orphans.json"
```

Flags accepted by the script:

- `--neo4j-uri`: Bolt URI; falls back to `$NEO4J_URI` when omitted.
- `--scope`: `ap` only in this slice. Any other value is rejected.
- `--relationship-types`: explicit allowlist (`DEPENDS_ON`, `HOSTED_ON`,
  `MANAGES`, `RUNS_ON`). `CONNECTS_TO` is intentionally excluded because
  it has no parentage semantics.
- `--format`: `json` only.
- `--output`: file path or `-`/omitted for stdout.

## Output interpretation

The JSON envelope always has these five keys:

- `as_of`: ISO 8601 UTC timestamp with trailing `Z`.
- `scope`: validated scope string (`ap`).
- `relationship_types`: validated rel types in the order they were given.
- `orphan_count`: integer equal to `len(ci_ids)`.
- `ci_ids`: list of opaque CI IDs in first-seen order.

A single stderr line is emitted per run with the audit metadata
(`ts`, `query_hash`, `scope`, `rels`, `orphan_count`, `exit`,
`cap_reached`). The line never includes a CI ID, name, IP, or
credential; that is by design. Stderr must remain minimal.

## Privacy

- **Never copy the JSON output into the repository tree.** The
  `openspec/scripts/output/` directory is git-ignored for this reason.
  Write the file under `/tmp/`, a sealed operator share, or the CMDB
  tool's staging area.
- **Never paste CI IDs, names, IPs, or sites into chat, tickets, or
  documentation.** The script returns opaque IDs on purpose; downstream
  CMDB tooling is responsible for resolving them to a customer-facing
  label inside an authenticated UI.
- After the run, **Delete the JSON file** from the operator share or `/tmp/`
  to keep the secret-bearing host clean. The script does not clean up
  after itself.
- The `NEO4J_PASSWORD` environment variable stays in the operator shell.
  Do not echo it on the command line; do not commit it; do not paste
  it into the runbook or a chat thread.
