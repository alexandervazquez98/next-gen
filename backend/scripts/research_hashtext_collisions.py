"""Research script: investigate ``hashtext()`` triplet collision rate.

GitHub issue #336 — collision rate of PostgreSQL's ``hashtext()`` applied to
event-triplet advisory-lock keys. Issue #336's decision rule:

* ≤5% collision-induced serialization → close without action
* >5% → open follow-up for 64-bit hash migration

The actual lock primitive lives at ``backend/services/event_lock.py``:

    key = f"{ci_id}|{metric_id}|{event_type}"
    pg_db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": key})

— note the ``|`` separator (NOT the SQL ``||`` concatenation the issue body
mentions). That eliminates entire classes of prefix-collision inputs. See the
report (``docs/research-hashtext-collisions.md``) for the discrepancy flag.

This script ships:

1. A faithful Python port of PostgreSQL's ``hashtext()`` (which calls
   ``hash_any()`` from ``src/backend/utils/hash/hashfuncs.c`` — Bob Jenkins'
   lookup3 ``hashlittle2`` with PG-specific init constants). Returns signed
   32-bit int (PG semantics).
2. Synthetic data generation that mirrors production ID shapes
   (``ci-NNNNNN``, ``router-test-N``, ``<proto>.<category>.<name>``, the four
   production ``event_type`` values).
3. A collision analyzer with the invariant
   ``len(buckets) + collisions == total_triplets``.
4. Optional prod mode (read-only Neo4j scan) — never mutates.
5. JSON summary output and optional markdown report rendering.

Default mode is synthetic and is fully offline — no DB required. The script
never modifies any database.

References:

* PG source — ``src/backend/utils/hash/hashfuncs.c`` (``hash_any``).
* Lock call site — ``backend/services/event_lock.py:213``.
* Guard test — ``backend/tests/test_event_writer_lock_guard.py``.
* Risks anchor — ``openspec/changes/event-writer-coordination-observability/exploration.md:41``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path

logger = logging.getLogger("research.hashtext")

# ---------------------------------------------------------------------------
# Hashtext port
# ---------------------------------------------------------------------------
#
# Reference: PostgreSQL src/backend/utils/hash/hashfuncs.c (hash_any) which
# itself wraps Bob Jenkins' lookup3 hashlittle2 with PG-specific init
# constants. The function returns the C uint32 reinterpreted as int32, which
# is what ``SELECT hashtext(:k)`` returns in PG.
#
# Constants cross-checked against PG18+
# (https://github.com/postgres/postgres/blob/master/src/backend/utils/hash/hashfuncs.c):
#   - init seed: ``0x9e3779b9 + keylen + 3923095507U``
#   - mix:      6 round of subtract/xor/rotate (Jenkins lookup3)
#   - final:    8 round of xor/rotate/subtract (Jenkins lookup3)
#
# The integration test in ``test_research_hashtext_collisions.py::TestHashtextPort::
# test_port_matches_live_postgres`` is the definitive cross-check; it runs
# only when ``DATABASE_URL`` is set.
_MASK32 = 0xFFFFFFFF


def _rot32(x: int, n: int) -> int:
    """32-bit left rotation: ``ROTATE32(x, n)`` in PG's ``hashfuncs.c``."""
    n &= 31
    return ((x << n) | (x >> (32 - n))) & _MASK32


def _mix(a: int, b: int, c: int) -> tuple[int, int, int]:
    """PG ``mix(a, b, c)`` macro from ``hashfuncs.c``."""
    a = (a - c) & _MASK32
    a ^= _rot32(c, 4)
    c = (c + b) & _MASK32
    b = (b - a) & _MASK32
    b ^= _rot32(a, 6)
    a = (a + c) & _MASK32
    c = (c - b) & _MASK32
    c ^= _rot32(b, 8)
    b = (b + a) & _MASK32
    a = (a - c) & _MASK32
    a ^= _rot32(c, 16)
    c = (c + b) & _MASK32
    b = (b - a) & _MASK32
    b ^= _rot32(a, 19)
    a = (a + c) & _MASK32
    c = (c - b) & _MASK32
    c ^= _rot32(b, 4)
    b = (b + a) & _MASK32
    return a, b, c


def _final(a: int, b: int, c: int) -> tuple[int, int, int]:
    """PG ``ROTATE_HIGH_LOW_AND_FINALIZE(a, b, c)`` macro from ``hashfuncs.c``."""
    c ^= b
    c = (c - _rot32(b, 14)) & _MASK32
    a ^= c
    a = (a - _rot32(c, 11)) & _MASK32
    b ^= a
    b = (b - _rot32(a, 25)) & _MASK32
    c ^= b
    c = (c - _rot32(b, 16)) & _MASK32
    a ^= c
    a = (a - _rot32(c, 4)) & _MASK32
    b ^= a
    b = (b - _rot32(a, 14)) & _MASK32
    c ^= b
    c = (c - _rot32(b, 24)) & _MASK32
    return a, b, c


def hashtext_port(key: bytes | str) -> int:
    """Python port of PostgreSQL's ``hashtext(text)``.

    Returns a signed 32-bit integer, matching ``SELECT hashtext(:k)`` exactly.

    Parameters
    ----------
    key:
        Bytes (treated as raw bytes) or string (encoded as UTF-8). PG's
        ``hashtext`` takes ``text``, which is server-side encoding-aware; in
        practice production always passes ASCII so UTF-8 vs latin1 vs ascii
        makes no difference.

    Notes
    -----
    The C implementation reads ``k[0..10]`` unconditionally even when
    ``keylen < 12``; that's UB in the general case but in practice the
    server allocator hands out zero-padded memory. We emulate that with a
    12-byte zero tail. This is sufficient because the trailing reads only
    ever add to ``a``, ``b``, or ``c`` via XOR/add — never subtract.
    """
    if isinstance(key, str):
        key = key.encode("utf-8")
    # Pad so k[i] for i in [0..10] is always in-bounds and equals the
    # zero-padding PG sees after the buffer. This preserves the algorithm's
    # behaviour for inputs of every length 0..MAX.
    padded = key + b"\x00" * 12
    keylen = len(key)

    a = b = c = (0x9E3779B9 + keylen + 3923095507) & _MASK32

    # Main loop: 12-byte blocks.
    pos = 0
    while keylen - pos > 12:
        a = (
            a
            + (
                padded[pos]
                | (padded[pos + 1] << 8)
                | (padded[pos + 2] << 16)
                | (padded[pos + 3] << 24)
            )
        ) & _MASK32
        b = (
            b
            + (
                padded[pos + 4]
                | (padded[pos + 5] << 8)
                | (padded[pos + 6] << 16)
                | (padded[pos + 7] << 24)
            )
        ) & _MASK32
        c = (
            c
            + (
                padded[pos + 8]
                | (padded[pos + 9] << 8)
                | (padded[pos + 10] << 16)
                | (padded[pos + 11] << 24)
            )
        ) & _MASK32
        a, b, c = _mix(a, b, c)
        pos += 12

    # Tail: handle last 0..11 bytes. PG reads k[0..10] unconditionally; our
    # padded buffer keeps those slots zero when the input is short.
    c = (c + (padded[pos + 8] | (padded[pos + 9] << 8) | (padded[pos + 10] << 16))) & _MASK32
    # ``c += keylen - 12`` in C — when keylen < 12, the right-hand side is
    # negative, but PG casts via ``uint32`` so it folds to a large positive.
    c = (c + (keylen - 12)) & _MASK32
    b = (
        b
        + (
            padded[pos + 4]
            | (padded[pos + 5] << 8)
            | (padded[pos + 6] << 16)
            | (padded[pos + 7] << 24)
        )
    ) & _MASK32
    a = (
        a
        + (padded[pos] | (padded[pos + 1] << 8) | (padded[pos + 2] << 16) | (padded[pos + 3] << 24))
    ) & _MASK32

    a, b, c = _final(a, b, c)

    # Reinterpret uint32 as int32 — PG returns int4, which is signed.
    out = c
    if out >= 0x80000000:
        out -= 0x100000000
    return out


# ---------------------------------------------------------------------------
# Lock-key construction (matches event_lock.py byte-for-byte)
# ---------------------------------------------------------------------------

EVENT_TYPE_VALUES: tuple[str, ...] = (
    "COLLECTION_FAILURE",
    "AVAILABILITY",
    "THRESHOLD_BREACH",
    "",  # legacy NULL event_type, encoded as empty string by Neo4j → PG round-trip
)


def build_lock_key(ci_id: str, metric_id: str, event_type: str | None) -> bytes:
    """Reproduce ``backend/services/event_lock.py:213`` byte-for-byte.

    The Python f-string uses ``|`` as the separator. ``None`` and the empty
    string both render as the empty string (PG ``NULL`` → b'' via the
    SQLAlchemy adapter). Any deviation here breaks the research.
    """
    et = "" if event_type is None else str(event_type)
    return f"{ci_id}|{metric_id}|{et}".encode()


# ---------------------------------------------------------------------------
# Synthetic data generation
# ---------------------------------------------------------------------------
#
# The shapes below mirror production ID conventions seen in the Neo4j graph:
# CIs follow ``ci-<zero-padded>`` (also ``router-test-<n>`` for synthetic
# load test fixtures); MetricDefs follow ``<protocol>.<category>.<name>``
# (e.g. ``snmp.if.in_errors``); event_type enum is documented in
# ``docs/domain/business-model.md``.

METRIC_TEMPLATES: tuple[str, ...] = (
    "snmp.if.in_errors",
    "snmp.if.out_errors",
    "snmp.if.utilization",
    "snmp.if.discards",
    "snmp.icmp.latency_ms",
    "snmp.icmp.packet_loss_pct",
    "snmp.cpu.utilization_pct",
    "snmp.memory.used_pct",
    "snmp.collection_failure",
    "snmp.sysuptime.seconds",
)


def _generate_ci_ids(n: int, rng: random.Random) -> list[str]:
    """Mix of two production shapes: ``ci-NNNNNN`` and ``router-test-N``.

    The split is deterministic from ``rng`` so synthetic runs are
    reproducible.
    """
    out: list[str] = []
    for i in range(n):
        if rng.random() < 0.85:
            # Bulk: zero-padded CI identifiers (the dominant shape in prod).
            out.append(f"ci-{i + 1:06d}")
        else:
            # Sporadic synthetic load-test fixtures.
            out.append(f"router-test-{i + 1}")
    return out


def _generate_metric_ids(metrics_per_ci: int, rng: random.Random) -> list[str]:
    """Pick ``metrics_per_ci`` distinct MetricDef IDs per CI, drawn without
    replacement from ``METRIC_TEMPLATES``. With ``len(METRIC_TEMPLATES) == 10``
    we cap at 10 to keep things realistic; if more is requested we cycle.
    """
    if metrics_per_ci > len(METRIC_TEMPLATES):
        # Wrap-around sampling so very large ``metrics_per_ci`` still
        # produces a deterministic set.
        pool = METRIC_TEMPLATES * ((metrics_per_ci // len(METRIC_TEMPLATES)) + 1)
    else:
        pool = list(METRIC_TEMPLATES)
    return rng.sample(pool, metrics_per_ci)


def generate_synthetic_triplets(
    num_cis: int,
    metrics_per_ci: int,
    samples_per_triplet: int,
    *,
    include_null_event_type: bool,
    seed: int,
) -> list[tuple[str, str, str | None]]:
    """Produce ``(ci_id, metric_id, event_type)`` triplets.

    ``samples_per_triplet > 1`` simulates the same triplet being seen multiple
    times (e.g. duplicate writer attempts); the lock is keyed on the triplet,
    so duplicates always collide. Default ``samples_per_triplet == 1`` matches
    the steady-state production behaviour where each triplet is seen once.
    """
    rng = random.Random(seed)
    event_types: list[str | None] = list(EVENT_TYPE_VALUES)
    if not include_null_event_type:
        event_types = [et for et in event_types if et]

    ci_ids = _generate_ci_ids(num_cis, rng)
    triplets: list[tuple[str, str, str | None]] = []
    for ci_id in ci_ids:
        metric_ids = _generate_metric_ids(metrics_per_ci, rng)
        for metric_id in metric_ids:
            for et in event_types:
                for _ in range(max(1, samples_per_triplet)):
                    triplets.append((ci_id, metric_id, et))
    return triplets


# ---------------------------------------------------------------------------
# Collision analyzer
# ---------------------------------------------------------------------------


def analyze_collisions(triplets: Sequence[tuple[str, str, str | None]]) -> dict:
    """Bucket triplets by ``hashtext(build_lock_key(...))`` and report stats.

    The output schema is the source of truth for both the report's numbers
    and the test invariants. Required keys:

    * ``total_triplets`` — count of triplets fed in
    * ``distinct_buckets`` — distinct hash buckets (= distinct hash values)
    * ``collision_count`` — ``sum(bucket_size - 1)`` over all buckets; the
      number of "extra" entries that landed in a shared bucket (NOT the
      number of buckets-with-collisions — issue #336's rate is
      ``collisions / total``)
    * ``collision_rate`` — ``collision_count / total_triplets``
    * ``max_bucket_size`` — largest bucket
    * ``percentiles`` — ``{p50, p90, p99, p100}`` bucket-size distribution
    * ``hash_min`` / ``hash_max`` — min and max int32 hash values

    Invariant: ``distinct_buckets + collision_count == total_triplets``.
    """
    hashes: list[int] = [hashtext_port(build_lock_key(ci, m, et)) for ci, m, et in triplets]
    counts = Counter(hashes)
    total = len(hashes)
    buckets = len(counts)
    collision_count = sum(c - 1 for c in counts.values() if c > 1)
    max_bucket = max(counts.values()) if counts else 0

    sizes = sorted(counts.values())
    if sizes:
        p50 = _percentile(sizes, 50)
        p90 = _percentile(sizes, 90)
        p99 = _percentile(sizes, 99)
        p100 = sizes[-1]
    else:
        p50 = p90 = p99 = p100 = 0

    return {
        "total_triplets": total,
        "distinct_buckets": buckets,
        "collision_count": collision_count,
        "collision_rate": (collision_count / total) if total else 0.0,
        "max_bucket_size": max_bucket,
        "hash_min": min(hashes) if hashes else 0,
        "hash_max": max(hashes) if hashes else 0,
        "percentiles": {
            "p50": p50,
            "p90": p90,
            "p99": p99,
            "p100": p100,
        },
    }


def _percentile(sorted_values: Sequence[int], p: int) -> int:
    """Linear-interpolation percentile on a pre-sorted sequence."""
    if not sorted_values:
        return 0
    n = len(sorted_values)
    rank = (p / 100.0) * (n - 1)
    lo = int(rank)
    hi = min(lo + 1, n - 1)
    frac = rank - lo
    return int(round(sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac))


# ---------------------------------------------------------------------------
# Prod mode (Neo4j)
# ---------------------------------------------------------------------------


def fetch_prod_triplets_from_neo4j(
    uri: str, user: str, password: str
) -> list[tuple[str, str, str | None]]:
    """Read-only Neo4j scan.

    Mirrors the import style in ``backend/seed_dummy_ci.py``. We only use
    the official ``neo4j`` driver — no extra deps. The query is a plain
    MATCH that never mutates.
    """
    from neo4j import GraphDatabase  # noqa: WPS433 — runtime import on purpose

    driver = GraphDatabase.driver(uri, auth=(user, password))
    triplets: list[tuple[str, str, str | None]] = []
    query = (
        "MATCH (e:Event) "
        "RETURN e.ci_id AS ci_id, e.metric_id AS metric_id, e.event_type AS event_type"
    )
    with driver.session() as session:
        for record in session.run(query):
            ci = record.get("ci_id")
            metric = record.get("metric_id")
            et = record.get("event_type")
            if ci is None or metric is None:
                # Skip rows missing required identifiers — they're noise, not signal.
                continue
            triplets.append((str(ci), str(metric), et))
    driver.close()
    return triplets


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


REPORT_TEMPLATE = """# Hashtext collision rate — research report (issue #336)

> Generated by `backend/scripts/research_hashtext_collisions.py`.
> Do not edit by hand — rerun the script to refresh.

## TL;DR

- Mode: **{mode}**
- Distinct triplets: **{total_triplets}**
- Distinct hash buckets: **{distinct_buckets}**
- Collision count (sum of bucket_size − 1): **{collision_count}**
- Collision rate: **{collision_rate_pct:.4f}%**
- Max bucket size: **{max_bucket_size}**
- Decision (issue rule, ≤5% close, >5% follow-up): **{decision}**

## Configuration

| Parameter | Value |
|-----------|-------|
| num_cis | {num_cis} |
| metrics_per_ci | {metrics_per_ci} |
| samples_per_triplet | {samples_per_triplet} |
| seed | {seed} |
| include_null_event_type | {include_null_event_type} |

## Bucket size distribution

| Percentile | Bucket size |
|------------|-------------|
| P50 | {p50} |
| P90 | {p90} |
| P99 | {p99} |
| P100 | {p100} |

## Hash range

- min: {hash_min}
- max: {hash_max}

## Discrepancy flag

Issue #336 describes the lock key as `hashtext(ci_id::text || metric_id::text || event_type::text)`
(SQL `||` concatenation). The actual code in `backend/services/event_lock.py:213`
uses an f-string with a `|` separator:

    key = f"{{ci_id}}|{{metric_id}}|{{event_type}}"

That eliminates prefix-collision classes — e.g. `("ab", "c", "d")` and
`("a", "b", "cd")` produce different keys. Only true 32-bit hashtext
collisions on distinct pipe-joined strings remain.

If the original SQL `||` formulation were in use, collision rates would be
**higher** than what this script measures (more inputs map to the same key).
Treat the issue body as describing a hypothetical worst case; the production
behaviour matches what we measure here.

## Methodology

1. Build keys via `f"{{ci_id}}|{{metric_id}}|{{event_type}}"` — byte-for-byte
   match to `event_lock.py`.
2. Hash each key with `hashtext_port` (Python port of PG `hash_any`).
3. Bucket by hash value; count collisions as `sum(bucket_size - 1)`.
4. Compute the rate as `collisions / total_triplets`.
5. Apply the issue's decision rule verbatim.

## Production context

Lock acquisition goes through `acquire_event_triplet_lock` in
`backend/services/event_lock.py` — the single funnel for every protected
writer. The guard test `backend/tests/test_event_writer_lock_guard.py`
prevents new writers from skipping the lock.

Per `openspec/changes/event-writer-coordination-observability/exploration.md:45`:

> Hash collisions from `hashtext()` only cause false contention, not data
> loss, but metrics may make collision-like contention visible without proving
> root cause.

A high collision rate does NOT corrupt data — it serializes writers that
should run in parallel, increasing the chance of pool exhaustion under load.
"""


def render_report(summary: dict) -> str:
    cfg = summary.get("config", {})
    pcts = summary.get("percentiles", {})
    rate = summary.get("collision_rate", 0.0)
    decision = "CLOSE without action (≤5%)" if rate <= 0.05 else "OPEN follow-up (>5%)"

    return REPORT_TEMPLATE.format(
        mode=summary.get("mode", "unknown"),
        total_triplets=summary.get("total_triplets", 0),
        distinct_buckets=summary.get("distinct_buckets", 0),
        collision_count=summary.get("collision_count", 0),
        collision_rate_pct=rate * 100.0,
        max_bucket_size=summary.get("max_bucket_size", 0),
        decision=decision,
        num_cis=cfg.get("num_cis", "?"),
        metrics_per_ci=cfg.get("metrics_per_ci", "?"),
        samples_per_triplet=cfg.get("samples_per_triplet", "?"),
        seed=cfg.get("seed", "?"),
        include_null_event_type=cfg.get("include_null_event_type", "?"),
        p50=pcts.get("p50", 0),
        p90=pcts.get("p90", 0),
        p99=pcts.get("p99", 0),
        p100=pcts.get("p100", 0),
        hash_min=summary.get("hash_min", 0),
        hash_max=summary.get("hash_max", 0),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="research_hashtext_collisions",
        description=(
            "Investigate hashtext() triplet collision rate (issue #336). "
            "Default mode is synthetic and fully offline — no DB required."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("synthetic", "prod", "both"),
        default="synthetic",
        help="Data source: synthetic (default, offline), prod (Neo4j read-only), or both.",
    )
    parser.add_argument(
        "--num-cis", type=int, default=500, help="Synthetic CI count (default 500)."
    )
    parser.add_argument(
        "--metrics-per-ci",
        type=int,
        default=3,
        help="Synthetic metric-def count per CI (default 3).",
    )
    parser.add_argument(
        "--samples-per-triplet",
        type=int,
        default=1,
        help="Multi-event instances per (ci, metric, event_type); default 1.",
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="RNG seed for synthetic runs (default 42)."
    )
    parser.add_argument(
        "--include-null-event-type",
        type=lambda s: s.lower() in ("1", "true", "yes", "y"),
        default=True,
        help="Include legacy NULL event_type (empty string); default true.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write JSON summary to this path (default: stdout).",
    )
    parser.add_argument(
        "--write-report",
        type=Path,
        default=None,
        help="Render the markdown report template with the JSON summary into this path.",
    )
    parser.add_argument(
        "--neo4j-uri",
        default=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        help="Neo4j URI for --mode prod (env NEO4J_URI).",
    )
    parser.add_argument(
        "--neo4j-user",
        default=os.environ.get("NEO4J_USER", "neo4j"),
        help="Neo4j user (env NEO4J_USER).",
    )
    parser.add_argument(
        "--neo4j-password",
        default=os.environ.get("NEO4J_PASSWORD", os.environ.get("NEO4J_PASS", "")),
        help="Neo4j password (env NEO4J_PASSWORD / NEO4J_PASS).",
    )
    return parser.parse_args(list(argv))


def _run_synthetic(args: argparse.Namespace) -> dict:
    triplets = generate_synthetic_triplets(
        num_cis=args.num_cis,
        metrics_per_ci=args.metrics_per_ci,
        samples_per_triplet=args.samples_per_triplet,
        include_null_event_type=args.include_null_event_type,
        seed=args.seed,
    )
    result = analyze_collisions(triplets)
    result["mode"] = "synthetic"
    result["config"] = {
        "num_cis": args.num_cis,
        "metrics_per_ci": args.metrics_per_ci,
        "samples_per_triplet": args.samples_per_triplet,
        "seed": args.seed,
        "include_null_event_type": args.include_null_event_type,
    }
    return result


def _run_prod(args: argparse.Namespace) -> dict:
    triplets = fetch_prod_triplets_from_neo4j(
        uri=args.neo4j_uri,
        user=args.neo4j_user,
        password=args.neo4j_password,
    )
    result = analyze_collisions(triplets)
    result["mode"] = "prod"
    result["config"] = {"source": "neo4j", "uri": args.neo4j_uri}
    return result


def main(argv: Iterable[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    summaries: list[dict] = []
    if args.mode in ("synthetic", "both"):
        summaries.append(_run_synthetic(args))
    if args.mode in ("prod", "both"):
        if not args.neo4j_password:
            logger.error("--mode prod requires --neo4j-password or NEO4J_PASSWORD env")
            return 2
        summaries.append(_run_prod(args))

    payload = {"runs": summaries}
    encoded = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(encoded)
        logger.info("wrote JSON summary to %s", args.output)
    else:
        print(encoded)

    if args.write_report:
        for run in summaries:
            args.write_report.write_text(render_report(run))
            logger.info("wrote report for mode=%s to %s", run.get("mode"), args.write_report)

    return 0


if __name__ == "__main__":
    sys.exit(main())
