"""Empty-case tests for the PhysicalLink utilization read model — feat-439.

T5: when a PhysicalLink has no connected interfaces OR all of its interfaces
have no ``metric_values`` rows in the window, the response is:

    {
      "utilization": null,
      "empty_reason": "no_data",
      "stale": false,
      "last_sample_at": null,
      ...
    }

The empty case is distinct from "0% utilization" — operators must not confuse
"no data" with "the link is idle" (REQ-PHYSLINK-UTIL-2).
"""

from __future__ import annotations

# Mirror the slice-2 test pattern: enable the feature flag so the route is
# reachable. ``setdefault`` keeps the suite hermetic.
import os
from datetime import UTC, datetime, timedelta

import pytest

os.environ.setdefault("FEATURE_CMDB_PHYSICAL_LINKS_ENABLED", "true")


@pytest.fixture
def fixed_now() -> datetime:
    return datetime(2026, 10, 3, 20, 54, 37, tzinfo=UTC)


@pytest.fixture
def window_seconds() -> int:
    return 900


def _link_row(link_id: str = "pl-fiber-01", capacity_gbps: float | None = 10.0) -> dict:
    return {
        "id": link_id,
        "type": "fiber",
        "endpoints": ["ci-A", "ci-B"],
        "status": "UP",
        "capacity_gbps": capacity_gbps,
        "install_date": "2024-01-15",
    }


def _seed(monkeypatch, link_row, per_endpoint_samples):
    """Stub the repo's aggregate + get_by_id, plus metric_repo.get_metric_window."""
    from repositories import metric_repo, physical_link_repo

    # Accepts ``self`` because monkeypatch on a class makes the function a method.
    def fake_get_aggregate(self, link_id, window_seconds, now):
        if link_row is None or link_row.get("id") != link_id:
            return None
        return {
            "physical_link": link_row,
            "endpoints": per_endpoint_samples,
        }

    monkeypatch.setattr(
        physical_link_repo.PhysicalLinkRepo,
        "get_aggregate_counter_samples",
        fake_get_aggregate,
    )
    monkeypatch.setattr(
        physical_link_repo.PhysicalLinkRepo,
        "get_by_id",
        lambda self, link_id: link_row if link_row and link_row.get("id") == link_id else None,
    )
    monkeypatch.setattr(metric_repo, "get_metric_window", lambda *a, **k: [])


# ---------------------------------------------------------------------------
# T5: empty case — distinct from "0% utilization"
# ---------------------------------------------------------------------------


class TestEmptyCase:
    def test_no_endpoints_returns_no_data(self, monkeypatch, fixed_now, window_seconds):
        """PhysicalLink with empty endpoints list → empty_reason="no_data"."""
        from services.physical_link_utilization import (
            PhysicalLinkUtilizationService,
        )

        link_row = _link_row("pl-empty", capacity_gbps=10.0)
        # Repo reports endpoints present but with no samples for any of them.
        empty = {
            "ci-A": {"ifInOctets": [], "ifOutOctets": [], "max_sample_at": None},
            "ci-B": {"ifInOctets": [], "ifOutOctets": [], "max_sample_at": None},
        }
        _seed(monkeypatch, link_row, empty)

        service = PhysicalLinkUtilizationService(stale_after_seconds=1800)
        result = service.compute(
            physical_link_id="pl-empty",
            window_seconds=window_seconds,
            now=fixed_now,
        )
        assert result["stale"] is False
        assert result["empty_reason"] == "no_data"
        assert result["utilization"] is None
        assert result["last_sample_at"] is None

    def test_endpoints_with_no_metric_values_returns_no_data(
        self, monkeypatch, fixed_now, window_seconds
    ):
        """Endpoints exist but no metric_values in the window → no_data."""
        from services.physical_link_utilization import (
            PhysicalLinkUtilizationService,
        )

        link_row = _link_row("pl-no-samples", capacity_gbps=10.0)
        # Only one endpoint has any samples; both timestamps are stale (older
        # than the window) so the aggregate reports max_sample_at=None for
        # both endpoints and empty arrays. This proves the "no metric_values
        # rows" branch.
        empty = {
            "ci-A": {"ifInOctets": [], "ifOutOctets": [], "max_sample_at": None},
            "ci-B": {"ifInOctets": [], "ifOutOctets": [], "max_sample_at": None},
        }
        _seed(monkeypatch, link_row, empty)

        service = PhysicalLinkUtilizationService(stale_after_seconds=1800)
        result = service.compute(
            physical_link_id="pl-no-samples",
            window_seconds=window_seconds,
            now=fixed_now,
        )
        assert result["empty_reason"] == "no_data"
        assert result["utilization"] is None

    def test_empty_case_is_distinct_from_zero_utilization(
        self, monkeypatch, fixed_now, window_seconds
    ):
        """REGRESSION GUARD (REQ-PHYSLINK-UTIL-2):
        "no data" must NOT be reported as 0% utilization.

        If all counters in the window are zero, the response is still the
        happy path with utilization=0.0 and empty_reason=null. The empty
        case fires only when there are no samples at all.
        """
        from services.physical_link_utilization import (
            PhysicalLinkUtilizationService,
        )

        link_row = _link_row("pl-zero", capacity_gbps=10.0)
        t0 = fixed_now - timedelta(seconds=window_seconds)
        # All counters are zero across the window → happy path, 0% utilization.
        per_endpoint = {
            "ci-A": {
                "ifInOctets": [
                    {"time": t0, "value": 0.0},
                    {"time": fixed_now, "value": 0.0},
                ],
                "ifOutOctets": [
                    {"time": t0, "value": 0.0},
                    {"time": fixed_now, "value": 0.0},
                ],
                "max_sample_at": fixed_now,
            },
            "ci-B": {
                "ifInOctets": [
                    {"time": t0, "value": 0.0},
                    {"time": fixed_now, "value": 0.0},
                ],
                "ifOutOctets": [
                    {"time": t0, "value": 0.0},
                    {"time": fixed_now, "value": 0.0},
                ],
                "max_sample_at": fixed_now,
            },
        }
        _seed(monkeypatch, link_row, per_endpoint)

        service = PhysicalLinkUtilizationService(stale_after_seconds=1800)
        result = service.compute(
            physical_link_id="pl-zero",
            window_seconds=window_seconds,
            now=fixed_now,
        )
        # NOT the empty case — zero traffic is a real (and answerable) state.
        assert result["empty_reason"] is None
        assert result["utilization"] is not None
        assert result["utilization"]["utilization_percent"] == 0.0
        assert result["utilization"]["saturated"] is False

    def test_empty_response_uses_strict_iso_z_format(self, monkeypatch, fixed_now, window_seconds):
        """Wire shape: ISO 8601 with explicit ``Z`` suffix for UTC."""
        from services.physical_link_utilization import (
            PhysicalLinkUtilizationService,
        )

        link_row = _link_row("pl-iso", capacity_gbps=10.0)
        empty = {
            "ci-A": {"ifInOctets": [], "ifOutOctets": [], "max_sample_at": None},
            "ci-B": {"ifInOctets": [], "ifOutOctets": [], "max_sample_at": None},
        }
        _seed(monkeypatch, link_row, empty)

        service = PhysicalLinkUtilizationService(stale_after_seconds=1800)
        result = service.compute(
            physical_link_id="pl-iso",
            window_seconds=window_seconds,
            now=fixed_now,
        )
        # computed_at is non-null and ends with 'Z' (UTC wire format).
        assert result["computed_at"].endswith("Z")
        assert result["last_sample_at"] is None
