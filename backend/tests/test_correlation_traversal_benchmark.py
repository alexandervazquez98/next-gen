"""Contract tests for the #539 correlation traversal latency benchmark.

The benchmark itself needs a live Neo4j, so these tests guard its contract:
the budget, the refusal to touch a database without an explicit
acknowledgement, the shape of the two compared queries, and the report
arithmetic.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.correlation_traversal_benchmark import (
    BASELINE_QUERY,
    BUDGET_MS,
    build_report,
    main,
    status_gated_query,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
GUIDE = REPO_ROOT / "docs" / "correlation-topology-guide.md"


def test_budget_matches_the_documented_contract():
    """The benchmark budget is the one the reconciled contract states."""
    assert BUDGET_MS == 50.0
    guide = GUIDE.read_text(encoding="utf-8")
    assert "≤50 ms added latency" in guide


def test_db_backed_mode_requires_an_explicit_acknowledgement(capsys):
    """Running the benchmark without --allow-db must not touch the database."""
    exit_code = main([])

    assert exit_code == 2
    assert "--allow-db" in capsys.readouterr().err


def test_status_gated_query_reads_the_link_status_in_the_same_statement():
    """The measured query must be the one the repository actually renders."""
    query = status_gated_query()

    assert ":PhysicalLink" in query
    assert "CONNECTED_VIA" in query
    assert "propagating_link_statuses" in query
    assert "pl.status IN $propagating_link_statuses" in query


def test_baseline_query_is_the_pre_539_pure_ci_traversal():
    """The baseline must not contain any PhysicalLink hop, or the delta is meaningless."""
    assert ":PhysicalLink" not in BASELINE_QUERY
    assert "CONNECTED_VIA" not in BASELINE_QUERY
    assert "DEPENDS_ON|HOSTED_ON|CONNECTS_TO" in BASELINE_QUERY


def test_report_reports_the_added_latency_and_the_budget_verdict():
    """The report states the added latency, the budget, and whether it is met."""
    report = build_report(
        baseline={"n": 100, "median_ms": 4.5, "p95_ms": 8.9, "max_ms": 12.0},
        current={"n": 100, "median_ms": 5.0, "p95_ms": 9.4, "max_ms": 13.0},
        topology={"ci_count": 100, "physical_link_count": 50},
    )

    assert report["added_latency_median_ms"] == 0.5
    assert report["added_latency_p95_ms"] == 0.5
    assert report["budget_ms"] == 50.0
    assert report["within_budget"] is True
    assert report["topology"] == {"ci_count": 100, "physical_link_count": 50}
    json.dumps(report)


def test_report_fails_the_budget_when_the_added_latency_is_too_high():
    """A regression past the budget must be reported as a budget failure."""
    report = build_report(
        baseline={"n": 100, "median_ms": 4.5, "p95_ms": 8.9, "max_ms": 12.0},
        current={"n": 100, "median_ms": 60.0, "p95_ms": 70.0, "max_ms": 80.0},
    )

    assert report["within_budget"] is False
    assert report["added_latency_median_ms"] > BUDGET_MS
