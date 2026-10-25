"""HTTP contract tests for the managed MetricDictionary surface (feature #480).

Contract under test (S2/S5):

- ``GET /api/dictionaries?key=value_stream|tier|criticality&active=true``
  returns ``[{value, label}]`` — the dropdown source for the ITIL-aligned
  Service Catalog form.
- ``GET /api/dictionaries`` without a ``key`` keeps the legacy dictionary-list
  contract used by the CMDB dictionary manager.
- Managed MetricDictionary rows (``dictionary_key`` set: ``value_stream``,
  ``tier``, ``criticality``) must never surface in the legacy list as
  null-shaped records.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from models.user import User
from routers import dictionaries
from services.auth_service import get_current_active_user

app = FastAPI()
app.include_router(dictionaries.router, prefix="/api")
client = TestClient(app)


def _viewer_user() -> User:
    return User(
        username="viewer",
        role="OPERATOR",
        permissions=[],
        allowed_locations=[],
    )


def _override_current_user(user: User) -> None:
    async def _override():
        return user

    app.dependency_overrides[get_current_active_user] = _override


@pytest.fixture(autouse=True)
def _clear_overrides():
    original = dict(app.dependency_overrides)
    yield
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original)


class TestManagedDictionaryRootContract:
    """``GET /api/dictionaries?key=...&active=...`` returns ``{value, label}[]``."""

    def test_requires_authentication(self):
        response = client.get("/api/dictionaries", params={"key": "value_stream"})
        assert response.status_code == 401

    @pytest.mark.parametrize(
        ("key", "expected"),
        [
            (
                "value_stream",
                [
                    {"value": "operate", "label": "Operate"},
                    {"value": "deliver", "label": "Deliver"},
                ],
            ),
            (
                "tier",
                [
                    {"value": "bronze", "label": "Bronze"},
                    {"value": "silver", "label": "Silver"},
                    {"value": "gold", "label": "Gold"},
                    {"value": "platinum", "label": "Platinum"},
                ],
            ),
            (
                "criticality",
                [
                    {"value": "low", "label": "Low"},
                    {"value": "medium", "label": "Medium"},
                    {"value": "high", "label": "High"},
                    {"value": "critical", "label": "Critical"},
                ],
            ),
        ],
    )
    def test_returns_value_label_pairs_for_managed_keys(self, key, expected):
        _override_current_user(_viewer_user())

        with patch(
            "services.dictionary_service.list_dictionary_values",
            return_value=expected,
        ) as lookup:
            response = client.get("/api/dictionaries", params={"key": key, "active": "true"})

        assert response.status_code == 200
        assert response.json() == expected
        lookup.assert_called_once_with(key, active=True)

    def test_forwards_the_active_filter(self):
        _override_current_user(_viewer_user())

        with patch(
            "services.dictionary_service.list_dictionary_values",
            return_value=[],
        ) as lookup:
            response = client.get("/api/dictionaries", params={"key": "tier", "active": "false"})

        assert response.status_code == 200
        assert response.json() == []
        lookup.assert_called_once_with("tier", active=False)

    def test_key_filtered_call_does_not_use_the_legacy_list(self):
        _override_current_user(_viewer_user())

        with (
            patch("services.dictionary_service.list_dictionaries") as legacy,
            patch("services.dictionary_service.list_dictionary_values", return_value=[]),
        ):
            response = client.get("/api/dictionaries", params={"key": "value_stream"})

        assert response.status_code == 200
        legacy.assert_not_called()

    def test_values_alias_matches_the_root_contract(self):
        """``/api/dictionaries/values`` stays as a compatibility alias."""
        _override_current_user(_viewer_user())

        with patch(
            "services.dictionary_service.list_dictionary_values",
            return_value=[{"value": "operate", "label": "Operate"}],
        ):
            root = client.get("/api/dictionaries", params={"key": "value_stream"})
            alias = client.get("/api/dictionaries/values", params={"key": "value_stream"})

        assert root.status_code == 200
        assert alias.status_code == 200
        assert alias.json() == root.json()


class TestLegacyDictionaryListIsPreserved:
    """``GET /api/dictionaries`` (no key) keeps the legacy contract."""

    def test_legacy_payload_shape_is_unchanged(self):
        _override_current_user(_viewer_user())

        legacy_payload = [
            {
                "id": "dict-1",
                "name": "Cisco 2960 Template",
                "brand": "Cisco",
                "model": "Catalyst-2960",
                "metric_ids": ["cpu-load"],
                "polling_interval": 60,
            }
        ]

        with patch("services.dictionary_service.list_dictionaries", return_value=legacy_payload):
            response = client.get("/api/dictionaries")

        assert response.status_code == 200
        assert response.json() == legacy_payload


class TestLegacyListExcludesManagedRows:
    """Managed MetricDictionary rows must not appear as null-shaped records."""

    def test_managed_rows_are_filtered_out_of_the_legacy_list(self, mock_neo4j_driver):
        from services import dictionary_service

        mock_session = mock_neo4j_driver.mock_session
        mock_session.set_response(
            "match (md:metricdictionary)",
            [
                {
                    "id": "dict-1",
                    "name": "Cisco 2960 Template",
                    "brand": "Cisco",
                    "model": "Catalyst-2960",
                    "polling_interval": 60,
                    "created_at": "2026-01-01T00:00:00",
                    "updated_at": "2026-01-01T00:00:00",
                    "dictionary_key": None,
                },
                {
                    "id": None,
                    "name": None,
                    "brand": None,
                    "model": None,
                    "polling_interval": None,
                    "created_at": None,
                    "updated_at": None,
                    "dictionary_key": "value_stream",
                },
                {
                    "id": None,
                    "name": None,
                    "brand": None,
                    "model": None,
                    "polling_interval": None,
                    "created_at": None,
                    "updated_at": None,
                    "dictionary_key": "tier",
                },
            ],
        )
        mock_session.set_response("has_metric", [])

        with patch("services.dictionary_service.get_db", return_value=mock_neo4j_driver):
            result = dictionary_service.list_dictionaries()

        assert [row["id"] for row in result] == ["dict-1"]
        assert all(row.get("dictionary_key") is None for row in result)

    def test_legacy_query_excludes_managed_rows_in_cypher(self, mock_neo4j_driver):
        from services import dictionary_service

        mock_session = mock_neo4j_driver.mock_session
        mock_session.set_default_response([])

        with patch("services.dictionary_service.get_db", return_value=mock_neo4j_driver):
            dictionary_service.list_dictionaries()

        queries = [entry["query"] for entry in mock_session.queries]
        list_query = next(q for q in queries if "md:MetricDictionary" in q)
        assert "dictionary_key IS NULL" in list_query
