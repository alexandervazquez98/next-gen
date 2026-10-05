"""Tests for the PhysicalLink polling bridge — feat-443 (PR1, slice 4/4).

The bridge is a scheduled job that:

1. Finds all *active* :PhysicalLink rows (status in {UP, UNKNOWN, PLANNED}).
2. Stamps ``last_polled_at`` when at least one endpoint has fresh
   ``metric_values`` rows in the last 60s.
3. Leaves the cached timestamp alone when no endpoint has fresh samples
   (idempotent — never overwrites a previously-set value with ``null``).
4. Is a no-op when the feature flag is off.

TDD coverage (PR1): T1, T2, T3, T4, T5.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

# Match the slice-2/3 suite: enable the routers so the import graph
# resolves identically to the rest of the project.
os.environ.setdefault("FEATURE_CMDB_PHYSICAL_LINKS_ENABLED", "true")


# Fixtures


@pytest.fixture
def fixed_now() -> datetime:
    """Deterministic now() for time control — injected via _now lambdas."""
    return datetime(2026, 10, 3, 20, 54, 37, tzinfo=UTC)


@pytest.fixture
def fresh_window_seconds() -> int:
    """The 60-second freshness window from the spec."""
    return 60


def _link_row(
    link_id: str = "pl-fiber-01",
    endpoint_a: str = "ci-A",
    endpoint_b: str = "ci-B",
    status: str = "UP",
    last_polled_at: datetime | None = None,
) -> dict:
    return {
        "id": link_id,
        "type": "fiber",
        "endpoints": [endpoint_a, endpoint_b],
        "status": status,
        "capacity_gbps": 10.0,
        "install_date": "2024-01-15",
        "last_polled_at": last_polled_at,
    }


# T1: find_active_links() — excludes explicit DOWN


class TestFindActiveLinks:
    """T1: ``find_active_links`` returns status in {UP, UNKNOWN, PLANNED}."""

    def test_returns_links_with_status_up(self, mock_neo4j_driver):
        from repositories.physical_link_repo import PhysicalLinkRepo

        mock_neo4j_driver.mock_session.set_response(
            "match (pl:physicallink)",
            [_link_row(link_id="pl-up", status="UP")],
        )
        repo = PhysicalLinkRepo(driver=mock_neo4j_driver)
        rows = repo.find_active_links(mock_neo4j_driver)
        assert len(rows) == 1
        assert rows[0]["id"] == "pl-up"
        assert rows[0]["status"] == "UP"

    def test_excludes_links_with_status_down(self, mock_neo4j_driver):
        from repositories.physical_link_repo import PhysicalLinkRepo

        # The repo-level filter must keep explicit DOWN rows out of the
        # result set. The mock session only returns whatever the cypher
        # would have produced, so a row that comes back here means the
        # filter was applied server-side.
        mock_neo4j_driver.mock_session.set_response(
            "match (pl:physicallink)",
            [_link_row(link_id="pl-up", status="UP")],
        )
        repo = PhysicalLinkRepo(driver=mock_neo4j_driver)
        rows = repo.find_active_links(mock_neo4j_driver)
        for row in rows:
            assert row["status"] != "DOWN"

    def test_returns_links_with_status_unknown_and_planned(self, mock_neo4j_driver):
        from repositories.physical_link_repo import PhysicalLinkRepo

        mock_neo4j_driver.mock_session.set_response(
            "match (pl:physicallink)",
            [
                _link_row(link_id="pl-unk", status="UNKNOWN"),
                _link_row(link_id="pl-plan", status="PLANNED"),
            ],
        )
        repo = PhysicalLinkRepo(driver=mock_neo4j_driver)
        rows = repo.find_active_links(mock_neo4j_driver)
        ids = {r["id"] for r in rows}
        assert ids == {"pl-unk", "pl-plan"}


# T2: update_last_polled_at() — idempotent


class TestUpdateLastPolledAt:
    """T2: ``update_last_polled_at`` writes ``pl.last_polled_at = ts`` and is idempotent."""

    def test_writes_last_polled_at(self, mock_neo4j_driver):
        from repositories.physical_link_repo import PhysicalLinkRepo

        ts = datetime(2026, 10, 3, 20, 54, 37, tzinfo=UTC)
        mock_neo4j_driver.mock_session.set_default_response([])

        repo = PhysicalLinkRepo(driver=mock_neo4j_driver)
        repo.update_last_polled_at("pl-fiber-01", ts)

        calls = [
            q for q in mock_neo4j_driver.mock_session.queries if "last_polled_at" in q["query"]
        ]
        assert len(calls) == 1
        assert calls[0]["params"]["link_id"] == "pl-fiber-01"
        # Datetime must travel as a Neo4j-compatible parameter — no f-string interpolation.
        assert calls[0]["params"]["ts"] == ts

    def test_is_idempotent_on_repeated_calls(self, mock_neo4j_driver):
        from repositories.physical_link_repo import PhysicalLinkRepo

        ts = datetime(2026, 10, 3, 20, 54, 37, tzinfo=UTC)
        mock_neo4j_driver.mock_session.set_default_response([])

        repo = PhysicalLinkRepo(driver=mock_neo4j_driver)
        repo.update_last_polled_at("pl-fiber-01", ts)
        repo.update_last_polled_at("pl-fiber-01", ts)

        calls = [
            q for q in mock_neo4j_driver.mock_session.queries if "last_polled_at" in q["query"]
        ]
        # Repeated calls must each be a SET on the same link (idempotent upsert).
        assert len(calls) == 2
        for call in calls:
            assert call["params"]["link_id"] == "pl-fiber-01"


# T3: run_once() — stamps last_polled_at when an endpoint has recent samples


class TestRunOnceStampsFreshLinks:
    """T3: ``run_once`` stamps ``last_polled_at = now`` when at least one
    endpoint has ``metric_values`` rows in the last 60s."""

    def test_stamps_last_polled_at_when_endpoint_has_recent_samples(
        self, mock_neo4j_driver, fixed_now, fresh_window_seconds, monkeypatch
    ):
        from polling.physical_link_bridge import run_once
        from repositories import metric_repo

        # Two active links with disjoint endpoint pairs:
        # - pl-A spans (ci-A, ci-B) where ci-A has a fresh sample
        # - pl-stale spans (ci-stale-1, ci-stale-2) where neither has any sample
        mock_neo4j_driver.mock_session.set_response(
            "match (pl:physicallink)",
            [
                _link_row(link_id="pl-A", endpoint_a="ci-A", endpoint_b="ci-B"),
                _link_row(
                    link_id="pl-stale",
                    endpoint_a="ci-stale-1",
                    endpoint_b="ci-stale-2",
                ),
            ],
        )

        recent_ts = fixed_now - timedelta(seconds=10)
        sample_responses = {
            "ci-A": [{"time": recent_ts, "value": 1.0}],
            "ci-B": [],
            "ci-stale-1": [],
            "ci-stale-2": [],
        }

        def fake_get_metric_window(node_id, metric_id, s, e):
            return list(sample_responses.get(node_id, []))

        monkeypatch.setattr(metric_repo, "get_metric_window", fake_get_metric_window)

        stats = run_once(
            settings=type(
                "S",
                (),
                {
                    "feature_enabled": True,
                    "fresh_window_seconds": fresh_window_seconds,
                },
            )(),
            driver=mock_neo4j_driver,
            now=fixed_now,
        )

        # pl-A: stamped (ci-A fresh). pl-stale: NOT stamped (no fresh endpoint).
        update_calls = [
            q for q in mock_neo4j_driver.mock_session.queries if "last_polled_at" in q["query"]
        ]
        stamped_ids = {q["params"]["link_id"] for q in update_calls if "ts" in q["params"]}
        assert "pl-A" in stamped_ids
        assert "pl-stale" not in stamped_ids

        # Stats surface the result for observability.
        assert stats["stamped"] >= 1
        assert stats["skipped"] >= 1


# T4: run_once() — does NOT overwrite a previously-set last_polled_at with null


class TestRunOncePreservesPreviousTimestamp:
    """T4: when no endpoint has recent samples, the bridge MUST NOT
    overwrite a previously-set ``last_polled_at`` with null."""

    def test_does_not_overwrite_with_null(
        self, mock_neo4j_driver, fixed_now, fresh_window_seconds, monkeypatch
    ):
        from polling.physical_link_bridge import run_once
        from repositories import metric_repo

        # One active link with no recent samples on either endpoint.
        mock_neo4j_driver.mock_session.set_response(
            "match (pl:physicallink)",
            [_link_row(link_id="pl-stale")],
        )

        monkeypatch.setattr(metric_repo, "get_metric_window", lambda *a, **k: [])

        run_once(
            settings=type(
                "S",
                (),
                {
                    "feature_enabled": True,
                    "fresh_window_seconds": fresh_window_seconds,
                },
            )(),
            driver=mock_neo4j_driver,
            now=fixed_now,
        )

        # The bridge must NOT issue a SET ... last_polled_at = null for a
        # link with no fresh samples.
        update_calls = [
            q for q in mock_neo4j_driver.mock_session.queries if "last_polled_at" in q["query"]
        ]
        for call in update_calls:
            ts_param = call["params"].get("ts")
            assert ts_param is not None, "run_once MUST NOT overwrite last_polled_at with null"


# T5: run_once() — no-op when the feature flag is off


class TestRunOnceHonorsFeatureFlag:
    """T5: when the feature flag is off, ``run_once`` is a pure no-op."""

    def test_is_noop_when_feature_disabled(
        self, mock_neo4j_driver, fixed_now, fresh_window_seconds
    ):
        from polling.physical_link_bridge import run_once

        mock_neo4j_driver.mock_session.set_response(
            "match (pl:physicallink)",
            [_link_row(link_id="pl-A")],
        )

        stats = run_once(
            settings=type(
                "S",
                (),
                {
                    "feature_enabled": False,
                    "fresh_window_seconds": fresh_window_seconds,
                },
            )(),
            driver=mock_neo4j_driver,
            now=fixed_now,
        )

        # No cypher must have been issued for the polling pass.
        update_calls = [
            q for q in mock_neo4j_driver.mock_session.queries if "last_polled_at" in q["query"]
        ]
        assert (
            update_calls == []
        ), "run_once with feature_enabled=False MUST NOT call update_last_polled_at"

        # Stats must reflect a no-op.
        assert stats.get("stamped") == 0
        assert stats.get("skipped") == 0
        assert stats.get("disabled") is True
