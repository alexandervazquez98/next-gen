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


def test_writer_batches_timescale_inserts_receipts_and_neo4j_updates(monkeypatch):
    from polling import writer_pool

    persisted = []
    completed = []
    event_rows = []
    row = _row(numeric=17.0)
    monkeypatch.setattr(writer_pool.pg_queue, "claim_results", lambda *a, **k: [row])
    monkeypatch.setattr(writer_pool, "receipt_exists", lambda db, key: False)
    monkeypatch.setattr(writer_pool, "persist_samples_and_receipts", lambda db, rows, samples: persisted.append((list(rows), list(samples))))
    monkeypatch.setattr(writer_pool.event_writer, "batch_update_events", lambda driver, rows: event_rows.extend(rows))
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
