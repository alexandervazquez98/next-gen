"""REQ-CORR-2: Path C (leased polling) correlation round-trip tests.

Path C is the leased polling producer (`backend/polling/snmp_worker.py`). It
must pre-tag every result envelope with `correlation_type`, `propagated_from`,
and `root_cause_ci_id` BEFORE the envelope is enqueued onto
`poll_result_queue`. The downstream `backend/polling/event_writer.py` then
preserves those fields through `build_event_rows` and persists them in Neo4j.

This file proves the round-trip contract:

1. **Producer pre-tags the envelope** (RED in PR 2): `run_leased_snmp_worker_once`
   calls `resolve_correlation_fields` and stamps the resulting fields into the
   envelope metadata before `result_to_queue_row` is called.
2. **Writer preserves pre-tagged PROPAGATED fields** (regression): a PROPAGATED
   envelope survives `build_event_rows` round-trip.
3. **Writer preserves pre-tagged ROOT fields** (regression): a ROOT envelope
   survives the round-trip with `propagated_from=None`.
4. **Writer backwards compat**: an envelope without `correlation_type` metadata
   falls back to the writer's default (`ROOT`).

Existing test coverage in `test_polling_event_writer.py` already covers the
PROPAGATED round-trip; these tests pin the ROOT and missing-type variants
explicitly (so future refactors of `build_event_rows` cannot regress either).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

# Ensure backend root is on the import path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_envelope(
    ci_id: str = "ci-B",
    metric_id: str = "cpu",
    *,
    correlation_metadata: dict | None = None,
):
    """Build a minimal PollResultEnvelope with optional correlation metadata.

    When `correlation_metadata` is None, the envelope has NO correlation fields
    (the producer-side default). Otherwise the metadata dict is merged in.
    """
    from polling.contracts import PollResultEnvelope, PollingProtocol, PollingResultStatus

    metadata = {"name": metric_id, "criticality": 3}
    if correlation_metadata:
        metadata.update(correlation_metadata)
    return PollResultEnvelope(
        result_id=uuid4(),
        task_id=uuid4(),
        cycle_id=uuid4(),
        idempotency_key="idem-1",
        ci_id=ci_id,
        metric_id=metric_id,
        protocol=PollingProtocol.SNMP,
        source="10.0.0.1:161",
        observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        received_at=datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
        status=PollingResultStatus.CRITICAL,
        worker_id="snmp-worker",
        value={"numeric": 95.0, "text": None, "raw": 95.0},
        error={"code": None, "message": None, "retryable": False},
        metadata=metadata,
        timing={
            "started_at": "2026-01-01T00:00:00+00:00",
            "finished_at": "2026-01-01T00:00:01+00:00",
            "duration_ms": 100.0,
        },
    )


def _make_settings():
    settings = MagicMock()
    settings.snmp_leased_worker_enabled = True
    settings.task_batch_size = 100
    settings.lease_ttl_seconds = 120
    return settings


def _make_claimed_task(ci_id: str = "ci-B"):
    return {
        "task_id": uuid4(),
        "cycle_id": uuid4(),
        "ci_id": ci_id,
        "metric_id": "cpu",
        "protocol": "SNMP",
        "priority": 50,
        "source": "10.0.0.1:161",
        "partition_key": 0,
        "payload": {},
        "site_id": None,
        "subnet": None,
        "ip_address": "10.0.0.1",
        "credential_ref": None,
        "endpoint": None,
        "metadata_version": 1,
    }


# ---------------------------------------------------------------------------
# Scenario A: Producer pre-tags the envelope (REQ-CORR-2 — RED in PR 2)
# ---------------------------------------------------------------------------


class TestPathCProducerPreTagging:
    """Path C leased worker must call resolve_correlation_fields and stamp the
    resulting correlation fields into the envelope metadata BEFORE the envelope
    is enqueued onto the queue.

    Without this pre-tagging, the writer would default every event to ROOT and
    break cascade-deduplication for leased polling. PR 2 implements the wire-in.
    """

    def test_producer_pre_tags_envelope_with_propagated_correlation(self):
        """A CRITICAL envelope from a dependent CI gets pre-tagged as PROPAGATED
        with propagated_from and root_cause_ci_id from the resolver."""
        from polling.snmp_worker import run_leased_snmp_worker_once

        ci_id = "ci-B"
        envelope = _make_envelope(ci_id=ci_id)
        correlation_fields = {
            "correlation_type": "PROPAGATED",
            "propagated_from": "evt-A-root",
            "root_cause_ci_id": "ci-A",
        }
        settings = _make_settings()
        safety_limiter = MagicMock()
        safety_limiter.acquire.return_value = MagicMock(
            allowed=True, error_code=None, reason=None
        )
        safety_limiter.release.return_value = None
        claimed = _make_claimed_task(ci_id=ci_id)
        db = MagicMock()

        with patch("polling.snmp_worker.pg_queue.claim_tasks", return_value=[claimed]), \
             patch("polling.snmp_worker.pg_queue.enqueue_results") as mock_enqueue, \
             patch("polling.snmp_worker.pg_queue.complete_task") as mock_complete, \
             patch("polling.snmp_worker.pg_queue.retry_task"), \
             patch("polling.snmp_worker.execute_poll_task", return_value=envelope), \
             patch(
                 "services.event_service.resolve_correlation_fields",
                 return_value=correlation_fields,
             ) as mock_resolve:
            stats = run_leased_snmp_worker_once(
                db,
                settings=settings,
                worker_id="snmp-worker",
                safety_limiter=safety_limiter,
            )

        # 1. Producer must call resolve_correlation_fields for this ci_id.
        assert mock_resolve.called, (
            "Path C producer must call resolve_correlation_fields to tag "
            "envelopes with correlation fields before enqueue."
        )
        # First positional arg is ci_id.
        called_ci_id = mock_resolve.call_args[0][0]
        assert called_ci_id == ci_id, (
            f"resolve_correlation_fields must be called with ci_id={ci_id!r}, "
            f"got {called_ci_id!r}"
        )

        # 2. The enqueued row's envelope metadata must include the correlation
        #    fields returned by the resolver.
        assert mock_enqueue.called, "enqueue_results must be called"
        enqueued_rows = mock_enqueue.call_args[0][1]
        assert len(enqueued_rows) == 1, (
            f"expected exactly one enqueued row, got {len(enqueued_rows)}"
        )
        enqueued_metadata = enqueued_rows[0]["envelope"]["metadata"]
        assert enqueued_metadata["correlation_type"] == "PROPAGATED", (
            f"envelope metadata must carry correlation_type='PROPAGATED', "
            f"got {enqueued_metadata.get('correlation_type')!r}. "
            f"Path C producer is not pre-tagging (T7 not implemented)."
        )
        assert enqueued_metadata["propagated_from"] == "evt-A-root", (
            f"envelope metadata must carry propagated_from='evt-A-root', "
            f"got {enqueued_metadata.get('propagated_from')!r}"
        )
        assert enqueued_metadata["root_cause_ci_id"] == "ci-A", (
            f"envelope metadata must carry root_cause_ci_id='ci-A', "
            f"got {enqueued_metadata.get('root_cause_ci_id')!r}"
        )

    def test_producer_pre_tags_envelope_with_root_correlation(self):
        """An envelope from a CI with no open parent gets pre-tagged as ROOT."""
        from polling.snmp_worker import run_leased_snmp_worker_once

        ci_id = "ci-A"
        envelope = _make_envelope(ci_id=ci_id)
        root_fields = {
            "correlation_type": "ROOT",
            "propagated_from": None,
            "root_cause_ci_id": "ci-A",
        }
        settings = _make_settings()
        safety_limiter = MagicMock()
        safety_limiter.acquire.return_value = MagicMock(
            allowed=True, error_code=None, reason=None
        )
        safety_limiter.release.return_value = None
        claimed = _make_claimed_task(ci_id=ci_id)
        db = MagicMock()

        with patch("polling.snmp_worker.pg_queue.claim_tasks", return_value=[claimed]), \
             patch("polling.snmp_worker.pg_queue.enqueue_results") as mock_enqueue, \
             patch("polling.snmp_worker.pg_queue.complete_task"), \
             patch("polling.snmp_worker.pg_queue.retry_task"), \
             patch("polling.snmp_worker.execute_poll_task", return_value=envelope), \
             patch(
                 "services.event_service.resolve_correlation_fields",
                 return_value=root_fields,
             ):
            run_leased_snmp_worker_once(
                db,
                settings=settings,
                worker_id="snmp-worker",
                safety_limiter=safety_limiter,
            )

        enqueued_rows = mock_enqueue.call_args[0][1]
        enqueued_metadata = enqueued_rows[0]["envelope"]["metadata"]
        assert enqueued_metadata["correlation_type"] == "ROOT", (
            f"expected correlation_type='ROOT', got "
            f"{enqueued_metadata.get('correlation_type')!r}"
        )
        assert enqueued_metadata["propagated_from"] is None, (
            f"expected propagated_from=None for ROOT, got "
            f"{enqueued_metadata.get('propagated_from')!r}"
        )
        assert enqueued_metadata["root_cause_ci_id"] == "ci-A"


# ---------------------------------------------------------------------------
# Scenario B: Writer round-trip preserves pre-tagged metadata
# ---------------------------------------------------------------------------


class TestPathCWriterRoundTrip:
    """The writer (event_writer.build_event_rows) must preserve pre-tagged
    correlation metadata for every variant: PROPAGATED, ROOT, and missing
    (backwards-compatible default).
    """

    def _row(self, *, ci_id="ci-B", metric_id="cpu", value=95.0, status="CRITICAL",
             correlation_metadata=None, protocol="SNMP",
             threshold_metadata=None):
        from datetime import datetime, timezone

        base_metadata = {
            "critical": 90,
            "warning": 80,
            "criticality": 3,
            "operator": ">=",
            "name": metric_id,
        }
        if threshold_metadata:
            base_metadata.update(threshold_metadata)
        if correlation_metadata:
            base_metadata.update(correlation_metadata)
        return {
            "idempotency_key": "idem-1",
            "ci_id": ci_id,
            "metric_id": metric_id,
            "protocol": protocol,
            "source": "10.0.0.1:161",
            "observed_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "status": status,
            "value": {"numeric": value, "raw": value},
            "error": {"message": None},
            "metadata": base_metadata,
        }

    def test_writer_round_trip_preserves_propagated_metadata(self):
        """A pre-tagged PROPAGATED envelope survives build_event_rows."""
        from polling.event_writer import build_event_rows

        rows = build_event_rows([
            self._row(
                correlation_metadata={
                    "correlation_type": "PROPAGATED",
                    "propagated_from": "evt-A-root",
                    "root_cause_ci_id": "ci-A",
                },
            )
        ])

        assert rows[0]["correlation_type"] == "PROPAGATED"
        assert rows[0]["propagated_from"] == "evt-A-root"
        assert rows[0]["root_cause_ci_id"] == "ci-A"

    def test_writer_round_trip_preserves_root_metadata(self):
        """A pre-tagged ROOT envelope survives build_event_rows with
        propagated_from=None and root_cause_ci_id equal to its own CI."""
        from polling.event_writer import build_event_rows

        rows = build_event_rows([
            self._row(
                ci_id="ci-A",
                correlation_metadata={
                    "correlation_type": "ROOT",
                    "propagated_from": None,
                    "root_cause_ci_id": "ci-A",
                },
            )
        ])

        assert rows[0]["correlation_type"] == "ROOT"
        assert rows[0]["propagated_from"] is None
        assert rows[0]["root_cause_ci_id"] == "ci-A"

    def test_writer_round_trip_without_correlation_metadata_defaults_to_root(self):
        """An envelope with NO correlation_type metadata falls back to the
        writer's default (ROOT, own ci_id). Backwards compatibility for callers
        that haven't been wired into the resolver yet."""
        from polling.event_writer import build_event_rows

        rows = build_event_rows([self._row(ci_id="ci-XYZ")])

        assert rows[0]["correlation_type"] == "ROOT", (
            f"expected default ROOT when no correlation metadata present, "
            f"got {rows[0]['correlation_type']!r}"
        )
        assert rows[0]["propagated_from"] is None
        assert rows[0]["root_cause_ci_id"] == "ci-XYZ", (
            f"expected default root_cause_ci_id='ci-XYZ', "
            f"got {rows[0]['root_cause_ci_id']!r}"
        )

    def test_writer_round_trip_preserves_propagated_into_persisted_query(self):
        """A pre-tagged PROPAGATED envelope survives batch_update_events and
        shows up in the breach query parameters with correlation fields intact.
        This is the end-to-end proof the writer does NOT rewrite metadata to
        ROOT."""
        from polling.event_writer import batch_update_events
        from tests.conftest import MockNeo4jDriver

        driver = MockNeo4jDriver()
        # Use a value that breaches the critical threshold (500 >= 500)
        # so the breach query actually has rows to inspect.
        batch_update_events(driver, [
            self._row(
                ci_id="ci-B",
                metric_id="icmp_latency_ms",
                value=500.0,
                status="CRITICAL",
                protocol="ICMP",
                threshold_metadata={
                    "name": "ICMP Latency",
                    "warning": 100,
                    "critical": 500,
                    "operator": ">=",
                    "metric_kind": "telemetry",
                    "criticality": 3,
                },
                correlation_metadata={
                    "correlation_type": "PROPAGATED",
                    "propagated_from": "evt-A-root",
                    "root_cause_event_id": "evt-A-root",
                    "root_cause_ci_id": "ci-A",
                },
            )
        ])

        breach_query = next(
            q for q in driver.mock_session.queries
            if "row.is_breach AND row.event_type <> 'COLLECTION_FAILURE'" in q["query"]
        )
        params = breach_query["params"]["rows"]
        assert len(params) == 1
        assert params[0]["correlation_type"] == "PROPAGATED"
        assert params[0]["propagated_from"] == "evt-A-root"
        assert params[0]["root_cause_ci_id"] == "ci-A"
        assert params[0]["root_cause_event_id"] == "evt-A-root"
