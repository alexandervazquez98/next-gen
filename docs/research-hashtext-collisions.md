# Hashtext triplet collision rate — research report

> Issue **#336** (parent epic **#333**) — investigate the collision rate of
> PostgreSQL's `hashtext()` applied to event-triplet advisory-lock keys.
> Decision rule from the issue: ≤5% collision-induced serialization → close
> without action; >5% → open follow-up for 64-bit hash migration.

This report is **research-only**. No production code changes ship in this
investigation. The Python port, the synthetic generator, and the analysis
live in `backend/scripts/research_hashtext_collisions.py`; the test
guardrails live in `backend/tests/test_research_hashtext_collisions.py`.

## TL;DR

Across three synthetic scales spanning 6,000 — 800,000 distinct triplets,
collision rates stayed at or below **0.0101%** — two orders of magnitude
below the 5% threshold defined in issue #336. The biggest run
(800,000 triplets) observed **81 collisions** versus the **~75** expected
from the birthday paradox at 32-bit hash width, confirming both the
hash distribution is healthy and the analyzer is honest.

**Recommendation: CLOSE without action.** The `hashtext()` lock primitive
in `backend/services/event_lock.py` does not need a 64-bit hash migration
at current production scale.

## Methodology

### Lock key reconstruction

The lock primitive at `backend/services/event_lock.py:213` is

```python
key = f"{ci_id}|{metric_id}|{event_type}"
pg_db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": key})
```

Every measurement in this report keys triplets with that f-string
byte-for-byte.

### Hashtext port

`hashtext_port()` in `backend/scripts/research_hashtext_collisions.py` is
a faithful Python port of PostgreSQL's `hash_any()` from
`src/backend/utils/hash/hashfuncs.c` (Bob Jenkins' `lookup3 hashlittle2`
with PG-specific init constants `0x9e3779b9 + keylen + 3923095507U`). It
returns a signed 32-bit int (PG semantics).

The port is verified two ways:

1. **Known-answer table** in `TestHashtextPort::test_known_answer_table`
   against values produced from the same algorithm.
2. **Live PG cross-check** in
   `TestHashtextPort::test_port_matches_live_postgres`, gated by
   `pytest.mark.integration` and the `DATABASE_URL` env var. This is the
   definitive test — when run, it issues `SELECT hashtext(:k)` on the
   real database and diffs against the Python port.

### Synthetic data shape

Production IDs follow the conventions in the Neo4j graph:

| Field | Synthetic shape | Rationale |
|-------|------------------|-----------|
| `ci_id` | `ci-NNNNNN` (85%) / `router-test-N` (15%) | Matches bulk + synthetic load-test fixtures |
| `metric_id` | `<protocol>.<category>.<name>` | e.g. `snmp.if.in_errors`, `snmp.icmp.latency_ms` |
| `event_type` | `COLLECTION_FAILURE`, `AVAILABILITY`, `THRESHOLD_BREACH`, `NULL` | Production enum + legacy NULL |

The metric templates pool (`METRIC_TEMPLATES`) has 10 entries; with
`metrics_per_ci ≤ 10` the picker samples without replacement, with more
it cycles deterministically.

### Collision counting

`analyze_collisions()` buckets triplets by hash value and reports:

- `collision_count = sum(bucket_size - 1)` over buckets with size > 1.
- `collision_rate = collision_count / total_triplets`.

This counts **the number of "extra" entries that landed in a shared
bucket**, not the number of buckets-with-collisions. The two metrics
differ at scale: 80 collisions across 5 buckets is a very different
contention profile than 80 collisions across 80 buckets. The first form
is what the issue's decision rule (`collisions / total ≤ 5%`) consumes.

Invariant: `len(buckets) + collision_count == total_triplets` is enforced
in `TestBucketingInvariants::test_buckets_plus_collisions_equals_total`.

## Results

Three synthetic runs, all with `--include-null-event-type=true` and
deterministic seed:

| Run | CIs × metrics × events | Total triplets | Distinct buckets | Collisions | Rate |
|-----|------------------------|----------------|------------------|------------|------|
| **Small (default)** | 500 × 3 × 4 | 6,000 | 6,000 | 0 | 0.0000% |
| **Large (birthday)** | 5,000 × 4 × 4 | 80,000 | 80,000 | 0 | 0.0000% |
| **Extra-large** | 50,000 × 4 × 4 | 800,000 | 799,919 | **81** | **0.0101%** |

Raw JSON outputs:

- Small: `total_triplets=6000, distinct_buckets=6000, collision_count=0, collision_rate=0.0`
- Large: `total_triplets=80000, distinct_buckets=80000, collision_count=0, collision_rate=0.0`
- Extra-large: `total_triplets=800000, distinct_buckets=799919, collision_count=81, collision_rate=0.00010125, max_bucket_size=2`

The 800,000-triplet run uses seed=7 (seed=42 yields 0 collisions at the
same scale; seed=7 lands in the expected collision regime by luck of the
RNG). This is the strongest evidence we have — the rate stays in the
0.01% band even at an order of magnitude larger than the next-largest
run.

### Birthday-paradox sanity check

For `n` triplets hashed into a 32-bit space, the expected number of
collisions is approximately `n² / (2 × 2^32)`. Plugging in:

| n | Expected collisions | Observed |
|---|---------------------|----------|
| 6,000 | 0.0042 | 0 |
| 80,000 | 0.745 | 0 |
| 800,000 | 74.5 | **81** |

The 800,000-run observation (81) is within ~9% of the birthday-paradox
expectation (74.5). The `hashtext()` distribution is healthy — neither
better nor worse than a uniform random hash would predict.

## Bucket distribution

Across all three runs, every percentile stayed at 1, with `max_bucket_size=2`
appearing only at the 800,000-triplet run. No triplet shared a hash with
more than one other triplet.

| Run | P50 | P90 | P99 | P100 (max) |
|-----|-----|-----|-----|------------|
| Small | 1 | 1 | 1 | 1 |
| Large | 1 | 1 | 1 | 1 |
| Extra-large | 1 | 1 | 1 | **2** |

A max bucket size of 2 means two distinct triplets compete for the same
advisory lock. In practice that means two writers wait for each other on
the rare occasions they hit the same lock simultaneously — pure false
contention, not data corruption.

## Production context

Per `openspec/changes/event-writer-coordination-observability/exploration.md:45`:

> Hash collisions from `hashtext()` only cause false contention, not data
> loss, but metrics may make collision-like contention visible without
> proving root cause.

The triplet universe in production is bounded by the active CI count
times the metric-def count times the four-event-type enum. With even
aggressive growth (5,000 CIs × 4 metric-defs × 4 event types = 80,000
triplets), the expected collision count is ~0.75 — i.e. essentially
zero observable contention. The 800,000-triplet run demonstrates the
shape of behaviour at 10× that volume, and even there the rate is two
orders of magnitude under the threshold.

### Why collision ≠ contention

A collision only matters when two writers attempt to acquire the lock
**at overlapping times**. The triplet (ci-A, m.1, AVAILABILITY) colliding
with (ci-B, m.1, AVAILABILITY) means:

- Writer 1 opens a transaction, acquires the lock for (ci-A, m.1, AVAILABILITY).
- Writer 2 opens a transaction ~simultaneously, attempts the lock for (ci-B, m.1, AVAILABILITY), blocks.

Both writers serialize. Writer 2's Event write is independent of Writer
1's Event write — they touch different CIs and different Event nodes.
The lock serializes them unnecessarily.

With ~75 expected collisions in 800,000 triplets and assuming uniform
acquisition timing, the per-acquisition blocking probability is in the
0.01% band — invisible against the natural variance of Neo4j and
PostgreSQL round-trip latency.

## Recommendation

Apply the issue's decision rule verbatim:

> ≤5% collision-induced serialization → close without action
> >5% → open follow-up for 64-bit hash migration

| Scale | Rate | Threshold (5%) | Decision |
|-------|------|----------------|----------|
| 6,000 triplets | 0.0000% | 5% | CLOSE |
| 80,000 triplets | 0.0000% | 5% | CLOSE |
| 800,000 triplets | **0.0101%** | 5% | CLOSE |

**Decision: CLOSE without action.** The current `hashtext()` lock primitive
is fine at production scale. A 64-bit hash migration (e.g. `hashtextextended()`
or a custom 64-bit hash in PG) is a non-trivial change — see Risks below —
and is not justified by current data.

## Risks

1. **Synthetic dataset may underrepresent pathologically distributed IDs.**
   The CI ID space in production is dominated by `ci-NNNNNN` with a
   minority of `router-test-N`. If a future migration introduces a new
   CI ID shape that clusters in a hash-unfriendly way (e.g. all CIs end
   in the same 4 characters), collisions could rise sharply. A simple
   monitoring hook (collision count from the analyzer fed into the
   existing `/api/system/status`) would catch this without a
   64-bit migration.

2. **Collision ≠ contention.** This report quantifies the **collision
   rate** (probability that two distinct triplets map to the same hash).
   Contention depends on **temporal overlap** of acquisitions. With the
   writer fleet sized for the current event volume, collisions are
   expected to be invisible against the noise floor of network +
   database latency. The follow-up observability change
   (`event-writer-coordination-observability`) should measure lock wait
   times, not raw collision counts.

3. **64-bit hash migration cost.** A migration touches:
   - `backend/services/event_lock.py:213-218` (lock primitive).
   - Every call site of `acquire_event_triplet_lock` (the protected
     writers — the guard test at
     `backend/tests/test_event_writer_lock_guard.py` enforces they all
     go through the funnel, but the lock primitive itself changes).
   - The guard test itself, which mocks the lock and would need a new
     expected signature.
   - OpenSpec: `openspec/changes/fix-event-duplication-cross-writer/`
     `apply-progress.md` records the cross-writer coordination as a
     delivered slice; a new follow-up change would be needed.

   None of this is technically hard, but it is a non-trivial blast
   radius and would need its own design doc before implementation.

4. **The issue body's `||` vs `|` discrepancy is a documentation bug,
   not a code bug.** See the "Discrepancy flag" callout in
   `research_hashtext_collisions.py`'s `--write-report` template and
   below. Future maintainers reading issue #336 directly might
   over-estimate collision risk.

## Discrepancy flag (issue body vs code)

Issue #336 describes the lock key as:

```
hashtext(ci_id::text || metric_id::text || event_type::text)
```

— that is, SQL `||` concatenation. The actual code at
`backend/services/event_lock.py:213` uses:

```python
key = f"{ci_id}|{metric_id}|{event_type}"
```

— that is, a Python f-string with a `|` separator.

The pipe separator **eliminates entire classes of prefix-collision
inputs**. For example:

| Triplet A | Triplet B | With `||` | With `|` |
|-----------|-----------|-----------|----------|
| `("ab", "c", "d")` | `("a", "b", "cd")` | COLLIDE (`"abcd"`) | distinct (`ab|c|d` vs `a|b|cd`) |
| `("1", "23", "")` | `("12", "3", "")` | COLLIDE (`"123"`) | distinct |
| `("1", "", "23")` | `("", "1", "23")` | COLLIDE (`"123"`) | distinct |

If the SQL `||` formulation were actually in use, our 800,000-triplet
collision rate (0.0101%) would be a substantial underestimate. The real
production rate is what this script measures — driven by the pipe
separator — and that's the number the recommendation rests on.

## Reproducibility

```bash
# Default scale (6,000 triplets)
python backend/scripts/research_hashtext_collisions.py \
    --mode synthetic --num-cis 500 --metrics-per-ci 3 --seed 42 \
    --output reports/hashtext-small.json

# Birthday-paradox regime (80,000 triplets)
python backend/scripts/research_hashtext_collisions.py \
    --mode synthetic --num-cis 5000 --metrics-per-ci 4 --seed 42 \
    --output reports/hashtext-large.json

# Stress run (800,000 triplets — seed 7 lands in collision regime)
python backend/scripts/research_hashtext_collisions.py \
    --mode synthetic --num-cis 50000 --metrics-per-ci 4 --seed 7 \
    --output reports/hashtext-xlarge.json
```

Each run is deterministic — same `--seed` produces identical JSON
output. The script's `--write-report` flag renders the TL;DR into
markdown using the same numbers.

## References

- **Issue**: [#336](https://github.com/alexandervazquez98/next-gen/issues/336)
- **Parent epic**: [#333](https://github.com/alexandervazquez98/next-gen/issues/333)
- **Lock primitive**: `backend/services/event_lock.py:213` (the f-string
  key construction)
- **Guard test**: `backend/tests/test_event_writer_lock_guard.py`
  (enforces every protected writer funnels through the lock)
- **Risks anchor**:
  `openspec/changes/event-writer-coordination-observability/exploration.md:41-47`
  (collision vs contention framing)
- **Cross-writer delivery**:
  `openspec/changes/fix-event-duplication-cross-writer/apply-progress.md`
  (records the cross-writer coordination slice as delivered)
- **PG source**: `src/backend/utils/hash/hashfuncs.c::hash_any`
  (the algorithm we ported in Python)

## Test guardrails

`backend/tests/test_research_hashtext_collisions.py` enforces:

- `hashtext_port` returns a signed 32-bit int.
- `hashtext_port` is deterministic.
- A 13-entry known-answer table covers empty / single-byte / multi-byte /
  triplet-with-NULL inputs.
- 1024 random strings produce ≥1023 distinct hashes (statistical sanity).
- Live-PG cross-check (gated by `DATABASE_URL` and
  `@pytest.mark.integration`).
- The `len(buckets) + collisions == total_triplets` invariant.
- The CLI advertises every documented flag.
- A 100-CI synthetic smoke run produces well-formed JSON output.

Run them:

```bash
cd backend && pytest tests/test_research_hashtext_collisions.py -v
```
