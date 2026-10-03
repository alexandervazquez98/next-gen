"""Tests for the PhysicalLink utilization read model — feat-439 (#439 slice 3/4).

Slice 3/4 of the fiber-optic / physical-link visualization chain. The endpoint
exposes per-link counter-delta utilization with three distinct empty cases:
- ``empty_reason="no_data"`` — no samples in window
- ``empty_reason="stale_samples"`` — last sample older than threshold
- ``empty_reason="no_capacity"`` — capacity_gbps not set on the link

Aggregation semantics (locked in the ODD doc):
- ``delta = last(counter) - first(counter)`` within window (RFC 1213 counter semantics).
- endpoint bps = ``(delta_in + delta_out) / window_seconds * 8``
- link utilization = ``max(endpoint_a_bps, endpoint_b_bps) / capacity_bps`` clipped to [0, 1]
- ``saturated = max_bps > capacity_bps``

TDD task coverage:
- T1: happy path rollup with max-bottleneck semantic
- T2: WindowDuration parser
- T3: get_metric_window (mocked at the metric_repo function level)
- T4: get_aggregate_counter_samples joins endpoints + per-endpoint ifInOctets / ifOutOctets
- T6: stale case (> stale_after_seconds)
- T7: no-capacity case
- T8: router end-to-end via TestClient (happy + invalid window + 404)

T5 (empty case) lives in ``test_physical_link_utilization_no_data.py`` to keep
the happy-path suite focused.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

# Enable the slice-2 router + the slice-3 router (both gated on the same env
# flag). Mirrors the slice-2 test pattern: setdefault keeps the suite
# hermetic when the operator toggles the env at deploy time.
os.environ.setdefault("FEATURE_CMDB_PHYSICAL_LINKS_ENABLED", "true")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fixed_now() -> datetime:
    """A deterministic now() for time control — injected via _now lambdas."""
    return datetime(2026, 10, 3, 20, 54, 37, tzinfo=UTC)


@pytest.fixture
def window_seconds() -> int:
    return 900  # 15 minutes, the locked default


def _iso_z(dt: datetime) -> str:
    """Format a datetime as the wire shape uses: ``...Z`` suffix."""
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# T2: WindowDuration parser (no I/O — pure logic)
# ---------------------------------------------------------------------------


class TestWindowDurationParser:
    """T2: ``WindowDuration.parse`` accepts '15m' / '1h' / '6h' / '24h' and rejects garbage."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("15m", 900),
            ("30m", 1800),
            ("1h", 3600),
            ("6h", 21600),
            ("24h", 86400),
        ],
    )
    def test_parse_accepts_documented_durations(self, raw, expected):
        from schemas.physical_link_utilization import WindowDuration

        assert WindowDuration.parse(raw) == expected

    def test_parse_rejects_unknown_unit(self):
        from schemas.physical_link_utilization import WindowDuration

        with pytest.raises(ValueError):
            WindowDuration.parse("invalid")

    def test_parse_rejects_zero_minutes(self):
        from schemas.physical_link_utilization import WindowDuration

        with pytest.raises(ValueError):
            WindowDuration.parse("0m")

    def test_parse_rejects_empty_string(self):
        from schemas.physical_link_utilization import WindowDuration

        with pytest.raises(ValueError):
            WindowDuration.parse("")

    def test_parse_rejects_unit_without_number(self):
        from schemas.physical_link_utilization import WindowDuration

        with pytest.raises(ValueError):
            WindowDuration.parse("h")

    def test_to_string_inverts_parse(self):
        from schemas.physical_link_utilization import WindowDuration

        # Canonical round-trip: parse(to_string(x)) == x
        for seconds in (900, 1800, 3600, 21600, 86400):
            assert WindowDuration.parse(WindowDuration.to_string(seconds)) == seconds

    def test_to_string_uses_canonical_durations(self):
        from schemas.physical_link_utilization import WindowDuration

        assert WindowDuration.to_string(900) == "15m"
        assert WindowDuration.to_string(1800) == "30m"
        assert WindowDuration.to_string(3600) == "1h"
        assert WindowDuration.to_string(21600) == "6h"
        assert WindowDuration.to_string(86400) == "24h"

    def test_to_string_rejects_unknown_seconds(self):
        from schemas.physical_link_utilization import WindowDuration

        with pytest.raises(ValueError):
            WindowDuration.to_string(123)


# ---------------------------------------------------------------------------
# T3: get_metric_window (mocked at the metric_repo function level)
# ---------------------------------------------------------------------------


class TestGetMetricWindow:
    """T3: ``metric_repo.get_metric_window`` returns samples in [start, end] ordered ASC."""

    def test_returns_samples_in_range_ordered_ascending(self, monkeypatch):
        from repositories import metric_repo

        t0 = datetime(2026, 10, 3, 20, 0, 0, tzinfo=UTC)
        t1 = t0 + timedelta(seconds=300)
        t2 = t0 + timedelta(seconds=600)
        rows = [
            {"time": t0, "value": 100.0},
            {"time": t1, "value": 200.0},
            {"time": t2, "value": 300.0},
        ]
        monkeypatch.setattr(metric_repo, "get_metric_window", lambda *a, **k: list(rows))

        result = metric_repo.get_metric_window("ci-A", "ifInOctets", t0, t2 + timedelta(seconds=60))
        assert result == rows

    def test_excludes_samples_outside_range(self, monkeypatch):
        from repositories import metric_repo

        start = datetime(2026, 10, 3, 20, 0, 0, tzinfo=UTC)
        end = start + timedelta(seconds=900)
        in_window = [
            {"time": start + timedelta(seconds=100), "value": 1.0},
            {"time": start + timedelta(seconds=800), "value": 2.0},
        ]
        # Capture filter args and pre-filter the response to simulate SQL WHERE.
        captured = {}

        def fake(node_id, metric_id, s, e):
            captured["node_id"] = node_id
            captured["metric_id"] = metric_id
            captured["start"] = s
            captured["end"] = e
            return [r for r in in_window if s <= r["time"] <= e]

        monkeypatch.setattr(metric_repo, "get_metric_window", fake)
        result = metric_repo.get_metric_window("ci-A", "ifInOctets", start, end)
        assert result == in_window
        assert captured["start"] == start
        assert captured["end"] == end

    def test_ordered_oldest_first(self, monkeypatch):
        from repositories import metric_repo

        start = datetime(2026, 10, 3, 20, 0, 0, tzinfo=UTC)
        rows_asc = [
            {"time": start + timedelta(seconds=i * 60), "value": float(i)} for i in range(5)
        ]
        # Repo contract: function must guarantee ASC by time. The test verifies
        # the consumer (service layer) trusts this contract by passing the
        # rows through unchanged — first/last selection is positional.
        monkeypatch.setattr(metric_repo, "get_metric_window", lambda *a, **k: list(rows_asc))
        result = metric_repo.get_metric_window(
            "ci-A", "ifInOctets", start, start + timedelta(seconds=600)
        )
        assert [r["value"] for r in result] == [0.0, 1.0, 2.0, 3.0, 4.0]


# ---------------------------------------------------------------------------
# T4: get_aggregate_counter_samples (joins PhysicalLink endpoints + metric_values)
# ---------------------------------------------------------------------------


def _make_neo4j_link_row(
    link_id: str = "pl-fiber-01",
    endpoint_a: str = "ci-A",
    endpoint_b: str = "ci-B",
    capacity_gbps: float | None = 10.0,
) -> dict:
    return {
        "id": link_id,
        "type": "fiber",
        "endpoints": [endpoint_a, endpoint_b],
        "status": "UP",
        "capacity_gbps": capacity_gbps,
        "install_date": "2024-01-15",
    }


class TestGetAggregateCounterSamples:
    """T4: joins endpoints with metric_values for ifInOctets + ifOutOctets."""

    def test_returns_per_endpoint_first_last_and_max_timestamp(
        self, mock_neo4j_driver, monkeypatch, fixed_now, window_seconds
    ):
        from repositories import metric_repo, physical_link_repo

        mock_neo4j_driver.mock_session.set_response(
            "match (pl:physicallink)",
            [_make_neo4j_link_row()],
        )

        t0 = fixed_now - timedelta(seconds=window_seconds)
        # ci-A: 3 in samples, 3 out samples — both increasing
        in_a = [
            {"time": t0 + timedelta(seconds=0), "value": 1.0e9},
            {"time": t0 + timedelta(seconds=450), "value": 2.0e9},
            {"time": t0 + timedelta(seconds=890), "value": 3.0e9},
        ]
        out_a = [
            {"time": t0 + timedelta(seconds=0), "value": 0.0},
            {"time": t0 + timedelta(seconds=890), "value": 1.0e9},
        ]
        in_b = [
            {"time": t0 + timedelta(seconds=0), "value": 5.0e9},
            {"time": t0 + timedelta(seconds=890), "value": 5.5e9},
        ]
        out_b = [
            {"time": t0 + timedelta(seconds=0), "value": 0.0},
            {"time": t0 + timedelta(seconds=890), "value": 0.0},
        ]

        def fake_get_metric_window(node_id, metric_id, s, e):
            if node_id == "ci-A" and metric_id == "ifInOctets":
                return list(in_a)
            if node_id == "ci-A" and metric_id == "ifOutOctets":
                return list(out_a)
            if node_id == "ci-B" and metric_id == "ifInOctets":
                return list(in_b)
            if node_id == "ci-B" and metric_id == "ifOutOctets":
                return list(out_b)
            return []

        monkeypatch.setattr(metric_repo, "get_metric_window", fake_get_metric_window)

        repo = physical_link_repo.PhysicalLinkRepo(driver=mock_neo4j_driver)
        result = repo.get_aggregate_counter_samples(
            "pl-fiber-01", window_seconds=window_seconds, now=fixed_now
        )

        # Top-level shape
        assert result["physical_link"]["id"] == "pl-fiber-01"
        assert set(result["endpoints"].keys()) == {"ci-A", "ci-B"}

        a = result["endpoints"]["ci-A"]
        assert a["ifInOctets"] == in_a
        assert a["ifOutOctets"] == out_a
        # max_sample_at is the newest timestamp across both metrics
        assert a["max_sample_at"] == in_a[-1]["time"]

        b = result["endpoints"]["ci-B"]
        assert b["ifInOctets"] == in_b
        assert b["ifOutOctets"] == out_b
        assert b["max_sample_at"] == in_b[-1]["time"]

    def test_returns_empty_endpoint_dict_when_no_samples(
        self, mock_neo4j_driver, monkeypatch, fixed_now, window_seconds
    ):
        from repositories import metric_repo, physical_link_repo

        mock_neo4j_driver.mock_session.set_response(
            "match (pl:physicallink)",
            [_make_neo4j_link_row()],
        )
        monkeypatch.setattr(metric_repo, "get_metric_window", lambda *a, **k: [])

        repo = physical_link_repo.PhysicalLinkRepo(driver=mock_neo4j_driver)
        result = repo.get_aggregate_counter_samples(
            "pl-fiber-01", window_seconds=window_seconds, now=fixed_now
        )

        # Both endpoints present, both with empty arrays + None max_sample_at
        for ci_id in ("ci-A", "ci-B"):
            ep = result["endpoints"][ci_id]
            assert ep["ifInOctets"] == []
            assert ep["ifOutOctets"] == []
            assert ep["max_sample_at"] is None

    def test_returns_none_when_physical_link_missing(
        self, mock_neo4j_driver, monkeypatch, fixed_now, window_seconds
    ):
        from repositories import metric_repo, physical_link_repo

        mock_neo4j_driver.mock_session.set_default_response([])
        monkeypatch.setattr(metric_repo, "get_metric_window", lambda *a, **k: [])

        repo = physical_link_repo.PhysicalLinkRepo(driver=mock_neo4j_driver)
        result = repo.get_aggregate_counter_samples(
            "missing-link", window_seconds=window_seconds, now=fixed_now
        )
        assert result is None


# ---------------------------------------------------------------------------
# T1: compute_physical_link_utilization — happy path
# ---------------------------------------------------------------------------


def _seed_service_repo(monkeypatch, link_row, per_endpoint_samples, fixed_now, window_seconds):
    """Wire a PhysicalLinkUtilizationService against a stubbed repo + metric_repo."""
    from repositories import metric_repo, physical_link_repo

    # Stub get_aggregate_counter_samples on the repo CLASS so the service picks it up.
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
    # Belt-and-suspenders: also stub get_by_id so any direct path stays safe.
    monkeypatch.setattr(
        physical_link_repo.PhysicalLinkRepo,
        "get_by_id",
        lambda self, link_id: link_row if link_row and link_row.get("id") == link_id else None,
    )
    monkeypatch.setattr(metric_repo, "get_metric_window", lambda *a, **k: [])


class TestComputePhysicalLinkUtilizationHappyPath:
    """T1: max-bottleneck semantic, full-duplex counter deltas."""

    def test_max_bottleneck_full_duplex_with_50pct_in_one_direction(
        self, monkeypatch, fixed_now, window_seconds
    ):
        """Spec-locked scenario: 15-min window, 10 Gbps capacity, ~50% in one direction.

        ci-A: ifInOctets grows 0 -> 562_500_000_000 (~50% of 10Gbps in 15 min).
        ci-A: ifOutOctets stays 0.
        ci-B: ifInOctets stays 0.
        ci-B: ifOutOctets grows 0 -> 562_500_000_000.

        Expected:
        - max_endpoint_bps = 5_000_000_000
        - utilization_percent = 0.5
        - saturated = False
        """
        from services.physical_link_utilization import (
            PhysicalLinkUtilizationService,
        )

        link_row = _make_neo4j_link_row(link_id="pl-fiber-01", capacity_gbps=10.0)
        t0 = fixed_now - timedelta(seconds=window_seconds)

        def _series(start, end):
            return [
                {"time": t0, "value": float(start)},
                {"time": t0 + timedelta(seconds=window_seconds), "value": float(end)},
            ]

        per_endpoint = {
            "ci-A": {
                "ifInOctets": _series(0, 562_500_000_000),
                "ifOutOctets": _series(0, 0),
                "max_sample_at": t0 + timedelta(seconds=window_seconds),
            },
            "ci-B": {
                "ifInOctets": _series(0, 0),
                "ifOutOctets": _series(0, 562_500_000_000),
                "max_sample_at": t0 + timedelta(seconds=window_seconds),
            },
        }
        _seed_service_repo(monkeypatch, link_row, per_endpoint, fixed_now, window_seconds)

        service = PhysicalLinkUtilizationService(stale_after_seconds=1800)
        result = service.compute(
            physical_link_id="pl-fiber-01",
            window_seconds=window_seconds,
            now=fixed_now,
        )

        # Wire shape
        assert result["physical_link_id"] == "pl-fiber-01"
        assert result["window_seconds"] == window_seconds
        assert result["stale"] is False
        assert result["empty_reason"] is None
        assert result["last_sample_at"] is not None
        # Utilization math
        u = result["utilization"]
        assert u is not None
        assert u["capacity_bps"] == 10_000_000_000
        assert u["max_endpoint_bps"] == 5_000_000_000
        assert u["utilization_percent"] == 0.5
        assert u["saturated"] is False

    def test_saturated_flag_when_above_capacity(self, monkeypatch, fixed_now, window_seconds):
        """When max_endpoint_bps > capacity_bps: utilization clipped to 1.0, saturated=true."""
        from services.physical_link_utilization import (
            PhysicalLinkUtilizationService,
        )

        link_row = _make_neo4j_link_row(link_id="pl-overdrive", capacity_gbps=1.0)
        t0 = fixed_now - timedelta(seconds=window_seconds)
        # 1 Gbps cap → 1.125e11 bytes/sec * 900s = 1.0125e14 bytes (over 2x the cap)
        over_byte_delta = 1_012_500_000_000

        def _series(value):
            return [
                {"time": t0, "value": 0.0},
                {"time": t0 + timedelta(seconds=window_seconds), "value": float(value)},
            ]

        per_endpoint = {
            "ci-A": {
                "ifInOctets": _series(over_byte_delta),
                "ifOutOctets": _series(0),
                "max_sample_at": t0 + timedelta(seconds=window_seconds),
            },
            "ci-B": {
                "ifInOctets": _series(0),
                "ifOutOctets": _series(0),
                "max_sample_at": t0 + timedelta(seconds=window_seconds),
            },
        }
        _seed_service_repo(monkeypatch, link_row, per_endpoint, fixed_now, window_seconds)

        service = PhysicalLinkUtilizationService(stale_after_seconds=1800)
        result = service.compute(
            physical_link_id="pl-overdrive",
            window_seconds=window_seconds,
            now=fixed_now,
        )
        u = result["utilization"]
        assert u["utilization_percent"] == 1.0
        assert u["saturated"] is True
        assert u["max_endpoint_bps"] > u["capacity_bps"]

    def test_compute_returns_dict_for_missing_physical_link(
        self, monkeypatch, fixed_now, window_seconds
    ):
        """Unknown id → returns None (router maps to 404)."""
        from services.physical_link_utilization import (
            PhysicalLinkUtilizationService,
        )

        _seed_service_repo(monkeypatch, None, {}, fixed_now, window_seconds)
        service = PhysicalLinkUtilizationService(stale_after_seconds=1800)
        assert (
            service.compute(
                physical_link_id="missing", window_seconds=window_seconds, now=fixed_now
            )
            is None
        )


# ---------------------------------------------------------------------------
# T6: stale case — last sample older than threshold
# ---------------------------------------------------------------------------


class TestComputePhysicalLinkUtilizationStale:
    """T6: when max(last_sample_at) is older than stale_after_seconds, the response is stale."""

    def test_stale_when_last_sample_older_than_threshold(
        self, monkeypatch, fixed_now, window_seconds
    ):
        from services.physical_link_utilization import (
            PhysicalLinkUtilizationService,
        )

        link_row = _make_neo4j_link_row(link_id="pl-stale", capacity_gbps=10.0)
        # Last sample is 60 minutes ago (3600s). Threshold is 1800s.
        last_sample = fixed_now - timedelta(seconds=3600)
        per_endpoint = {
            "ci-A": {
                "ifInOctets": [
                    {"time": fixed_now - timedelta(seconds=4500), "value": 0.0},
                    {"time": last_sample, "value": 1.0e9},
                ],
                "ifOutOctets": [],
                "max_sample_at": last_sample,
            },
            "ci-B": {
                "ifInOctets": [],
                "ifOutOctets": [],
                "max_sample_at": None,
            },
        }
        _seed_service_repo(monkeypatch, link_row, per_endpoint, fixed_now, window_seconds)

        service = PhysicalLinkUtilizationService(stale_after_seconds=1800)
        result = service.compute(
            physical_link_id="pl-stale", window_seconds=window_seconds, now=fixed_now
        )
        assert result["stale"] is True
        assert result["empty_reason"] == "stale_samples"
        assert result["utilization"] is None
        # last_sample_at MUST be set (we still expose what we have, so the
        # operator sees "the data we would have used").
        assert result["last_sample_at"] is not None

    def test_fresh_when_last_sample_within_threshold(self, monkeypatch, fixed_now, window_seconds):
        from services.physical_link_utilization import (
            PhysicalLinkUtilizationService,
        )

        link_row = _make_neo4j_link_row(link_id="pl-fresh", capacity_gbps=10.0)
        t0 = fixed_now - timedelta(seconds=window_seconds)
        last_sample = fixed_now - timedelta(seconds=10)  # 10s old, well within 1800s
        per_endpoint = {
            "ci-A": {
                "ifInOctets": [
                    {"time": t0, "value": 0.0},
                    {"time": last_sample, "value": 1.0e9},
                ],
                "ifOutOctets": [
                    {"time": t0, "value": 0.0},
                    {"time": last_sample, "value": 0.0},
                ],
                "max_sample_at": last_sample,
            },
            "ci-B": {
                "ifInOctets": [
                    {"time": t0, "value": 0.0},
                    {"time": last_sample, "value": 0.0},
                ],
                "ifOutOctets": [
                    {"time": t0, "value": 0.0},
                    {"time": last_sample, "value": 0.0},
                ],
                "max_sample_at": last_sample,
            },
        }
        _seed_service_repo(monkeypatch, link_row, per_endpoint, fixed_now, window_seconds)

        service = PhysicalLinkUtilizationService(stale_after_seconds=1800)
        result = service.compute(
            physical_link_id="pl-fresh", window_seconds=window_seconds, now=fixed_now
        )
        assert result["stale"] is False
        assert result["empty_reason"] is None
        assert result["utilization"] is not None


# ---------------------------------------------------------------------------
# T7: no-capacity case — capacity_gbps is null
# ---------------------------------------------------------------------------


class TestComputePhysicalLinkUtilizationNoCapacity:
    """T7: PhysicalLink.capacity_gbps=null → empty_reason="no_capacity", utilization=null."""

    def test_no_capacity_returns_no_capacity_reason(self, monkeypatch, fixed_now, window_seconds):
        from services.physical_link_utilization import (
            PhysicalLinkUtilizationService,
        )

        link_row = _make_neo4j_link_row(link_id="pl-planned", capacity_gbps=None)
        t0 = fixed_now - timedelta(seconds=window_seconds)
        per_endpoint = {
            "ci-A": {
                "ifInOctets": [
                    {"time": t0, "value": 0.0},
                    {"time": fixed_now, "value": 1.0e9},
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
        _seed_service_repo(monkeypatch, link_row, per_endpoint, fixed_now, window_seconds)

        service = PhysicalLinkUtilizationService(stale_after_seconds=1800)
        result = service.compute(
            physical_link_id="pl-planned", window_seconds=window_seconds, now=fixed_now
        )
        assert result["stale"] is False
        assert result["empty_reason"] == "no_capacity"
        assert result["utilization"] is None


# ---------------------------------------------------------------------------
# T8: router end-to-end (TestClient)
# ---------------------------------------------------------------------------


class TestRouterEndToEnd:
    """T8: GET /api/cmdb/physical-links/{id}/utilization — happy / 422 / 404 / 200."""

    def test_happy_path_returns_200_and_wire_shape(self, monkeypatch, fixed_now):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routers import physical_link_utilization as pl_util_router
        from services import physical_link_utilization as svc

        # Stub the service to avoid hitting the repo layer (covered separately).
        # Accepts ``self`` because the stub is set on the class. ``now`` is
        # optional because the router calls ``compute(physical_link_id=...,
        # window_seconds=...)`` without it (the service defaults to now()).
        def fake_compute(self, physical_link_id, window_seconds, now=None):
            return {
                "physical_link_id": physical_link_id,
                "window_seconds": window_seconds,
                "computed_at": "2026-10-03T20:54:37Z",
                "stale": False,
                "empty_reason": None,
                "last_sample_at": "2026-10-03T20:53:00Z",
                "utilization": {
                    "endpoint_a": {
                        "in_bytes_delta": 100,
                        "out_bytes_delta": 0,
                        "in_bps": 1,
                        "out_bps": 0,
                    },
                    "endpoint_b": {
                        "in_bytes_delta": 0,
                        "out_bytes_delta": 0,
                        "in_bps": 0,
                        "out_bps": 0,
                    },
                    "max_endpoint_bps": 1,
                    "capacity_bps": 10_000_000_000,
                    "utilization_percent": 0.0000001,
                    "saturated": False,
                },
            }

        monkeypatch.setattr(
            svc.PhysicalLinkUtilizationService,
            "compute",
            fake_compute,
        )

        app = FastAPI()
        app.include_router(pl_util_router.router, prefix="/api")
        client = TestClient(app)

        resp = client.get("/api/cmdb/physical-links/pl-fiber-01/utilization?window=15m")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["physical_link_id"] == "pl-fiber-01"
        assert data["window_seconds"] == 900
        assert data["stale"] is False
        assert data["utilization"]["capacity_bps"] == 10_000_000_000

    def test_invalid_window_returns_422(self, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routers import physical_link_utilization as pl_util_router

        app = FastAPI()
        app.include_router(pl_util_router.router, prefix="/api")
        client = TestClient(app)

        resp = client.get("/api/cmdb/physical-links/pl-fiber-01/utilization?window=invalid")
        assert resp.status_code == 422

    def test_unknown_physical_link_returns_404(self, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routers import physical_link_utilization as pl_util_router
        from services import physical_link_utilization as svc

        # Unknown id → service.compute returns None → router maps to 404.
        monkeypatch.setattr(
            svc.PhysicalLinkUtilizationService,
            "compute",
            lambda self, physical_link_id, window_seconds, now=None: None,
        )
        app = FastAPI()
        app.include_router(pl_util_router.router, prefix="/api")
        client = TestClient(app)

        resp = client.get("/api/cmdb/physical-links/missing/utilization?window=15m")
        assert resp.status_code == 404
        assert resp.json()["detail"]["reason"] == "physical_link_not_found"

    def test_default_window_is_15m(self, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routers import physical_link_utilization as pl_util_router
        from services import physical_link_utilization as svc

        captured_kwargs = {}

        def fake_compute(self, physical_link_id, window_seconds, now=None):
            captured_kwargs["window_seconds"] = window_seconds
            return {
                "physical_link_id": physical_link_id,
                "window_seconds": window_seconds,
                "computed_at": "2026-10-03T20:54:37Z",
                "stale": False,
                "empty_reason": None,
                "last_sample_at": None,
                "utilization": None,
            }

        monkeypatch.setattr(svc.PhysicalLinkUtilizationService, "compute", fake_compute)
        app = FastAPI()
        app.include_router(pl_util_router.router, prefix="/api")
        client = TestClient(app)

        resp = client.get("/api/cmdb/physical-links/pl-fiber-01/utilization")
        assert resp.status_code == 200
        assert captured_kwargs["window_seconds"] == 900  # 15m default

    def test_feature_flag_off_returns_404(self, monkeypatch):
        """When FEATURE_CMDB_PHYSICAL_LINKS_ENABLED=false, the endpoint MUST 404."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routers import physical_link_utilization as pl_util_router

        monkeypatch.setenv("FEATURE_CMDB_PHYSICAL_LINKS_ENABLED", "false")
        app = FastAPI()
        app.include_router(pl_util_router.router, prefix="/api")
        client = TestClient(app)

        resp = client.get("/api/cmdb/physical-links/pl-fiber-01/utilization?window=15m")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "feature_disabled"
