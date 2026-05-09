"""
Integration-level tests for dictionary CRUD endpoints.
Uses FastAPI TestClient with mocked auth and database.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

# Use conftest.py stubs — import app normally
from main import app
from services.auth_service import get_current_active_user
from models.user import User, UserPermission


client = TestClient(app)


def _admin_user():
    return User(
        username="admin",
        role="ADMIN",
        permissions=[UserPermission.CI_EDIT],
        allowed_locations=[],
    )


def _viewer_user():
    return User(
        username="viewer",
        role="VIEWER",
        permissions=[],
        allowed_locations=[],
    )


# ---------------------------------------------------------------------------
# Tests: GET /api/dictionaries
# ---------------------------------------------------------------------------

class TestGetDictionaries:
    """Tests for GET /api/dictionaries endpoint."""

    def test_list_dictionaries_unauthenticated(self):
        """No auth token should return 401."""
        response = client.get("/api/dictionaries")
        assert response.status_code == 401

    def test_list_dictionaries_authenticated_success(self):
        """Admin should get list of dictionaries."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.dictionaries.dictionary_service") as mock_svc:
            mock_svc.list_dictionaries.return_value = [
                {
                    "id": "dict-1",
                    "name": "Cisco 2960 Template",
                    "brand": "Cisco",
                    "model": "Catalyst-2960",
                    "metric_ids": ["cpu-load"],
                    "polling_interval": 60,
                }
            ]

            response = client.get("/api/dictionaries")

            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            assert len(data) == 1
            assert data[0]["id"] == "dict-1"
            assert data[0]["brand"] == "Cisco"

        app.dependency_overrides.pop(get_current_active_user, None)


# ---------------------------------------------------------------------------
# Tests: POST /api/dictionaries
# ---------------------------------------------------------------------------

class TestCreateDictionary:
    """Tests for POST /api/dictionaries endpoint."""

    def test_create_dictionary_unauthenticated(self):
        """No auth token should return 401."""
        response = client.post("/api/dictionaries", json={
            "id": "test-dict",
            "name": "Test Dictionary",
            "brand": "Cisco",
            "model": "Catalyst-2960",
            "metric_ids": [],
        })
        assert response.status_code == 401

    def test_create_dictionary_no_permission(self):
        """User without CI_EDIT should get 403."""
        async def override():
            return _viewer_user()
        app.dependency_overrides[get_current_active_user] = override

        response = client.post("/api/dictionaries", json={
            "id": "test-dict",
            "name": "Test Dictionary",
            "brand": "Cisco",
            "model": "Catalyst-2960",
            "metric_ids": [],
        })

        assert response.status_code == 403
        app.dependency_overrides.pop(get_current_active_user, None)

    def test_create_dictionary_success(self):
        """Admin should be able to create a dictionary."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.dictionaries.dictionary_service") as mock_svc:
            mock_svc.validate_metric_ids.return_value = (True, [])
            mock_svc.create_dictionary.return_value = {
                "id": "test-dict",
                "name": "Test Dictionary",
                "brand": "Cisco",
                "model": "Catalyst-2960",
                "metric_ids": [],
                "polling_interval": 60,
            }

            response = client.post("/api/dictionaries", json={
                "id": "test-dict",
                "name": "Test Dictionary",
                "brand": "Cisco",
                "model": "Catalyst-2960",
                "metric_ids": [],
            })

            assert response.status_code == 201
            data = response.json()
            assert data["message"] == "Dictionary created"
            assert data["id"] == "test-dict"

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_create_dictionary_duplicate_brand_model_returns_409(self):
        """Duplicate brand+model should return 409 Conflict."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.dictionaries.dictionary_service") as mock_svc:
            mock_svc.validate_metric_ids.return_value = (True, [])
            mock_svc.create_dictionary.side_effect = ValueError(
                "Dictionary with brand='Cisco' and model='Catalyst-2960' already exists"
            )

            response = client.post("/api/dictionaries", json={
                "id": "test-dict-2",
                "name": "Test Dictionary 2",
                "brand": "Cisco",
                "model": "Catalyst-2960",
                "metric_ids": [],
            })

            assert response.status_code == 409
            assert "already exists" in response.json()["detail"]

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_create_dictionary_invalid_metric_ids_returns_422(self):
        """Non-existent metric_ids should return 422."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.dictionaries.dictionary_service") as mock_svc:
            mock_svc.validate_metric_ids.return_value = (False, ["non-existent-metric"])

            response = client.post("/api/dictionaries", json={
                "id": "test-dict",
                "name": "Test Dictionary",
                "brand": "Cisco",
                "model": "Catalyst-2960",
                "metric_ids": ["non-existent-metric"],
            })

            assert response.status_code == 422
            assert "Invalid metric_ids" in response.json()["detail"]

        app.dependency_overrides.pop(get_current_active_user, None)


# ---------------------------------------------------------------------------
# Tests: GET /api/dictionaries/{id}
# ---------------------------------------------------------------------------

class TestGetDictionary:
    """Tests for GET /api/dictionaries/{dictionary_id} endpoint."""

    def test_get_dictionary_not_found(self):
        """Non-existent dictionary should return 404."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.dictionaries.dictionary_service") as mock_svc:
            mock_svc.get_dictionary.return_value = None

            response = client.get("/api/dictionaries/non-existent-id")

            assert response.status_code == 404

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_get_dictionary_success(self):
        """Should return dictionary with metric_ids."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.dictionaries.dictionary_service") as mock_svc:
            mock_svc.get_dictionary.return_value = {
                "id": "dict-1",
                "name": "Cisco 2960",
                "brand": "Cisco",
                "model": "Catalyst-2960",
                "metric_ids": ["cpu-load", "mem-used"],
                "polling_interval": 60,
            }

            response = client.get("/api/dictionaries/dict-1")

            assert response.status_code == 200
            data = response.json()
            assert data["id"] == "dict-1"
            assert data["metric_ids"] == ["cpu-load", "mem-used"]

        app.dependency_overrides.pop(get_current_active_user, None)


# ---------------------------------------------------------------------------
# Tests: PUT /api/dictionaries/{id}
# ---------------------------------------------------------------------------

class TestUpdateDictionary:
    """Tests for PUT /api/dictionaries/{dictionary_id} endpoint."""

    def test_update_dictionary_not_found(self):
        """Non-existent dictionary should return 404."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.dictionaries.dictionary_service") as mock_svc:
            mock_svc.get_dictionary.return_value = None

            response = client.put("/api/dictionaries/non-existent-id", json={
                "name": "New Name",
            })

            assert response.status_code == 404

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_update_dictionary_success(self):
        """Admin should be able to update a dictionary."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.dictionaries.dictionary_service") as mock_svc:
            mock_svc.get_dictionary.return_value = {
                "id": "dict-1",
                "name": "Old Name",
                "brand": "Cisco",
                "model": "Catalyst-2960",
                "metric_ids": [],
                "polling_interval": 60,
            }
            mock_svc.update_dictionary.return_value = {
                "id": "dict-1",
                "name": "New Name",
                "brand": "Cisco",
                "model": "Catalyst-2960",
                "metric_ids": [],
                "polling_interval": 60,
            }

            response = client.put("/api/dictionaries/dict-1", json={
                "name": "New Name",
            })

            assert response.status_code == 200
            assert response.json()["message"] == "Dictionary updated"

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_update_dictionary_brand_model_conflict_returns_409(self):
        """Brand+model conflict should return 409."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.dictionaries.dictionary_service") as mock_svc:
            mock_svc.get_dictionary.return_value = {
                "id": "dict-1",
                "name": "Dict 1",
                "brand": "Cisco",
                "model": "Catalyst-2960",
                "metric_ids": [],
                "polling_interval": 60,
            }
            mock_svc.update_dictionary.side_effect = ValueError(
                "Another dictionary with brand='Dell' and model='N3048' already exists"
            )

            response = client.put("/api/dictionaries/dict-1", json={
                "brand": "Dell",
                "model": "N3048",
            })

            assert response.status_code == 409
            assert "already exists" in response.json()["detail"]

        app.dependency_overrides.pop(get_current_active_user, None)


# ---------------------------------------------------------------------------
# Tests: DELETE /api/dictionaries/{id}
# ---------------------------------------------------------------------------

class TestDeleteDictionary:
    """Tests for DELETE /api/dictionaries/{dictionary_id} endpoint."""

    def test_delete_dictionary_not_found(self):
        """Non-existent dictionary should return 404."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.dictionaries.dictionary_service") as mock_svc:
            mock_svc.delete_dictionary.return_value = False

            response = client.delete("/api/dictionaries/non-existent-id")

            assert response.status_code == 404

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_delete_dictionary_success(self):
        """Admin should be able to delete a dictionary."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.dictionaries.dictionary_service") as mock_svc:
            mock_svc.delete_dictionary.return_value = True

            response = client.delete("/api/dictionaries/dict-1")

            assert response.status_code == 200
            assert response.json()["message"] == "Dictionary deleted"

        app.dependency_overrides.pop(get_current_active_user, None)


# ---------------------------------------------------------------------------
# Tests: GET /api/dictionaries/{id}/target-cis
# ---------------------------------------------------------------------------

class TestGetTargetCIs:
    """Tests for GET /api/dictionaries/{dictionary_id}/target-cis endpoint."""

    def test_target_cis_unauthenticated(self):
        """No auth token should return 401."""
        response = client.get("/api/dictionaries/dict-1/target-cis")
        assert response.status_code == 401

    def test_target_cis_not_found(self):
        """Non-existent dictionary should return 404."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.dictionaries.dictionary_service") as mock_svc:
            mock_svc.get_target_cis.side_effect = ValueError("Dictionary 'missing' not found")

            response = client.get("/api/dictionaries/missing/target-cis")

            assert response.status_code == 404

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_target_cis_success(self):
        """Should return CIs matching dictionary brand+model."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.dictionaries.dictionary_service") as mock_svc:
            mock_svc.get_target_cis.return_value = [
                {
                    "id": "ci-1",
                    "name": "Switch-A",
                    "ip": "10.0.0.1",
                    "brand": "Cisco",
                    "model": "Catalyst-2960",
                    "location_name": "DC-1",
                },
                {
                    "id": "ci-2",
                    "name": "Switch-B",
                    "ip": "10.0.0.2",
                    "brand": "Cisco",
                    "model": "Catalyst-2960",
                    "location_name": "DC-2",
                },
            ]

            response = client.get("/api/dictionaries/dict-1/target-cis")

            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            assert len(data) == 2
            assert data[0]["id"] == "ci-1"
            assert data[0]["brand"] == "Cisco"
            assert data[0]["model"] == "Catalyst-2960"

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_target_cis_empty(self):
        """Should return empty list when no CIs match."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.dictionaries.dictionary_service") as mock_svc:
            mock_svc.get_target_cis.return_value = []

            response = client.get("/api/dictionaries/dict-1/target-cis")

            assert response.status_code == 200
            assert response.json() == []

        app.dependency_overrides.pop(get_current_active_user, None)


# ---------------------------------------------------------------------------
# Tests: POST /api/dictionaries/{id}/apply
# ---------------------------------------------------------------------------

class TestApplyDictionary:
    """Tests for POST /api/dictionaries/{dictionary_id}/apply endpoint."""

    def test_apply_unauthenticated(self):
        """No auth token should return 401."""
        response = client.post("/api/dictionaries/dict-1/apply", json={"ci_ids": ["ci-1"]})
        assert response.status_code == 401

    def test_apply_no_permission(self):
        """User without CI_EDIT should get 403."""
        async def override():
            return _viewer_user()
        app.dependency_overrides[get_current_active_user] = override

        response = client.post("/api/dictionaries/dict-1/apply", json={"ci_ids": ["ci-1"]})

        assert response.status_code == 403
        app.dependency_overrides.pop(get_current_active_user, None)

    def test_apply_not_found(self):
        """Non-existent dictionary should return 404."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.dictionaries.dictionary_service") as mock_svc:
            mock_svc.apply_dictionary.side_effect = ValueError("Dictionary 'missing' not found")

            response = client.post("/api/dictionaries/missing/apply", json={"ci_ids": ["ci-1"]})

            assert response.status_code == 404

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_apply_success(self):
        """Should apply dictionary to specified CIs."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.dictionaries.dictionary_service") as mock_svc:
            mock_svc.apply_dictionary.return_value = {
                "applied_count": 2,
                "skipped_count": 0,
                "message": "Applied to 2 CIs, skipped 0",
            }

            response = client.post("/api/dictionaries/dict-1/apply", json={
                "ci_ids": ["ci-1", "ci-2"],
            })

            assert response.status_code == 200
            data = response.json()
            assert data["applied_count"] == 2
            assert data["skipped_count"] == 0
            assert "Applied to 2 CIs" in data["message"]

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_apply_with_skipped(self):
        """Should report skipped CIs when some have no IP or don't exist."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.dictionaries.dictionary_service") as mock_svc:
            mock_svc.apply_dictionary.return_value = {
                "applied_count": 1,
                "skipped_count": 2,
                "message": "Applied to 1 CIs, skipped 2",
            }

            response = client.post("/api/dictionaries/dict-1/apply", json={
                "ci_ids": ["ci-1", "missing-ci", "ci-no-ip"],
            })

            assert response.status_code == 200
            data = response.json()
            assert data["applied_count"] == 1
            assert data["skipped_count"] == 2

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_apply_dry_run(self):
        """dry_run=true should return count without persisting."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.dictionaries.dictionary_service") as mock_svc:
            mock_svc.apply_dictionary.return_value = {
                "applied_count": 5,
                "skipped_count": 0,
                "message": "Applied to 5 CIs, skipped 0",
            }

            response = client.post("/api/dictionaries/dict-1/apply", json={
                "ci_ids": ["ci-1", "ci-2"],
                "dry_run": True,
            })

            assert response.status_code == 200
            data = response.json()
            assert data["applied_count"] == 5

        app.dependency_overrides.pop(get_current_active_user, None)


# ---------------------------------------------------------------------------
# Tests: POST /api/dictionaries/{id}/preview
# ---------------------------------------------------------------------------

class TestPreviewDictionary:
    """Tests for POST /api/dictionaries/{dictionary_id}/preview endpoint."""

    def test_preview_unauthenticated(self):
        """No auth token should return 401."""
        response = client.post("/api/dictionaries/dict-1/preview", json={"ci_ids": ["ci-1"]})
        assert response.status_code == 401

    def test_preview_not_found(self):
        """Non-existent dictionary should return 404."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.dictionaries.dictionary_service") as mock_svc:
            mock_svc.preview_dictionary = AsyncMock(
                side_effect=ValueError("Dictionary 'missing' not found")
            )

            response = client.post("/api/dictionaries/missing/preview", json={"ci_ids": ["ci-1"]})

            assert response.status_code == 404

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_preview_success(self):
        """Should return live SNMP preview readings per CI."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.dictionaries.dictionary_service") as mock_svc:
            mock_svc.preview_dictionary = AsyncMock(return_value=[
                {
                    "ci_id": "ci-1",
                    "ci_name": "Switch-A",
                    "ip": "10.0.0.1",
                    "results": [
                        {"metric_id": "cpu-load", "oid": "1.3.6.1.4.1.9.2.1.58.0", "value": "45", "status": "OK"},
                        {"metric_id": "mem-used", "oid": "1.3.6.1.4.1.9.2.1.59.0", "value": "80", "status": "WARNING"},
                    ],
                },
                {
                    "ci_id": "ci-2",
                    "ci_name": "Switch-B",
                    "ip": "10.0.0.2",
                    "results": [
                        {"metric_id": "cpu-load", "oid": "1.3.6.1.4.1.9.2.1.58.0", "value": None, "status": "NO_DATA"},
                        {"metric_id": "mem-used", "oid": "1.3.6.1.4.1.9.2.1.59.0", "value": None, "status": "NO_DATA"},
                    ],
                },
            ])

            response = client.post("/api/dictionaries/dict-1/preview", json={
                "ci_ids": ["ci-1", "ci-2"],
            })

            assert response.status_code == 200
            data = response.json()
            assert "previews" in data
            assert len(data["previews"]) == 2
            assert data["previews"][0]["ci_id"] == "ci-1"
            assert data["previews"][0]["results"][0]["status"] == "OK"
            assert data["previews"][1]["results"][0]["status"] == "NO_DATA"

        app.dependency_overrides.pop(get_current_active_user, None)


# ---------------------------------------------------------------------------
# Tests: GET /api/cis/{ci_id}/applied-dictionary
# ---------------------------------------------------------------------------

class TestGetAppliedDictionary:
    """Tests for GET /api/cis/{ci_id}/applied-dictionary endpoint."""

    def test_get_applied_dictionary_unauthenticated(self):
        """No auth token should return 401."""
        response = client.get("/api/cis/ci-1/applied-dictionary")
        assert response.status_code == 401

    def test_get_applied_dictionary_not_found(self):
        """CI with no applied dictionary should return 404."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.cis.dictionary_service") as mock_svc:
            mock_svc.get_applied_dictionary.return_value = None

            response = client.get("/api/cis/ci-no-dict/applied-dictionary")

            assert response.status_code == 404
            assert "No dictionary applied" in response.json()["detail"]

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_get_applied_dictionary_success(self):
        """Should return applied dictionary with exclusions/extras."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.cis.dictionary_service") as mock_svc:
            mock_svc.get_applied_dictionary.return_value = {
                "dictionary_id": "dict-1",
                "dictionary_name": "Cisco 2960 Template",
                "dictionary_brand": "Cisco",
                "dictionary_model": "Catalyst-2960",
                "dictionary_metric_ids": ["cpu-load", "mem-used"],
                "excluded_metrics": ["cpu-load"],
                "extra_metrics": ["custom-metric"],
                "applied_at": "2026-05-09T12:00:00",
            }

            response = client.get("/api/cis/ci-1/applied-dictionary")

            assert response.status_code == 200
            data = response.json()
            assert data["dictionary_id"] == "dict-1"
            assert data["excluded_metrics"] == ["cpu-load"]
            assert data["extra_metrics"] == ["custom-metric"]

        app.dependency_overrides.pop(get_current_active_user, None)


# ---------------------------------------------------------------------------
# Tests: PUT /api/cis/{ci_id}/dictionary-exclusions
# ---------------------------------------------------------------------------

class TestUpdateDictionaryExclusions:
    """Tests for PUT /api/cis/{ci_id}/dictionary-exclusions endpoint."""

    def test_update_exclusions_unauthenticated(self):
        """No auth token should return 401."""
        response = client.put(
            "/api/cis/ci-1/dictionary-exclusions",
            json={"excluded_metrics": ["cpu-load"]},
        )
        assert response.status_code == 401

    def test_update_exclusions_no_permission(self):
        """User without CI_EDIT should get 403."""
        async def override():
            return _viewer_user()
        app.dependency_overrides[get_current_active_user] = override

        response = client.put(
            "/api/cis/ci-1/dictionary-exclusions",
            json={"excluded_metrics": ["cpu-load"]},
        )

        assert response.status_code == 403
        app.dependency_overrides.pop(get_current_active_user, None)

    def test_update_exclusions_not_found(self):
        """CI with no applied dictionary should return 404."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.cis.dictionary_service") as mock_svc:
            mock_svc.update_ci_exclusions.side_effect = ValueError(
                "No AppliedDictionary found for CI 'ci-no-dict'"
            )

            response = client.put(
                "/api/cis/ci-no-dict/dictionary-exclusions",
                json={"excluded_metrics": ["cpu-load"]},
            )

            assert response.status_code == 404
            assert "No AppliedDictionary found" in response.json()["detail"]

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_update_exclusions_success(self):
        """Should update excluded_metrics and extra_metrics."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.cis.dictionary_service") as mock_svc:
            mock_svc.update_ci_exclusions.return_value = {
                "dictionary_id": "dict-1",
                "dictionary_name": "Cisco 2960 Template",
                "dictionary_brand": "Cisco",
                "dictionary_model": "Catalyst-2960",
                "dictionary_metric_ids": ["cpu-load", "mem-used"],
                "excluded_metrics": ["cpu-load"],
                "extra_metrics": ["custom-metric"],
                "applied_at": "2026-05-09T12:00:00",
            }

            response = client.put(
                "/api/cis/ci-1/dictionary-exclusions",
                json={
                    "excluded_metrics": ["cpu-load"],
                    "extra_metrics": ["custom-metric"],
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["excluded_metrics"] == ["cpu-load"]
            assert data["extra_metrics"] == ["custom-metric"]

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_update_exclusions_invalid_extra_metric_ids_returns_422(self):
        """Non-existent extra_metric_ids should return 422."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.cis.dictionary_service") as mock_svc:
            mock_svc.update_ci_exclusions.side_effect = ValueError(
                "Invalid extra_metric_ids: ['non-existent-metric']"
            )

            response = client.put(
                "/api/cis/ci-1/dictionary-exclusions",
                json={"extra_metrics": ["non-existent-metric"]},
            )

            assert response.status_code == 422
            assert "Invalid extra_metric_ids" in response.json()["detail"]

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_update_exclusions_replace_not_merge(self):
        """Calling PUT replaces arrays, not merges."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.cis.dictionary_service") as mock_svc:
            mock_svc.update_ci_exclusions.return_value = {
                "dictionary_id": "dict-1",
                "dictionary_name": "Cisco 2960 Template",
                "dictionary_brand": "Cisco",
                "dictionary_model": "Catalyst-2960",
                "dictionary_metric_ids": ["cpu-load", "mem-used"],
                "excluded_metrics": ["mem-used"],
                "extra_metrics": [],
                "applied_at": "2026-05-09T12:00:00",
            }

            response = client.put(
                "/api/cis/ci-1/dictionary-exclusions",
                json={"excluded_metrics": ["mem-used"]},  # no extra_metrics
            )

            assert response.status_code == 200
            data = response.json()
            # excluded_metrics is REPLACED with only "mem-used", extra_metrics becomes []
            assert data["excluded_metrics"] == ["mem-used"]
            assert data["extra_metrics"] == []

        app.dependency_overrides.pop(get_current_active_user, None)


# ---------------------------------------------------------------------------
# Tests: DELETE /api/cis/{ci_id}/applied-dictionary
# ---------------------------------------------------------------------------

class TestRemoveAppliedDictionary:
    """Tests for DELETE /api/cis/{ci_id}/applied-dictionary endpoint."""

    def test_remove_applied_dictionary_unauthenticated(self):
        """No auth token should return 401."""
        response = client.delete("/api/cis/ci-1/applied-dictionary")
        assert response.status_code == 401

    def test_remove_applied_dictionary_no_permission(self):
        """User without CI_EDIT should get 403."""
        async def override():
            return _viewer_user()
        app.dependency_overrides[get_current_active_user] = override

        response = client.delete("/api/cis/ci-1/applied-dictionary")

        assert response.status_code == 403
        app.dependency_overrides.pop(get_current_active_user, None)

    def test_remove_applied_dictionary_not_found(self):
        """CI with no applied dictionary should return 404."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.cis.dictionary_service") as mock_svc:
            mock_svc.remove_applied_dictionary.return_value = False

            response = client.delete("/api/cis/ci-no-dict/applied-dictionary")

            assert response.status_code == 404
            assert "No dictionary applied" in response.json()["detail"]

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_remove_applied_dictionary_success(self):
        """Should remove AppliedDictionary from CI."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.cis.dictionary_service") as mock_svc:
            mock_svc.remove_applied_dictionary.return_value = True

            response = client.delete("/api/cis/ci-1/applied-dictionary")

            assert response.status_code == 200
            assert response.json()["message"] == "Dictionary removed from CI"

        app.dependency_overrides.pop(get_current_active_user, None)


# ---------------------------------------------------------------------------
# Tests: GET /api/cis/{ci_id}/applied-dictionary
# ---------------------------------------------------------------------------

class TestGetAppliedDictionary:
    """Tests for GET /api/cis/{ci_id}/applied-dictionary endpoint."""

    def test_get_applied_dictionary_unauthenticated(self):
        """No auth token should return 401."""
        response = client.get("/api/cis/ci-1/applied-dictionary")
        assert response.status_code == 401

    def test_get_applied_dictionary_not_found(self):
        """CI with no applied dictionary should return 404."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.dictionaries.dictionary_service") as mock_svc:
            mock_svc.get_applied_dictionary.return_value = None

            response = client.get("/api/cis/ci-no-dict/applied-dictionary")

            assert response.status_code == 404
            assert "No dictionary applied" in response.json()["detail"]

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_get_applied_dictionary_success(self):
        """Should return applied dictionary with exclusions/extras."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.dictionaries.dictionary_service") as mock_svc:
            mock_svc.get_applied_dictionary.return_value = {
                "dictionary_id": "dict-1",
                "dictionary_name": "Cisco 2960 Template",
                "dictionary_brand": "Cisco",
                "dictionary_model": "Catalyst-2960",
                "dictionary_metric_ids": ["cpu-load", "mem-used"],
                "excluded_metrics": ["cpu-load"],
                "extra_metrics": ["custom-metric"],
                "applied_at": "2026-05-09T12:00:00",
            }

            response = client.get("/api/cis/ci-1/applied-dictionary")

            assert response.status_code == 200
            data = response.json()
            assert data["dictionary_id"] == "dict-1"
            assert data["excluded_metrics"] == ["cpu-load"]
            assert data["extra_metrics"] == ["custom-metric"]

        app.dependency_overrides.pop(get_current_active_user, None)


# ---------------------------------------------------------------------------
# Tests: PUT /api/cis/{ci_id}/dictionary-exclusions
# ---------------------------------------------------------------------------

class TestUpdateDictionaryExclusions:
    """Tests for PUT /api/cis/{ci_id}/dictionary-exclusions endpoint."""

    def test_update_exclusions_unauthenticated(self):
        """No auth token should return 401."""
        response = client.put(
            "/api/cis/ci-1/dictionary-exclusions",
            json={"excluded_metrics": ["cpu-load"]},
        )
        assert response.status_code == 401

    def test_update_exclusions_no_permission(self):
        """User without CI_EDIT should get 403."""
        async def override():
            return _viewer_user()
        app.dependency_overrides[get_current_active_user] = override

        response = client.put(
            "/api/cis/ci-1/dictionary-exclusions",
            json={"excluded_metrics": ["cpu-load"]},
        )

        assert response.status_code == 403
        app.dependency_overrides.pop(get_current_active_user, None)

    def test_update_exclusions_not_found(self):
        """CI with no applied dictionary should return 404."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.dictionaries.dictionary_service") as mock_svc:
            mock_svc.update_ci_exclusions.side_effect = ValueError(
                "No AppliedDictionary found for CI 'ci-no-dict'"
            )

            response = client.put(
                "/api/cis/ci-no-dict/dictionary-exclusions",
                json={"excluded_metrics": ["cpu-load"]},
            )

            assert response.status_code == 404
            assert "No AppliedDictionary found" in response.json()["detail"]

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_update_exclusions_success(self):
        """Should update excluded_metrics and extra_metrics."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.dictionaries.dictionary_service") as mock_svc:
            mock_svc.update_ci_exclusions.return_value = {
                "dictionary_id": "dict-1",
                "dictionary_name": "Cisco 2960 Template",
                "dictionary_brand": "Cisco",
                "dictionary_model": "Catalyst-2960",
                "dictionary_metric_ids": ["cpu-load", "mem-used"],
                "excluded_metrics": ["cpu-load"],
                "extra_metrics": ["custom-metric"],
                "applied_at": "2026-05-09T12:00:00",
            }

            response = client.put(
                "/api/cis/ci-1/dictionary-exclusions",
                json={
                    "excluded_metrics": ["cpu-load"],
                    "extra_metrics": ["custom-metric"],
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["excluded_metrics"] == ["cpu-load"]
            assert data["extra_metrics"] == ["custom-metric"]

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_update_exclusions_invalid_extra_metric_ids_returns_422(self):
        """Non-existent extra_metric_ids should return 422."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.dictionaries.dictionary_service") as mock_svc:
            mock_svc.update_ci_exclusions.side_effect = ValueError(
                "Invalid extra_metric_ids: ['non-existent-metric']"
            )

            response = client.put(
                "/api/cis/ci-1/dictionary-exclusions",
                json={"extra_metrics": ["non-existent-metric"]},
            )

            assert response.status_code == 422
            assert "Invalid extra_metric_ids" in response.json()["detail"]

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_update_exclusions_replace_not_merge(self):
        """Calling PUT replaces arrays, not merges."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.dictionaries.dictionary_service") as mock_svc:
            mock_svc.update_ci_exclusions.return_value = {
                "dictionary_id": "dict-1",
                "dictionary_name": "Cisco 2960 Template",
                "dictionary_brand": "Cisco",
                "dictionary_model": "Catalyst-2960",
                "dictionary_metric_ids": ["cpu-load", "mem-used"],
                "excluded_metrics": ["mem-used"],
                "extra_metrics": [],
                "applied_at": "2026-05-09T12:00:00",
            }

            response = client.put(
                "/api/cis/ci-1/dictionary-exclusions",
                json={"excluded_metrics": ["mem-used"]},  # no extra_metrics
            )

            assert response.status_code == 200
            data = response.json()
            # excluded_metrics is REPLACED with only "mem-used", extra_metrics becomes []
            assert data["excluded_metrics"] == ["mem-used"]
            assert data["extra_metrics"] == []

        app.dependency_overrides.pop(get_current_active_user, None)


# ---------------------------------------------------------------------------
# Tests: DELETE /api/cis/{ci_id}/applied-dictionary
# ---------------------------------------------------------------------------

class TestRemoveAppliedDictionary:
    """Tests for DELETE /api/cis/{ci_id}/applied-dictionary endpoint."""

    def test_remove_applied_dictionary_unauthenticated(self):
        """No auth token should return 401."""
        response = client.delete("/api/cis/ci-1/applied-dictionary")
        assert response.status_code == 401

    def test_remove_applied_dictionary_no_permission(self):
        """User without CI_EDIT should get 403."""
        async def override():
            return _viewer_user()
        app.dependency_overrides[get_current_active_user] = override

        response = client.delete("/api/cis/ci-1/applied-dictionary")

        assert response.status_code == 403
        app.dependency_overrides.pop(get_current_active_user, None)

    def test_remove_applied_dictionary_not_found(self):
        """CI with no applied dictionary should return 404."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.dictionaries.dictionary_service") as mock_svc:
            mock_svc.remove_applied_dictionary.return_value = False

            response = client.delete("/api/cis/ci-no-dict/applied-dictionary")

            assert response.status_code == 404
            assert "No dictionary applied" in response.json()["detail"]

        app.dependency_overrides.pop(get_current_active_user, None)

    def test_remove_applied_dictionary_success(self):
        """Should remove AppliedDictionary from CI."""
        async def override():
            return _admin_user()
        app.dependency_overrides[get_current_active_user] = override

        with patch("routers.dictionaries.dictionary_service") as mock_svc:
            mock_svc.remove_applied_dictionary.return_value = True

            response = client.delete("/api/cis/ci-1/applied-dictionary")

            assert response.status_code == 200
            assert response.json()["message"] == "Dictionary removed from CI"

        app.dependency_overrides.pop(get_current_active_user, None)