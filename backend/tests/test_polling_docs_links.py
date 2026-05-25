from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_polling_docs_are_linked_from_readme_and_reference_existing_scripts():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    runbook = REPO_ROOT / "docs" / "polling-pipeline-runbook.md"
    tuning = REPO_ROOT / "docs" / "polling-pipeline-tuning.md"

    assert runbook.exists()
    assert tuning.exists()
    assert "docs/polling-pipeline-runbook.md" in readme
    assert "docs/polling-pipeline-tuning.md" in readme

    combined = runbook.read_text(encoding="utf-8") + tuning.read_text(encoding="utf-8")
    for path in [
        "backend/scripts/polling_host_benchmark.py",
        "backend/scripts/polling_load_simulator.py",
        "backend/scripts/run_polling_migrations.py",
        "backend/scripts/polling_enqueue_cycle.py",
        "backend/scripts/polling_result_writer.py",
    ]:
        assert (REPO_ROOT / path).exists()
        assert path in combined


def test_polling_docs_cover_flags_rollout_and_observability_metrics():
    docs = "\n".join(
        [
            (REPO_ROOT / "docs" / "polling-pipeline-runbook.md").read_text(encoding="utf-8"),
            (REPO_ROOT / "docs" / "polling-pipeline-tuning.md").read_text(encoding="utf-8"),
        ]
    )

    required_terms = [
        "POLLING_PG_QUEUE_ENABLED",
        "POLLING_SNMP_LEASED_WORKER",
        "POLLING_DB_WRITER_ENABLED",
        "POLLING_BACKPRESSURE_ENABLED",
        "POLLING_METADATA_CACHE_ENABLED",
        "cycle lag",
        "queue depth",
        "lease expiries",
        "worker p95/p99",
        "timeout rate",
        "writer lag",
        "DB latency",
        "dead-letter",
        "Neo4j pending",
        "rollback",
        "replay",
        "emergency concurrency reduction",
        "simulator evidence",
    ]
    for term in required_terms:
        assert term in docs
