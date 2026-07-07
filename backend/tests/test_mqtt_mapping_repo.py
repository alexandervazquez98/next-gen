"""Repository tests for MQTT mapping persistence and lifecycle transitions.

RED phase: these tests intentionally target repository behavior before implementation.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

pytestmark = [pytest.mark.unit]


SOURCE_DEVICE_ID = "mqtt-device-001"
SOURCE_METRIC_ID = "mqtt-device-001/temperature"
SOURCE_METRIC_NAME = "temperature"
TARGET_CI_ID = "ci-router-01"
TARGET_METRIC_DEF_ID = "temperature_celsius"
CREATED_BY = "mapper-01"
APPROVED_BY = "lead-op"


# ── create_draft ─────────────────────────────────────────────────────────────


def test_create_draft_persists_draft_status(mock_neo4j_driver):
    """create_draft MUST persist DRAFT mappings with deterministic query params."""
    from repositories.mqtt_mapping_repo import MqttMappingRepo

    created = {
        "id": "map-001",
        "source_device_id": SOURCE_DEVICE_ID,
        "source_metric_id": SOURCE_METRIC_ID,
        "source_metric_name": SOURCE_METRIC_NAME,
        "target_ci_id": TARGET_CI_ID,
        "target_metric_def_id": TARGET_METRIC_DEF_ID,
        "status": "DRAFT",
        "version": 1,
    }

    # Mapping id does not yet exist.
    mock_neo4j_driver.mock_session.set_response(
        "match (m:mqttmetricmapping) where m.id = $mapping_id",
        [],
    )
    mock_neo4j_driver.mock_session.set_response("create (m:mqttmetricmapping)", [created])

    # Existence checks pass.
    mock_neo4j_driver.mock_session.set_response("match (d:device)", [{"c": 1}])
    mock_neo4j_driver.mock_session.set_response("match (c:ci)", [{"c": 1}])
    mock_neo4j_driver.mock_session.set_response("match (md:metricdef)", [{"c": 1}])

    repo = MqttMappingRepo(driver=mock_neo4j_driver)
    result = repo.create_draft(
        mapping_id="map-001",
        source_device_id=SOURCE_DEVICE_ID,
        source_metric_id=SOURCE_METRIC_ID,
        source_metric_name=SOURCE_METRIC_NAME,
        target_ci_id=TARGET_CI_ID,
        target_metric_def_id=TARGET_METRIC_DEF_ID,
        created_by=CREATED_BY,
    )

    assert result["status"] == "DRAFT"
    assert result["id"] == "map-001"

    create_queries = mock_neo4j_driver.mock_session.queries
    assert create_queries, "expected at least one query"
    # Last query should be the write path with scalar and relationship wiring.
    cypher = create_queries[-1]["query"].lower()
    assert "create (m:mqttmetricmapping" in cypher
    assert "has_mqtt_mapping" in cypher
    assert "targets_ci" in cypher
    assert "targets_metric_def" in cypher
    params = create_queries[-1]["params"]
    assert params["source_device_id"] == SOURCE_DEVICE_ID
    assert params["source_metric_id"] == SOURCE_METRIC_ID
    assert params["target_ci_id"] == TARGET_CI_ID
    assert params["target_metric_def_id"] == TARGET_METRIC_DEF_ID


def test_create_draft_rejects_duplicate_mapping_id(mock_neo4j_driver):
    """create_draft must not overwrite existing mapping IDs (including DRAFT/REVOKED)."""
    from repositories.mqtt_mapping_repo import MappingConflictError, MqttMappingRepo

    mock_neo4j_driver.mock_session.set_response(
        "match (m:mqttmetricmapping) where m.id = $mapping_id",
        [
            {
                "id": "map-001",
                "status": "DRAFT",
                "source_device_id": SOURCE_DEVICE_ID,
                "source_metric_id": SOURCE_METRIC_ID,
                "source_metric_name": SOURCE_METRIC_NAME,
                "target_ci_id": TARGET_CI_ID,
                "target_metric_def_id": TARGET_METRIC_DEF_ID,
                "version": 1,
            }
        ],
    )

    repo = MqttMappingRepo(driver=mock_neo4j_driver)
    with pytest.raises(MappingConflictError):
        repo.create_draft(
            mapping_id="map-001",
            source_device_id=SOURCE_DEVICE_ID,
            source_metric_id=SOURCE_METRIC_ID,
            source_metric_name=SOURCE_METRIC_NAME,
            target_ci_id=TARGET_CI_ID,
            target_metric_def_id=TARGET_METRIC_DEF_ID,
            created_by=CREATED_BY,
        )


# ── existence helpers ────────────────────────────────────────────────────────


def test_create_draft_rejects_missing_source(mock_neo4j_driver):
    """create_draft should reject mappings when source device does not exist."""
    from repositories.mqtt_mapping_repo import MappingNotFoundError, MqttMappingRepo

    # Source missing; target checks may exist but are irrelevant if source is first.
    mock_neo4j_driver.mock_session.set_response("match (d:device)", [])

    repo = MqttMappingRepo(driver=mock_neo4j_driver)
    with pytest.raises(MappingNotFoundError):
        repo.create_draft(
            mapping_id="map-missing-source",
            source_device_id=SOURCE_DEVICE_ID,
            source_metric_id=SOURCE_METRIC_ID,
            source_metric_name=SOURCE_METRIC_NAME,
            target_ci_id=TARGET_CI_ID,
            target_metric_def_id=TARGET_METRIC_DEF_ID,
            created_by=CREATED_BY,
        )


# ── get_approved + status transitions ───────────────────────────────────────


def test_get_approved_returns_only_matching_source_pair(mock_neo4j_driver):
    """get_approved must query for source pair and APPROVED status only."""
    from repositories.mqtt_mapping_repo import MqttMappingRepo

    expected = {
        "id": "map-approved-001",
        "status": "APPROVED",
        "source_device_id": SOURCE_DEVICE_ID,
        "source_metric_id": SOURCE_METRIC_ID,
        "source_metric_name": SOURCE_METRIC_NAME,
        "target_ci_id": TARGET_CI_ID,
        "target_metric_def_id": TARGET_METRIC_DEF_ID,
        "approved_by": APPROVED_BY,
    }
    mock_neo4j_driver.mock_session.set_response(
        "// mqtt-mapping-get-approved",
        [expected],
    )

    repo = MqttMappingRepo(driver=mock_neo4j_driver)
    result = repo.get_approved(
        source_device_id=SOURCE_DEVICE_ID,
        source_metric_id=SOURCE_METRIC_ID,
    )

    assert result is not None
    assert result["id"] == expected["id"]
    assert result["status"] == "APPROVED"

    query = mock_neo4j_driver.mock_session.queries[-1]["query"]
    normalized_query = query.lstrip().lower()
    params = mock_neo4j_driver.mock_session.queries[-1]["params"]
    assert "source_device_id" in normalized_query
    assert "source_metric_id" in normalized_query
    assert params["source_device_id"] == SOURCE_DEVICE_ID
    assert params["source_metric_id"] == SOURCE_METRIC_ID
    assert normalized_query.startswith("// mqtt-mapping-get-approved")


def test_approve_mapping_rejects_conflict(mock_neo4j_driver):
    """approve must reject second APPROVED mapping for same source pair."""
    from repositories.mqtt_mapping_repo import MappingConflictError, MqttMappingRepo

    # Existing mapping under approval.
    mock_neo4j_driver.mock_session.set_response(
        "match (m:mqttmetricmapping) where m.id = $mapping_id",
        [
            {
                "id": "map-001",
                "status": "DRAFT",
                "source_device_id": SOURCE_DEVICE_ID,
                "source_metric_id": SOURCE_METRIC_ID,
                "source_metric_name": SOURCE_METRIC_NAME,
                "target_ci_id": TARGET_CI_ID,
                "target_metric_def_id": TARGET_METRIC_DEF_ID,
                "version": 1,
            },
        ],
    )

    # Target references exist.
    mock_neo4j_driver.mock_session.set_response("match (d:device)", [{"c": 1}])
    mock_neo4j_driver.mock_session.set_response("match (c:ci)", [{"c": 1}])
    mock_neo4j_driver.mock_session.set_response("match (md:metricdef)", [{"c": 1}])

    # Conflict present: atomic approve query sees an existing approved mapping for the pair.
    mock_neo4j_driver.mock_session.set_response(
        "// mqtt-mapping-approve",
        [
            {
                "id": "map-001",
                "source_device_id": SOURCE_DEVICE_ID,
                "source_metric_id": SOURCE_METRIC_ID,
                "status": "DRAFT",
                "version": 1,
                "target_ci_id": TARGET_CI_ID,
                "target_metric_def_id": TARGET_METRIC_DEF_ID,
                "conflict_count": 1,
            },
        ],
    )

    repo = MqttMappingRepo(driver=mock_neo4j_driver)
    with pytest.raises(MappingConflictError):
        repo.approve(mapping_id="map-001", approved_by=APPROVED_BY)

    query = mock_neo4j_driver.mock_session.queries[-1]["query"]
    params = mock_neo4j_driver.mock_session.queries[-1]["params"]
    normalized_query = query.lstrip().lower()
    assert "merge (l:mqttmappingsourcelock)" in normalized_query
    assert "mqtt-mapping-approve" in normalized_query
    assert "optional match (conflict:mqttmetricmapping)" in normalized_query
    assert params["source_key"] == f"{SOURCE_DEVICE_ID}|{SOURCE_METRIC_ID}"


def test_approve_mapping_already_approved_commits_transaction(mock_neo4j_driver):
    """approve should return an already APPROVED mapping and commit tx before return."""
    from repositories.mqtt_mapping_repo import MqttMappingRepo

    mock_neo4j_driver.mock_session.set_response(
        "match (m:mqttmetricmapping) where m.id = $mapping_id",
        [
            {
                "id": "map-003",
                "status": "APPROVED",
                "version": 2,
                "source_device_id": SOURCE_DEVICE_ID,
                "source_metric_id": SOURCE_METRIC_ID,
                "source_metric_name": SOURCE_METRIC_NAME,
                "target_ci_id": TARGET_CI_ID,
                "target_metric_def_id": TARGET_METRIC_DEF_ID,
            },
        ],
    )

    captured: dict[str, object] = {}
    original_begin_transaction = mock_neo4j_driver.mock_session.begin_transaction

    def begin_transaction():
        tx = original_begin_transaction()
        captured["tx"] = tx
        return tx

    mock_neo4j_driver.mock_session.begin_transaction = begin_transaction

    repo = MqttMappingRepo(driver=mock_neo4j_driver)
    result = repo.approve(mapping_id="map-003", approved_by=APPROVED_BY)

    assert result["status"] == "APPROVED"
    assert "tx" in captured
    assert captured["tx"].committed is True
    assert captured["tx"].rolled_back is False


def test_approve_mapping_already_approved_uses_only_read_path(mock_neo4j_driver):
    """approve should not execute update queries when mapping is already APPROVED."""
    from repositories.mqtt_mapping_repo import MqttMappingRepo

    mock_neo4j_driver.mock_session.set_response(
        "match (m:mqttmetricmapping) where m.id = $mapping_id",
        [
            {
                "id": "map-004",
                "status": "APPROVED",
                "version": 3,
                "source_device_id": SOURCE_DEVICE_ID,
                "source_metric_id": SOURCE_METRIC_ID,
                "source_metric_name": SOURCE_METRIC_NAME,
                "target_ci_id": TARGET_CI_ID,
                "target_metric_def_id": TARGET_METRIC_DEF_ID,
            },
        ],
    )

    captured: dict[str, object] = {}
    original_begin_transaction = mock_neo4j_driver.mock_session.begin_transaction

    def begin_transaction():
        tx = original_begin_transaction()
        captured["tx"] = tx
        return tx

    mock_neo4j_driver.mock_session.begin_transaction = begin_transaction

    repo = MqttMappingRepo(driver=mock_neo4j_driver)
    result = repo.approve(mapping_id="map-004", approved_by=APPROVED_BY)

    assert result["status"] == "APPROVED"
    assert len(mock_neo4j_driver.mock_session.queries) == 1
    assert "merge (l:mqttmappingsourcelock)" not in mock_neo4j_driver.mock_session.queries[0]["query"].lower()


def test_approve_mapping_marks_status_and_increments_version(mock_neo4j_driver):
    """approve should move DRAFT mapping to APPROVED and bump version."""
    from repositories.mqtt_mapping_repo import MqttMappingRepo

    mock_neo4j_driver.mock_session.set_response(
        "match (m:mqttmetricmapping) where m.id = $mapping_id",
        [
            {
                "id": "map-002",
                "status": "DRAFT",
                "version": 1,
                "source_device_id": SOURCE_DEVICE_ID,
                "source_metric_id": SOURCE_METRIC_ID,
                "source_metric_name": SOURCE_METRIC_NAME,
                "target_ci_id": TARGET_CI_ID,
                "target_metric_def_id": TARGET_METRIC_DEF_ID,
            },
        ],
    )
    mock_neo4j_driver.mock_session.set_response("match (d:device)", [{"c": 1}])
    mock_neo4j_driver.mock_session.set_response("match (c:ci)", [{"c": 1}])
    mock_neo4j_driver.mock_session.set_response("match (md:metricdef)", [{"c": 1}])
    mock_neo4j_driver.mock_session.set_response(
        "// mqtt-mapping-approve",
        [
            {
                "id": "map-002",
                "source_device_id": SOURCE_DEVICE_ID,
                "source_metric_id": SOURCE_METRIC_ID,
                "status": "APPROVED",
                "version": 2,
                "approved_by": APPROVED_BY,
                "approved_at": datetime(2026, 7, 1, 10, 0, tzinfo=UTC).isoformat().replace("+00:00", "Z"),
                "target_ci_id": TARGET_CI_ID,
                "target_metric_def_id": TARGET_METRIC_DEF_ID,
                "conflict_count": 0,
            },
        ],
    )

    repo = MqttMappingRepo(driver=mock_neo4j_driver)
    result = repo.approve(mapping_id="map-002", approved_by=APPROVED_BY)

    assert result["status"] == "APPROVED"
    assert result["version"] == 2
    assert result["approved_by"] == APPROVED_BY

    query = mock_neo4j_driver.mock_session.queries[-1]["query"]
    params = mock_neo4j_driver.mock_session.queries[-1]["params"]
    normalized_query = query.lstrip().lower()
    assert "mqtt-mapping-approve" in normalized_query
    assert "case" in normalized_query
    assert "conflict_count" in normalized_query
    assert "merge (l:mqttmappingsourcelock)" in normalized_query
    assert params["source_key"] == f"{SOURCE_DEVICE_ID}|{SOURCE_METRIC_ID}"


def test_approve_mapping_rejected_when_already_revoked(mock_neo4j_driver):
    """approve must not resurrect an already REVOKED mapping."""
    from repositories.mqtt_mapping_repo import MappingConflictError, MqttMappingRepo

    mock_neo4j_driver.mock_session.set_response(
        "match (m:mqttmetricmapping) where m.id = $mapping_id",
        [
            {
                "id": "map-004",
                "status": "REVOKED",
                "version": 3,
                "source_device_id": SOURCE_DEVICE_ID,
                "source_metric_id": SOURCE_METRIC_ID,
                "source_metric_name": SOURCE_METRIC_NAME,
                "target_ci_id": TARGET_CI_ID,
                "target_metric_def_id": TARGET_METRIC_DEF_ID,
            }
        ],
    )

    repo = MqttMappingRepo(driver=mock_neo4j_driver)
    with pytest.raises(MappingConflictError):
        repo.approve(mapping_id="map-004", approved_by=APPROVED_BY)

# ── revoke ───────────────────────────────────────────────────────────────────


def test_revoke_mapping_marks_revoked_and_bumps_version(mock_neo4j_driver):
    """revoke should set status REVOKED and increment version atomically."""
    from repositories.mqtt_mapping_repo import MqttMappingRepo

    mock_neo4j_driver.mock_session.set_response(
        "match (m:mqttmetricmapping) where m.id = $mapping_id",
        [
            {
                "id": "map-003",
                "status": "APPROVED",
                "version": 4,
                "source_device_id": SOURCE_DEVICE_ID,
                "source_metric_id": SOURCE_METRIC_ID,
                "source_metric_name": SOURCE_METRIC_NAME,
                "target_ci_id": TARGET_CI_ID,
                "target_metric_def_id": TARGET_METRIC_DEF_ID,
            }
        ],
    )
    mock_neo4j_driver.mock_session.set_response(
        "set m.status = \"REVOKED\"",
        [
            {
                "id": "map-003",
                "status": "REVOKED",
                "version": 5,
                "revoked_by": "ops-77",
            }
        ],
    )

    repo = MqttMappingRepo(driver=mock_neo4j_driver)
    result = repo.revoke(mapping_id="map-003", revoked_by="ops-77")

    assert result["status"] == "REVOKED"
    assert result["version"] == 5
    assert result["revoked_by"] == "ops-77"

    query = mock_neo4j_driver.mock_session.queries[-1]["query"]
    normalized_query = query.lstrip().lower()
    params = mock_neo4j_driver.mock_session.queries[-1]["params"]
    assert "set m.status" in normalized_query
    assert params["mapping_id"] == "map-003"
    assert params["revoked_by"] == "ops-77"
