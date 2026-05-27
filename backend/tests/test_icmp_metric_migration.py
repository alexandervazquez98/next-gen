from tests.conftest import MockNeo4jDriver


def test_create_default_ping_metric_links_latency_and_jitter_sidecars(monkeypatch):
    from repositories import topology_repo

    driver = MockNeo4jDriver()
    monkeypatch.setattr(topology_repo, "get_db", lambda: driver)

    topology_repo.create_default_ping_metric("ci-1", "router-a")

    queries = "\n".join(q["query"] for q in driver.mock_session.queries)
    params = [q["params"] for q in driver.mock_session.queries]
    assert "PING-router-a" in str(params)
    assert "icmp_latency_ms" in str(params)
    assert "icmp_jitter_ms" in str(params)
    assert "metric_kind = 'availability'" in queries
    assert "metric_kind = 'telemetry'" in queries
    assert "MERGE (n)-[:HAS_METRIC]->(latency)" in queries
    assert "MERGE (n)-[:HAS_METRIC]->(jitter)" in queries


def test_migrate_icmp_sidecar_metrics_is_idempotent_for_existing_ping_cis(monkeypatch):
    from repositories import topology_repo

    driver = MockNeo4jDriver()
    monkeypatch.setattr(topology_repo, "get_db", lambda: driver)

    topology_repo.migrate_icmp_sidecar_metrics()

    queries = "\n".join(q["query"] for q in driver.mock_session.queries)
    params = [q["params"] for q in driver.mock_session.queries]
    assert "MERGE (latency:MetricDef {id: $latency_id})" in queries
    assert "MERGE (jitter:MetricDef {id: $jitter_id})" in queries
    assert "availability.id = 'PING-CHECK'" in queries
    assert "availability.id STARTS WITH 'PING-'" in queries
    assert "MERGE (n)-[:HAS_METRIC]->(latency)" in queries
    assert "MERGE (n)-[:HAS_METRIC]->(jitter)" in queries
    assert {"latency_id": "icmp_latency_ms", "jitter_id": "icmp_jitter_ms"} in params


def test_migrate_icmp_sidecar_metrics_script_entrypoint_invokes_repository(monkeypatch):
    from scripts import migrate_icmp_sidecar_metrics as script

    calls = []
    monkeypatch.setattr(script.topology_repo, "migrate_icmp_sidecar_metrics", lambda: calls.append("migrated"))

    assert script.main() == 0
    assert calls == ["migrated"]
