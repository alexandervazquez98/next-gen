from tests.conftest import MockNeo4jDriver


def test_create_default_ping_metric_links_only_latency_and_jitter_sidecars(monkeypatch):
    from repositories import topology_repo

    driver = MockNeo4jDriver()
    monkeypatch.setattr(topology_repo, "get_db", lambda: driver)

    topology_repo.create_default_ping_metric("ci-1", "router-a")

    queries = "\n".join(q["query"] for q in driver.mock_session.queries)
    params = [q["params"] for q in driver.mock_session.queries]
    assert "icmp_latency_ms" in str(params)
    assert "icmp_jitter_ms" in str(params)
    assert "metric_kind = 'telemetry'" in queries
    assert "metric_kind = 'availability'" not in queries
    assert "PING-ci-1" not in str(params)
    assert "PING-router-a" not in str(params)
    assert "MERGE (m:MetricDef {id: $metric_id})" not in queries
    assert "MERGE (n)-[:HAS_METRIC]->(latency)" in queries
    assert "MERGE (n)-[:HAS_METRIC]->(jitter)" in queries


def test_create_default_ping_metric_edit_does_not_create_ping_metric(monkeypatch):
    from repositories import topology_repo

    driver = MockNeo4jDriver()
    monkeypatch.setattr(topology_repo, "get_db", lambda: driver)

    topology_repo.create_default_ping_metric("ci-1", "router-renamed")

    queries = "\n".join(q["query"] for q in driver.mock_session.queries)
    params = [q["params"] for q in driver.mock_session.queries]
    assert "RETURN availability.id AS metric_id" not in queries
    assert "PING-router-renamed" not in str(params)
    assert "PING-ci-1" not in str(params)


def test_migrate_icmp_sidecar_metrics_is_idempotent_for_existing_cis_with_ips(monkeypatch):
    from repositories import topology_repo

    driver = MockNeo4jDriver()
    monkeypatch.setattr(topology_repo, "get_db", lambda: driver)

    topology_repo.migrate_icmp_sidecar_metrics()

    queries = "\n".join(q["query"] for q in driver.mock_session.queries)
    params = [q["params"] for q in driver.mock_session.queries]
    assert "MERGE (latency:MetricDef {id: $latency_id})" in queries
    assert "MERGE (jitter:MetricDef {id: $jitter_id})" in queries
    assert "MATCH (n:CI)" in queries
    assert "n.ip IS NOT NULL" in queries
    assert "trim(toString(n.ip)) <> ''" in queries
    assert "availability.id = 'PING-CHECK'" not in queries
    assert "availability.id STARTS WITH 'PING-'" not in queries
    assert "MERGE (n)-[:HAS_METRIC]->(latency)" in queries
    assert "MERGE (n)-[:HAS_METRIC]->(jitter)" in queries
    assert {"latency_id": "icmp_latency_ms", "jitter_id": "icmp_jitter_ms"} in params


def test_migrate_icmp_sidecar_metrics_script_entrypoint_invokes_repository(monkeypatch):
    from scripts import migrate_icmp_sidecar_metrics as script

    calls = []
    monkeypatch.setattr(script.topology_repo, "migrate_icmp_sidecar_metrics", lambda: calls.append("migrated"))

    assert script.main() == 0
    assert calls == ["migrated"]


def test_migrate_icmp_availability_source_tags_icmp_except_sidecars(monkeypatch):
    from repositories import topology_repo

    driver = MockNeo4jDriver()
    monkeypatch.setattr(topology_repo, "get_db", lambda: driver)

    topology_repo.migrate_icmp_availability_source()

    queries = "\n".join(q["query"] for q in driver.mock_session.queries)
    params = [q["params"] for q in driver.mock_session.queries]
    assert "m.availability_source = coalesce(m.availability_source, 'ICMP')" in queries
    assert "e.availability_source = m.availability_source" in queries
    assert "e.availability_source = coalesce(e.availability_source, 'ICMP')" in queries
    assert "NOT m.id IN $excluded_metric_ids" in queries
    assert "NOT e.metric_id IN $excluded_metric_ids" in queries
    assert "coalesce(m.name, '') <> 'mariadb-GS'" in queries
    assert {"excluded_metric_ids": ["icmp_latency_ms", "icmp_jitter_ms", "mariadb-GS"]} in params


def test_migrate_icmp_availability_source_script_entrypoint_invokes_repository(monkeypatch):
    from scripts import migrate_icmp_availability_source as script

    calls = []
    monkeypatch.setattr(script.topology_repo, "migrate_icmp_availability_source", lambda: calls.append("migrated"))

    assert script.main() == 0
    assert calls == ["migrated"]
