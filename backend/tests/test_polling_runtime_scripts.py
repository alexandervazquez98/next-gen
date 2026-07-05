import json
from types import SimpleNamespace


class FakeSession:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_migration_script_dry_run_lists_polling_migrations(capsys):
    from scripts import run_polling_migrations

    assert run_polling_migrations.main(["--dry-run"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert "20260525_001_polling_queue" in payload["migrations"]


def test_migration_script_calls_runner_with_app_engine(monkeypatch, capsys):
    from scripts import run_polling_migrations

    fake_engine = object()
    calls = []
    monkeypatch.setattr(run_polling_migrations, "_load_engine", lambda: fake_engine)
    monkeypatch.setattr(
        run_polling_migrations,
        "_run_pending_migrations",
        lambda engine: calls.append(engine) or ["v1"],
    )

    assert run_polling_migrations.main([]) == 0

    assert calls == [fake_engine]
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"dry_run": False, "applied": ["v1"], "applied_count": 1}


def test_result_writer_script_noops_when_writer_flag_disabled(monkeypatch, capsys):
    from scripts import polling_result_writer

    monkeypatch.setattr(
        polling_result_writer, "_load_settings", lambda: SimpleNamespace(db_writer_enabled=False)
    )
    monkeypatch.setattr(
        polling_result_writer,
        "_run_writer_once",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("writer should not run")),
    )

    assert polling_result_writer.main([]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["enabled"] is False
    assert "POLLING_DB_WRITER_ENABLED" in payload["reason"]


def test_result_writer_script_runs_one_gated_batch_and_closes_sessions(monkeypatch, capsys):
    from scripts import polling_result_writer

    sessions = [FakeSession(), FakeSession()]
    calls = []
    monkeypatch.setattr(
        polling_result_writer,
        "_load_settings",
        lambda: SimpleNamespace(db_writer_enabled=True, result_batch_size=10),
    )
    monkeypatch.setattr(
        polling_result_writer, "_load_session_factory", lambda: lambda: sessions.pop(0)
    )
    monkeypatch.setattr(polling_result_writer, "_load_neo4j_driver", lambda: "neo4j-driver")

    def fake_run(queue_db, timescale_db, neo4j_driver, **kwargs):
        calls.append((queue_db, timescale_db, neo4j_driver, kwargs))
        return {"claimed": 1, "written": 1}

    monkeypatch.setattr(polling_result_writer, "_run_writer_once", fake_run)

    assert (
        polling_result_writer.main(
            [
                "--worker-id",
                "writer-test",
                "--lease-ttl-seconds",
                "45",
                "--writer-partitions",
                "1,2",
            ]
        )
        == 0
    )

    queue_db, timescale_db, neo4j_driver, kwargs = calls[0]
    assert queue_db.closed is True
    assert timescale_db.closed is True
    assert neo4j_driver == "neo4j-driver"
    assert kwargs["worker_id"] == "writer-test"
    assert kwargs["lease_ttl_seconds"] == 45
    assert kwargs["writer_partitions"] == [1, 2]
    payload = json.loads(capsys.readouterr().out)
    assert payload["enabled"] is True
    assert payload["stats"] == {"claimed": 1, "written": 1}


def test_enqueue_script_noops_when_queue_flag_disabled(monkeypatch, tmp_path, capsys):
    from scripts import polling_enqueue_cycle

    records = tmp_path / "records.json"
    records.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(
        polling_enqueue_cycle, "_load_settings", lambda: SimpleNamespace(pg_queue_enabled=False)
    )
    monkeypatch.setattr(
        polling_enqueue_cycle,
        "_load_session_factory",
        lambda: (_ for _ in ()).throw(AssertionError("db should not be opened")),
    )

    assert polling_enqueue_cycle.main(["--records-file", str(records)]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["enabled"] is False
    assert "POLLING_PG_QUEUE_ENABLED" in payload["reason"]


def test_enqueue_script_rejects_stale_records_when_metadata_cache_flag_enabled(
    monkeypatch, tmp_path, capsys
):
    from scripts import polling_enqueue_cycle

    records = tmp_path / "records.json"
    records.write_text(
        json.dumps(
            [{"node_id": "ci-1", "metric_id": "cpu", "protocol": "SNMP", "metadata_version": "old"}]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        polling_enqueue_cycle,
        "_load_settings",
        lambda: SimpleNamespace(pg_queue_enabled=True, metadata_cache_enabled=True),
    )

    assert (
        polling_enqueue_cycle.main(["--records-file", str(records), "--config-version", "current"])
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["reason"] == "metadata_version_mismatch"
    assert payload["stale_record_indexes"] == [0]


def test_enqueue_script_rejects_oversized_cycle_when_backpressure_flag_enabled(
    monkeypatch, tmp_path, capsys
):
    from scripts import polling_enqueue_cycle

    records = tmp_path / "records.json"
    records.write_text(
        json.dumps(
            [
                {
                    "node_id": "ci-1",
                    "metric_id": "PING-CHECK",
                    "protocol": "ICMP",
                    "ip": "10.0.0.1",
                },
                {
                    "node_id": "ci-2",
                    "metric_id": "PING-CHECK",
                    "protocol": "ICMP",
                    "ip": "10.0.0.2",
                },
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        polling_enqueue_cycle,
        "_load_settings",
        lambda: SimpleNamespace(
            pg_queue_enabled=True, backpressure_enabled=True, backpressure_max_task_queue_depth=1
        ),
    )

    assert polling_enqueue_cycle.main(["--records-file", str(records), "--dry-run"]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["reason"] == "backpressure_max_task_queue_depth"
    assert payload["task_count"] == 2
    assert payload["threshold"] == 1


def test_enqueue_script_builds_and_enqueues_cycle_when_enabled(monkeypatch, tmp_path, capsys):
    from scripts import polling_enqueue_cycle

    records = tmp_path / "records.json"
    records.write_text(
        json.dumps(
            [
                {
                    "node_id": "ci-1",
                    "metric_id": "PING-CHECK",
                    "protocol": "ICMP",
                    "ip": "10.0.0.1",
                }
            ]
        ),
        encoding="utf-8",
    )
    db = FakeSession()
    enqueued = []
    monkeypatch.setattr(
        polling_enqueue_cycle, "_load_settings", lambda: SimpleNamespace(pg_queue_enabled=True)
    )
    monkeypatch.setattr(polling_enqueue_cycle, "_load_session_factory", lambda: lambda: db)
    monkeypatch.setattr(
        polling_enqueue_cycle,
        "_enqueue_cycle_tasks",
        lambda db_arg, cycle, tasks: enqueued.append((db_arg, cycle, list(tasks))),
    )

    assert (
        polling_enqueue_cycle.main(
            [
                "--records-file",
                str(records),
                "--scheduled-for",
                "2026-05-25T12:00:00Z",
                "--config-version",
                "v1",
            ]
        )
        == 0
    )

    assert db.closed is True
    assert enqueued[0][0] is db
    assert len(enqueued[0][2]) == 1
    assert enqueued[0][2][0]["ci_id"] == "ci-1"
    payload = json.loads(capsys.readouterr().out)
    assert payload["enabled"] is True
    assert payload["dry_run"] is False
    assert payload["scheduled_for"] == "2026-05-25T12:00:00+00:00"
    assert payload["task_count"] == 1


def test_legacy_event_discriminator_audit_script_prints_json(monkeypatch, capsys):
    from scripts import audit_legacy_event_discriminators
    from services.legacy_event_discriminator_audit import classify_legacy_event_records

    result = classify_legacy_event_records(
        [{"event_id": "event-1", "ci_id": "ci-1", "metric_id": "metric-1", "event_type": None}]
    )
    monkeypatch.setattr(audit_legacy_event_discriminators, "_load_driver", lambda: object())
    monkeypatch.setattr(
        audit_legacy_event_discriminators,
        "run_legacy_event_discriminator_audit",
        lambda driver, limit=None: result,
    )

    assert audit_legacy_event_discriminators.main(["--format", "json", "--limit", "10"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["total_records"] == 1
    assert payload["findings"][0]["code"] == "missing_event_type"


def test_legacy_event_discriminator_audit_script_writes_markdown(monkeypatch, tmp_path, capsys):
    from scripts import audit_legacy_event_discriminators
    from services.legacy_event_discriminator_audit import classify_legacy_event_records

    output = tmp_path / "audit.md"
    result = classify_legacy_event_records(
        [{"event_id": "event-1", "ci_id": "ci-1", "metric_id": "metric-1", "source_protocol": None}]
    )
    monkeypatch.setattr(audit_legacy_event_discriminators, "_load_driver", lambda: object())
    monkeypatch.setattr(
        audit_legacy_event_discriminators,
        "run_legacy_event_discriminator_audit",
        lambda driver, limit=None: result,
    )

    assert (
        audit_legacy_event_discriminators.main(["--format", "markdown", "--output", str(output)])
        == 0
    )

    assert capsys.readouterr().out == ""
    report = output.read_text(encoding="utf-8")
    assert "# Legacy Event Discriminator Audit" in report
    assert "missing_source_protocol" in report
