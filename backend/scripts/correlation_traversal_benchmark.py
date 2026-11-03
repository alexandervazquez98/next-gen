"""Latency benchmark for the #539 status-gated PhysicalLink correlation traversal.

The reconciled contract in ``docs/correlation-topology-guide.md`` sets a
performance budget for the ``re_query_per_correlation`` decision: at most
50 ms of ADDED latency in a topology with 100 CIs and 50 PhysicalLinks,
measured in PR2a2. This script is that measurement.

It seeds an isolated topology (unique run prefix, removed afterwards) and
compares two traversals on the SAME graph:

* the pre-#539 baseline — the pure-CI ``DEPENDS_ON``/``HOSTED_ON``/
  ``CONNECTS_TO`` traversal with a variable-length path;
* the current status-gated traversal, rendered from
  ``repositories.topology_repo.correlation_path_variants()``.

The reported "added latency" is the difference between the two, so the budget
is measured against the behaviour the change actually replaces.

This script writes to the database it is pointed at. It only ever creates
nodes whose id starts with its own run prefix and removes exactly those nodes
at the end, so it is safe to run against a test instance — but the DB-backed
mode must be acknowledged explicitly with ``--allow-db``.

Usage::

    python -m scripts.correlation_traversal_benchmark --allow-db --json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from repositories.topology_repo import (  # noqa: E402
    CORRELATION_MAX_DEPTH,
    _correlation_parent_branches,
)

#: The performance budget from the reconciled contract: at most this much
#: ADDED latency, in milliseconds, for the ``re_query_per_correlation`` decision
#: in a topology with 100 CIs and 50 PhysicalLinks.
BUDGET_MS = 50.0

#: The pre-#539 traversal, kept verbatim so the measurement compares against
#: the behaviour the status-gated traversal replaces.
BASELINE_QUERY = """
MATCH (ci:CI {id: $ci_id})
MATCH (ci)-[r:DEPENDS_ON|HOSTED_ON|CONNECTS_TO*1..3]->(parent:CI)
MATCH (parent)-[:HAS_EVENT]->(pe:Event)
WHERE pe.status IN ['OPEN', 'ACK']
RETURN pe.id AS parent_event_id,
       pe.ci_id AS parent_ci_id,
       pe.correlation_type AS correlation_type,
       pe.root_cause_ci_id AS root_cause_ci_id
ORDER BY CASE pe.severity WHEN 'CRITICAL' THEN 1 WHEN 'WARNING' THEN 2 ELSE 3 END ASC, pe.created_at ASC
LIMIT 1
"""


def status_gated_query(max_depth: int = CORRELATION_MAX_DEPTH) -> str:
    """Return the current status-gated traversal, rendered from the shared model."""
    return f"""
MATCH (ci:CI {{id: $ci_id}})
CALL {{
{_correlation_parent_branches(max_depth)}
}}
MATCH (parent)-[:HAS_EVENT]->(pe:Event)
WHERE pe.status IN ['OPEN', 'ACK']
RETURN pe.id AS parent_event_id,
       pe.ci_id AS parent_ci_id,
       pe.correlation_type AS correlation_type,
       pe.root_cause_ci_id AS root_cause_ci_id,
       link_id,
       link_status
ORDER BY CASE pe.severity WHEN 'CRITICAL' THEN 1 WHEN 'WARNING' THEN 2 ELSE 3 END ASC, pe.created_at ASC
LIMIT 1
"""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure the added latency of the #539 status-gated PhysicalLink traversal"
    )
    parser.add_argument("--ci-count", type=int, default=100)
    parser.add_argument("--physical-link-count", type=int, default=50)
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--budget-ms", type=float, default=BUDGET_MS)
    parser.add_argument(
        "--allow-db",
        action="store_true",
        help="Required: this benchmark writes to the configured Neo4j instance",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    return parser


def _percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, int(len(ordered) * fraction))
    return ordered[index]


def build_report(
    baseline: dict[str, float],
    current: dict[str, float],
    budget_ms: float = BUDGET_MS,
    topology: dict[str, int] | None = None,
) -> dict[str, object]:
    """Assemble the benchmark report and its budget verdict."""
    added_median = round(current["median_ms"] - baseline["median_ms"], 3)
    added_p95 = round(current["p95_ms"] - baseline["p95_ms"], 3)
    within_budget = added_median <= budget_ms and added_p95 <= budget_ms
    return {
        "topology": topology or {},
        "baseline_ms": baseline,
        "status_gated_ms": current,
        "added_latency_median_ms": added_median,
        "added_latency_p95_ms": added_p95,
        "budget_ms": budget_ms,
        "within_budget": within_budget,
    }


def _seed(session, prefix: str, ci_count: int, link_count: int) -> list[str]:
    """Create an isolated topology and return the CI ids to traverse."""
    ci_ids = [f"{prefix}-CI-{index}" for index in range(ci_count)]
    session.run(
        "UNWIND $ids AS id CREATE (c:CI {id: id})",
        ids=ci_ids,
    )
    session.run(
        "CREATE (m:MetricDef {id: $mid, can_propagate: true})",
        mid=f"{prefix}-M1",
    )
    # Each PhysicalLink joins two endpoint CIs. Both endpoints point AT the
    # link, which is the canonical shape written by PhysicalLinkRepo.create().
    for index in range(link_count):
        link_id = f"{prefix}-PL-{index}"
        session.run(
            "CREATE (pl:PhysicalLink {id: $lid, status: 'UP'})",
            lid=link_id,
        )
        for endpoint in (2 * index, 2 * index + 1):
            if endpoint >= ci_count:
                break
            session.run(
                "MATCH (x:CI {id: $cid}), (p:PhysicalLink {id: $lid}) "
                "CREATE (x)-[:CONNECTED_VIA]->(p)",
                cid=ci_ids[endpoint],
                lid=link_id,
            )
    # DEPENDS_ON edges, so the pure-CI baseline has real work to do.
    for index in range(ci_count - 1):
        session.run(
            "MATCH (x:CI {id: $a}), (y:CI {id: $b}) CREATE (x)-[:DEPENDS_ON]->(y)",
            a=ci_ids[index],
            b=ci_ids[index + 1],
        )
    # OPEN events on every third CI.
    for index in range(0, ci_count, 3):
        session.run(
            "CREATE (e:Event {id: $eid, status: 'OPEN', severity: 'CRITICAL',"
            " ci_id: $cid, correlation_type: 'ROOT', root_cause_ci_id: $cid,"
            " created_at: datetime()})"
            "CREATE (c:CI {id: $cid})-[:HAS_EVENT]->(e)",
            eid=f"{prefix}-E-{index}",
            cid=ci_ids[index],
        )
    return ci_ids


def _measure(session, query: str, ci_ids: list[str], iterations: int) -> dict[str, float]:
    samples: list[float] = []
    for _ in range(3):  # warm-up
        for ci_id in ci_ids:
            list(session.run(query, ci_id=ci_id, propagating_link_statuses=["UNKNOWN", "UP"]))
    for _ in range(iterations):
        for ci_id in ci_ids:
            started = time.perf_counter()
            list(session.run(query, ci_id=ci_id, propagating_link_statuses=["UNKNOWN", "UP"]))
            samples.append((time.perf_counter() - started) * 1000)
    return {
        "n": len(samples),
        "median_ms": round(statistics.median(samples), 3),
        "p95_ms": round(_percentile(samples, 0.95), 3),
        "max_ms": round(max(samples), 3),
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.allow_db:
        print(
            "This benchmark writes to the configured Neo4j instance. "
            "Re-run with --allow-db to acknowledge.",
            file=sys.stderr,
        )
        return 2

    from database import get_db

    prefix = f"PERFBENCH-{uuid.uuid4().hex[:12]}"
    driver = get_db()
    try:
        with driver.session() as session:
            session.run("MATCH (n) WHERE n.id STARTS WITH $prefix DETACH DELETE n", prefix=prefix)
            ci_ids = _seed(session, prefix, args.ci_count, args.physical_link_count)
            baseline = _measure(session, BASELINE_QUERY, ci_ids, args.iterations)
            current = _measure(session, status_gated_query(), ci_ids, args.iterations)
            session.run("MATCH (n) WHERE n.id STARTS WITH $prefix DETACH DELETE n", prefix=prefix)
    finally:
        driver.close()

    report = build_report(
        baseline,
        current,
        budget_ms=args.budget_ms,
        topology={
            "ci_count": args.ci_count,
            "physical_link_count": args.physical_link_count,
        },
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["within_budget"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
