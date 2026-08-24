from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from uuid import uuid4


class FakeSettings:
    db_writer_enabled = True
    result_batch_size = 10


def _row(*, key="idem-1", numeric=42.0, status="OK", last_error_code=None):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return SimpleNamespace(
        result_id=uuid4(),
        task_id=uuid4(),
        cycle_id=uuid4(),
        idempotency_key=key,
        protocol="SNMP",
        ci_id="ci-1",
        metric_id="cpu",
        observed_at=now,
        received_at=now,
        priority=50,
        partition_key=1,
        last_error_code=last_error_code,
        envelope={
            "idempotency_key": key,
            "ci_id": "ci-1",
            "metric_id": "cpu",
            "protocol": "SNMP",
            "source": "10.0.0.1:161/1.2.3",
            "observed_at": now.isoformat(),
            "status": status,
            "value": {"numeric": numeric, "raw": numeric},
            "error": {"code": None, "message": None, "retryable": False},
            "metadata": {"critical": 90, "warning": 80, "criticality": 3, "operator": ">="},
        },
    )


def test_writer_skips_duplicate_receipts_and_marks_result_written(monkeypatch):
    from polling import writer_pool

    completed = []
    monkeypatch.setattr(writer_pool.pg_queue, "claim_results", lambda *a, **k: [_row()])
    monkeypatch.setattr(writer_pool, "receipt_exists", lambda db, key: True)
    monkeypatch.setattr(writer_pool.pg_queue, "complete_result", lambda db, rid: completed.append(rid))
    monkeypatch.setattr(writer_pool, "persist_samples_and_receipts", lambda *a, **k: (_ for _ in ()).throw(AssertionError("duplicate inserted")))
    monkeypatch.setattr(writer_pool.event_writer, "batch_update_events", lambda *a, **k: (_ for _ in ()).throw(AssertionError("duplicate updated")))

    stats = writer_pool.run_writer_once(object(), object(), object(), settings=FakeSettings(), worker_id="writer-a")

    assert stats == {"claimed": 1, "inserted": 0, "duplicates": 1, "written": 1, "retried": 0, "dead_lettered": 0}
    assert len(completed) == 1


def test_writer_expands_icmp_sidecar_samples_and_emits_events_for_breaching_sidecars(monkeypatch):
    from polling import writer_pool

    persisted = []
    event_rows = []
    row = _row(key="icmp-1", numeric=1.0)
    row.protocol = "ICMP"
    row.metric_id = "PING-CHECK"
    row.envelope.update({
        "protocol": "ICMP",
        "metric_id": "PING-CHECK",
        "metadata": {
            "metric_kind": "availability",
            "icmp": {"latency_ms": 20.0, "sidecar_metric_ids": ["icmp_latency_ms", "icmp_jitter_ms", "packet_loss_pct"]},
        },
    })
    monkeypatch.setattr(writer_pool.pg_queue, "claim_results", lambda *a, **k: [row])
    monkeypatch.setattr(writer_pool, "receipt_exists", lambda db, key: False)
    monkeypatch.setattr(writer_pool, "previous_metric_value", lambda db, node_id, metric_id, before: 12.5)
    monkeypatch.setattr(writer_pool, "persist_samples_and_receipts", lambda db, rows, samples: persisted.append((list(rows), list(samples))))
    monkeypatch.setattr(writer_pool.event_writer, "batch_update_events", lambda driver, rows, **kwargs: event_rows.extend(rows))
    monkeypatch.setattr(writer_pool.pg_queue, "complete_result", lambda db, rid: None)

    stats = writer_pool.run_writer_once(object(), object(), object(), settings=FakeSettings(), worker_id="writer-a")

    assert stats["inserted"] == 4
    assert persisted[0][1] == [
        {"node_id": "ci-1", "metric_id": "PING-CHECK", "value": 1.0, "time": row.observed_at},
        {"node_id": "ci-1", "metric_id": "icmp_latency_ms", "value": 20.0, "time": row.observed_at},
        {"node_id": "ci-1", "metric_id": "icmp_jitter_ms", "value": 7.5, "time": row.observed_at},
        {"node_id": "ci-1", "metric_id": "packet_loss_pct", "value": 0.0, "time": row.observed_at},
    ]
    # Latency below the warning threshold (20 ms) → only the primary and the
    # latency envelope are emitted; jitter (7.5) and packet loss (0%) stay OK
    # so their envelopes are dropped before reaching batch_update_events.
    assert [event["metric_id"] for event in event_rows] == ["PING-CHECK", "icmp_latency_ms"]
    assert event_rows[1]["status"] == "OK"
    assert event_rows[1]["metadata"]["warning"] == 100.0
    assert event_rows[1]["metadata"]["critical"] == 500.0


def test_writer_expands_failed_icmp_availability_to_packet_loss_sidecar(monkeypatch):
    from polling import writer_pool

    persisted = []
    event_rows = []
    row = _row(key="icmp-failed", numeric=0.0)
    row.protocol = "ICMP"
    row.metric_id = "PING-CHECK"
    row.envelope.update({
        "protocol": "ICMP",
        "metric_id": "PING-CHECK",
        "metadata": {"metric_kind": "availability", "icmp": {"sidecar_metric_ids": ["icmp_latency_ms", "icmp_jitter_ms", "packet_loss_pct"]}},
    })
    monkeypatch.setattr(writer_pool.pg_queue, "claim_results", lambda *a, **k: [row])
    monkeypatch.setattr(writer_pool, "receipt_exists", lambda db, key: False)
    monkeypatch.setattr(writer_pool, "previous_metric_value", lambda *a, **k: (_ for _ in ()).throw(AssertionError("latency lookup not expected")))
    monkeypatch.setattr(writer_pool, "persist_samples_and_receipts", lambda db, rows, samples: persisted.append((list(rows), list(samples))))
    monkeypatch.setattr(writer_pool.event_writer, "batch_update_events", lambda driver, rows, **kwargs: event_rows.extend(rows))
    monkeypatch.setattr(writer_pool.pg_queue, "complete_result", lambda db, rid: None)

    stats = writer_pool.run_writer_once(object(), object(), object(), settings=FakeSettings(), worker_id="writer-a")

    assert stats["inserted"] == 2
    assert persisted[0][1] == [
        {"node_id": "ci-1", "metric_id": "PING-CHECK", "value": 0.0, "time": row.observed_at},
        {"node_id": "ci-1", "metric_id": "packet_loss_pct", "value": 100.0, "time": row.observed_at},
    ]
    # CI down → packet_loss=100 ≥ 50% critical → CRITICAL envelope emitted
    # alongside the primary availability row.
    assert [event["metric_id"] for event in event_rows] == ["PING-CHECK", "packet_loss_pct"]
    packet_loss_event = event_rows[1]
    assert packet_loss_event["status"] == "CRITICAL"
    assert packet_loss_event["value"]["numeric"] == 100.0
    assert packet_loss_event["metadata"]["metric_kind"] == "telemetry"
    assert packet_loss_event["metadata"]["warning"] == 10.0
    assert packet_loss_event["metadata"]["critical"] == 50.0


def test_writer_persists_only_sidecars_for_internal_icmp_availability(monkeypatch):
    from polling import writer_pool

    persisted = []
    event_rows = []
    completed = []
    row = _row(key="icmp-internal", numeric=1.0)
    row.protocol = "ICMP"
    row.metric_id = "icmp_availability"
    row.envelope.update({
        "protocol": "ICMP",
        "metric_id": "icmp_availability",
        "metadata": {
            "metric_kind": "availability",
            "internal": True,
            "icmp": {"latency_ms": 20.0, "sidecar_metric_ids": ["icmp_latency_ms", "icmp_jitter_ms", "packet_loss_pct"]},
        },
    })
    monkeypatch.setattr(writer_pool.pg_queue, "claim_results", lambda *a, **k: [row])
    monkeypatch.setattr(writer_pool, "receipt_exists", lambda db, key: False)
    monkeypatch.setattr(writer_pool, "previous_metric_value", lambda db, node_id, metric_id, before: 12.5)
    monkeypatch.setattr(writer_pool, "persist_samples_and_receipts", lambda db, rows, samples: persisted.append((list(rows), list(samples))))
    monkeypatch.setattr(writer_pool.event_writer, "batch_update_events", lambda driver, rows, **kwargs: event_rows.extend(rows))
    monkeypatch.setattr(writer_pool.pg_queue, "complete_result", lambda db, rid: completed.append(rid))

    stats = writer_pool.run_writer_once(object(), object(), object(), settings=FakeSettings(), worker_id="writer-a")

    assert stats["inserted"] == 3
    assert persisted[0][1] == [
        {"node_id": "ci-1", "metric_id": "icmp_latency_ms", "value": 20.0, "time": row.observed_at},
        {"node_id": "ci-1", "metric_id": "icmp_jitter_ms", "value": 7.5, "time": row.observed_at},
        {"node_id": "ci-1", "metric_id": "packet_loss_pct", "value": 0.0, "time": row.observed_at},
    ]
    assert [event["metric_id"] for event in event_rows] == ["icmp_latency_ms"]
    assert event_rows[0]["status"] == "OK"
    assert completed == [row.result_id]


def test_writer_emits_warning_latency_event_from_icmp_sidecar(monkeypatch):
    from polling import writer_pool

    persisted = []
    event_rows = []
    row = _row(key="icmp-warning", numeric=1.0)
    row.protocol = "ICMP"
    row.metric_id = "icmp_availability"
    row.envelope.update({
        "protocol": "ICMP",
        "metric_id": "icmp_availability",
        "metadata": {
            "metric_kind": "availability",
            "internal": True,
            "icmp": {"latency_ms": 150.0, "sidecar_metric_ids": ["icmp_latency_ms"]},
        },
    })
    monkeypatch.setattr(writer_pool.pg_queue, "claim_results", lambda *a, **k: [row])
    monkeypatch.setattr(writer_pool, "receipt_exists", lambda db, key: False)
    monkeypatch.setattr(writer_pool, "previous_metric_value", lambda db, node_id, metric_id, before: None)
    monkeypatch.setattr(writer_pool, "persist_samples_and_receipts", lambda db, rows, samples: persisted.append((list(rows), list(samples))))
    monkeypatch.setattr(writer_pool.event_writer, "batch_update_events", lambda driver, rows, **kwargs: event_rows.extend(rows))
    monkeypatch.setattr(writer_pool.pg_queue, "complete_result", lambda db, rid: None)

    stats = writer_pool.run_writer_once(object(), object(), object(), settings=FakeSettings(), worker_id="writer-a")

    assert stats["inserted"] == 1
    assert event_rows[0]["metric_id"] == "icmp_latency_ms"
    assert event_rows[0]["status"] == "WARNING"
    assert event_rows[0]["value"]["numeric"] == 150.0


def test_writer_emits_packet_loss_critical_event_when_availability_is_zero(monkeypatch):
    from polling import writer_pool

    persisted = []
    event_rows = []
    row = _row(key="icmp-pktloss-critical", numeric=0.0)
    row.protocol = "ICMP"
    row.metric_id = "PING-CHECK"
    row.envelope.update({
        "protocol": "ICMP",
        "metric_id": "PING-CHECK",
        "metadata": {"metric_kind": "availability", "icmp": {"sidecar_metric_ids": ["icmp_latency_ms", "icmp_jitter_ms", "packet_loss_pct"]}},
    })
    monkeypatch.setattr(writer_pool.pg_queue, "claim_results", lambda *a, **k: [row])
    monkeypatch.setattr(writer_pool, "receipt_exists", lambda db, key: False)
    monkeypatch.setattr(writer_pool, "previous_metric_value", lambda *a, **k: None)
    monkeypatch.setattr(writer_pool, "persist_samples_and_receipts", lambda db, rows, samples: persisted.append((list(rows), list(samples))))
    monkeypatch.setattr(writer_pool.event_writer, "batch_update_events", lambda driver, rows, **kwargs: event_rows.extend(rows))
    monkeypatch.setattr(writer_pool.pg_queue, "complete_result", lambda db, rid: None)

    stats = writer_pool.run_writer_once(object(), object(), object(), settings=FakeSettings(), worker_id="writer-a")

    # CI down (availability=0) → packet_loss sample is 100% and the envelope
    # builder must surface a CRITICAL packet_loss_pct event alongside the
    # primary availability row.
    assert stats["inserted"] == 2
    metric_ids = [event["metric_id"] for event in event_rows]
    assert metric_ids == ["PING-CHECK", "packet_loss_pct"]
    packet_loss_event = event_rows[1]
    assert packet_loss_event["status"] == "CRITICAL"
    assert packet_loss_event["value"]["numeric"] == 100.0
    assert packet_loss_event["metadata"]["metric_kind"] == "telemetry"
    assert packet_loss_event["metadata"]["warning"] == 10.0
    assert packet_loss_event["metadata"]["critical"] == 50.0


def test_writer_emits_packet_loss_warning_event_at_warning_threshold(monkeypatch):
    from polling import writer_pool

    event_rows = []
    # Simulate an availability=0.2 envelope routed through a custom envelope
    # that drives packet_loss to a WARNING (10–50%) band.
    row = _row(key="icmp-pktloss-warn", numeric=0.2)
    row.protocol = "ICMP"
    row.metric_id = "PING-CHECK"
    row.envelope.update({
        "protocol": "ICMP",
        "metric_id": "PING-CHECK",
        "metadata": {"metric_kind": "availability", "icmp": {"sidecar_metric_ids": ["packet_loss_pct"]}},
    })

    # Force packet_loss to land in the WARNING band via the envelope builder:
    # we craft a synthetic envelope whose packet_loss derivation yields 25%.
    envelope_factory = None
    real_packet_loss = writer_pool._icmp_packet_loss_event_envelope

    def patched(envelope, db=None):
        # Override packet_loss derivation by short-circuiting: if numeric > 0,
        # we want to test the WARNING band, so we substitute 25.0 manually.
        from config import get_icmp_settings

        settings = get_icmp_settings()
        return {
            **dict(envelope),
            "metric_id": "packet_loss_pct",
            "status": "WARNING",
            "value": {"numeric": 25.0, "raw": 25.0},
            "metadata": writer_pool.packet_loss_threshold_metadata(
                warning_pct=settings.packet_loss_warning_pct,
                critical_pct=settings.packet_loss_critical_pct,
            ),
        }

    monkeypatch.setattr(writer_pool.pg_queue, "claim_results", lambda *a, **k: [row])
    monkeypatch.setattr(writer_pool, "receipt_exists", lambda db, key: False)
    monkeypatch.setattr(writer_pool, "previous_metric_value", lambda *a, **k: None)
    monkeypatch.setattr(writer_pool, "persist_samples_and_receipts", lambda *a, **k: None)
    monkeypatch.setattr(writer_pool, "_icmp_packet_loss_event_envelope", patched)
    monkeypatch.setattr(writer_pool.event_writer, "batch_update_events", lambda driver, rows, **kwargs: event_rows.extend(rows))
    monkeypatch.setattr(writer_pool.pg_queue, "complete_result", lambda db, rid: None)

    writer_pool.run_writer_once(object(), object(), object(), settings=FakeSettings(), worker_id="writer-a")

    assert [event["metric_id"] for event in event_rows] == ["PING-CHECK", "packet_loss_pct"]
    packet_loss_event = event_rows[1]
    assert packet_loss_event["status"] == "WARNING"
    assert packet_loss_event["value"]["numeric"] == 25.0
    assert packet_loss_event["metadata"]["criticality"] == 3


def test_writer_emits_jitter_critical_event_above_threshold(monkeypatch):
    from polling import writer_pool

    event_rows = []
    row = _row(key="icmp-jitter-critical", numeric=1.0)
    row.protocol = "ICMP"
    row.metric_id = "icmp_availability"
    row.envelope.update({
        "protocol": "ICMP",
        "metric_id": "icmp_availability",
        "metadata": {
            "metric_kind": "availability",
            "internal": True,
            "icmp": {"latency_ms": 300.0, "sidecar_metric_ids": ["icmp_latency_ms", "icmp_jitter_ms", "packet_loss_pct"]},
        },
    })
    # previous latency = 100.0 → jitter = 200.0 (above 150.0 critical).
    monkeypatch.setattr(writer_pool.pg_queue, "claim_results", lambda *a, **k: [row])
    monkeypatch.setattr(writer_pool, "receipt_exists", lambda db, key: False)
    monkeypatch.setattr(writer_pool, "previous_metric_value", lambda db, node_id, metric_id, before: 100.0)
    monkeypatch.setattr(writer_pool, "persist_samples_and_receipts", lambda *a, **k: None)
    monkeypatch.setattr(writer_pool.event_writer, "batch_update_events", lambda driver, rows, **kwargs: event_rows.extend(rows))
    monkeypatch.setattr(writer_pool.pg_queue, "complete_result", lambda db, rid: None)

    writer_pool.run_writer_once(object(), object(), object(), settings=FakeSettings(), worker_id="writer-a")

    metric_ids = [event["metric_id"] for event in event_rows]
    # Latency 300 (warning), jitter 200 (critical), packet_loss 0 (OK) → only
    # latency and jitter envelopes flow to batch_update_events.
    assert metric_ids == ["icmp_latency_ms", "icmp_jitter_ms"]
    jitter_event = next(event for event in event_rows if event["metric_id"] == "icmp_jitter_ms")
    assert jitter_event["status"] == "CRITICAL"
    assert jitter_event["value"]["numeric"] == 200.0
    assert jitter_event["metadata"]["metric_kind"] == "telemetry"
    assert jitter_event["metadata"]["name"] == "ICMP Jitter"
    assert jitter_event["metadata"]["warning"] == 50.0
    assert jitter_event["metadata"]["critical"] == 150.0


def test_writer_emits_jitter_event_when_previous_latency_available(monkeypatch):
    from polling import writer_pool

    event_rows = []
    row = _row(key="icmp-jitter-warn", numeric=1.0)
    row.protocol = "ICMP"
    row.metric_id = "icmp_availability"
    row.envelope.update({
        "protocol": "ICMP",
        "metric_id": "icmp_availability",
        "metadata": {
            "metric_kind": "availability",
            "internal": True,
            "icmp": {"latency_ms": 130.0, "sidecar_metric_ids": ["icmp_latency_ms", "icmp_jitter_ms", "packet_loss_pct"]},
        },
    })
    # previous = 50.0 → jitter = 80.0 (above 50.0 warning, below 150.0 critical).
    monkeypatch.setattr(writer_pool.pg_queue, "claim_results", lambda *a, **k: [row])
    monkeypatch.setattr(writer_pool, "receipt_exists", lambda db, key: False)
    monkeypatch.setattr(writer_pool, "previous_metric_value", lambda db, node_id, metric_id, before: 50.0)
    monkeypatch.setattr(writer_pool, "persist_samples_and_receipts", lambda *a, **k: None)
    monkeypatch.setattr(writer_pool.event_writer, "batch_update_events", lambda driver, rows, **kwargs: event_rows.extend(rows))
    monkeypatch.setattr(writer_pool.pg_queue, "complete_result", lambda db, rid: None)

    writer_pool.run_writer_once(object(), object(), object(), settings=FakeSettings(), worker_id="writer-a")

    metric_ids = [event["metric_id"] for event in event_rows]
    assert metric_ids == ["icmp_latency_ms", "icmp_jitter_ms"]
    jitter_event = next(event for event in event_rows if event["metric_id"] == "icmp_jitter_ms")
    assert jitter_event["status"] == "WARNING"
    assert jitter_event["value"]["numeric"] == 80.0


def test_writer_does_not_emit_jitter_event_when_previous_latency_missing(monkeypatch):
    from polling import writer_pool

    event_rows = []
    row = _row(key="icmp-jitter-no-prev", numeric=1.0)
    row.protocol = "ICMP"
    row.metric_id = "icmp_availability"
    row.envelope.update({
        "protocol": "ICMP",
        "metric_id": "icmp_availability",
        "metadata": {
            "metric_kind": "availability",
            "internal": True,
            "icmp": {"latency_ms": 130.0, "sidecar_metric_ids": ["icmp_latency_ms", "icmp_jitter_ms", "packet_loss_pct"]},
        },
    })
    monkeypatch.setattr(writer_pool.pg_queue, "claim_results", lambda *a, **k: [row])
    monkeypatch.setattr(writer_pool, "receipt_exists", lambda db, key: False)
    # No previous latency (first sample ever) → jitter envelope must return None.
    monkeypatch.setattr(writer_pool, "previous_metric_value", lambda *a, **k: None)
    monkeypatch.setattr(writer_pool, "persist_samples_and_receipts", lambda *a, **k: None)
    monkeypatch.setattr(writer_pool.event_writer, "batch_update_events", lambda driver, rows, **kwargs: event_rows.extend(rows))
    monkeypatch.setattr(writer_pool.pg_queue, "complete_result", lambda db, rid: None)

    writer_pool.run_writer_once(object(), object(), object(), settings=FakeSettings(), worker_id="writer-a")

    # No jitter envelope in the event batch because the previous-latency
    # lookup returned None.
    assert all(event["metric_id"] != "icmp_jitter_ms" for event in event_rows)


def test_writer_batches_timescale_inserts_receipts_and_neo4j_updates(monkeypatch):
    from polling import writer_pool

    persisted = []
    completed = []
    event_rows = []
    row = _row(numeric=17.0)
    monkeypatch.setattr(writer_pool.pg_queue, "claim_results", lambda *a, **k: [row])
    monkeypatch.setattr(writer_pool, "receipt_exists", lambda db, key: False)
    monkeypatch.setattr(writer_pool, "persist_samples_and_receipts", lambda db, rows, samples: persisted.append((list(rows), list(samples))))
    monkeypatch.setattr(writer_pool.event_writer, "batch_update_events", lambda driver, rows, **kwargs: event_rows.extend(rows))
    monkeypatch.setattr(writer_pool.pg_queue, "complete_result", lambda db, rid: completed.append(rid))

    stats = writer_pool.run_writer_once(object(), object(), object(), settings=FakeSettings(), worker_id="writer-a")

    assert stats["inserted"] == 1
    assert persisted[0][1] == [{"node_id": "ci-1", "metric_id": "cpu", "value": 17.0, "time": row.observed_at}]
    assert persisted[0][0][0]["idempotency_key"] == "idem-1"
    assert event_rows[0]["idempotency_key"] == "idem-1"
    assert completed == [row.result_id]


def test_writer_retries_as_neo4j_pending_after_timescale_receipt_success(monkeypatch):
    from polling import writer_pool

    retried = []
    row = _row(key="idem-2", numeric=1.0)
    monkeypatch.setattr(writer_pool.pg_queue, "claim_results", lambda *a, **k: [row])
    monkeypatch.setattr(writer_pool, "receipt_exists", lambda db, key: False)
    monkeypatch.setattr(writer_pool, "persist_samples_and_receipts", lambda *a, **k: None)
    monkeypatch.setattr(writer_pool.event_writer, "batch_update_events", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("neo4j down")))
    monkeypatch.setattr(writer_pool.pg_queue, "retry_result", lambda db, rid, **kw: retried.append((rid, kw)))

    stats = writer_pool.run_writer_once(object(), object(), object(), settings=FakeSettings(), worker_id="writer-a", now=datetime(2026, 1, 1, tzinfo=timezone.utc))

    assert stats["retried"] == 1
    assert retried[0][0] == row.result_id
    assert retried[0][1]["error_code"] == "neo4j_pending"
    assert retried[0][1]["next_eligible_at"] == datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=30)


def test_persist_samples_and_receipts_rolls_back_receipt_failure():
    from polling import writer_pool

    class FakeTelemetryDb:
        def __init__(self):
            self.bulk_saved = []
            self.committed = False
            self.rolled_back = False

        def bulk_save_objects(self, objects):
            self.bulk_saved.extend(objects)

        def execute(self, *args, **kwargs):
            raise RuntimeError("receipt insert failed")

        def commit(self):
            self.committed = True

        def rollback(self):
            self.rolled_back = True

    db = FakeTelemetryDb()
    row = {"idempotency_key": "idem-rollback", "result_id": uuid4(), "cycle_id": uuid4(), "envelope": _row(key="idem-rollback").envelope}

    try:
        writer_pool.persist_samples_and_receipts(
            db,
            [row],
            [{"node_id": "ci-1", "metric_id": "cpu", "value": 1.0, "time": datetime(2026, 1, 1, tzinfo=timezone.utc)}],
        )
    except RuntimeError as exc:
        assert "receipt insert failed" in str(exc)
    else:
        raise AssertionError("expected receipt failure")

    assert db.bulk_saved
    assert db.rolled_back is True
    assert db.committed is False
