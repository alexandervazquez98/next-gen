"""
Unit tests for dictionary_service.py — CRUD operations for MetricDictionary nodes.
"""

import pytest
from unittest.mock import patch, MagicMock

from models.core import MetricDictionary, DictionaryCreate, DictionaryUpdate


class TestDictionaryServiceImports:
    """Verify that dictionary_service can be imported and its functions exist."""

    def test_dictionary_service_imports(self):
        """The module should import without errors."""
        from services import dictionary_service

        assert hasattr(dictionary_service, "get_dictionary")
        assert hasattr(dictionary_service, "list_dictionaries")
        assert hasattr(dictionary_service, "create_dictionary")
        assert hasattr(dictionary_service, "update_dictionary")
        assert hasattr(dictionary_service, "delete_dictionary")
        assert hasattr(dictionary_service, "validate_metric_ids")
        assert hasattr(dictionary_service, "get_metrics_from_dictionary")


class TestDictionaryModels:
    """Test Pydantic models for MetricDictionary."""

    def test_metric_dictionary_model_valid(self):
        """MetricDictionary model should accept a standard payload."""
        d = MetricDictionary(
            id="cisco-2960-v1",
            name="Cisco Catalyst 2960 Template",
            brand="Cisco",
            model="Catalyst-2960",
            metric_ids=["cpu-load", "mem-used"],
            polling_interval=60,
        )
        assert d.id == "cisco-2960-v1"
        assert d.brand == "Cisco"
        assert d.model == "Catalyst-2960"
        assert len(d.metric_ids) == 2

    def test_dictionary_update_optional_fields(self):
        """DictionaryUpdate should allow all fields to be optional."""
        d = DictionaryUpdate(name="New Name")
        assert d.name == "New Name"
        assert d.brand is None
        assert d.model is None
        assert d.metric_ids is None


class TestDictionaryServiceCRUD:
    """CRUD operation tests with mocked Neo4j."""

    def test_get_dictionary_returns_none_when_not_found(self, mock_neo4j_session):
        """get_dictionary should return None for non-existent id."""
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_neo4j_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        with patch("services.dictionary_service.get_db", return_value=mock_driver):
            mock_neo4j_session.set_response("dict_none_check", [])

            from services.dictionary_service import get_dictionary

            result = get_dictionary("non-existent-id")
            assert result is None

    def test_get_dictionary_returns_dict_with_metric_ids(self, mock_neo4j_session):
        """get_dictionary should return dictionary data including metric_ids."""
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_neo4j_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        with patch("services.dictionary_service.get_db", return_value=mock_driver):
            # Query 1: get_dictionary node query
            mock_neo4j_session.set_response(
                "dict_node_query",
                [
                    {
                        "id": "cisco-2960-v1",
                        "name": "Cisco Catalyst 2960",
                        "brand": "Cisco",
                        "model": "Catalyst-2960",
                        "polling_interval": 60,
                        "created_at": None,
                        "updated_at": None,
                    }
                ],
            )
            # Query 2: get_metrics_from_dictionary (HAS_METRIC relationships)
            mock_neo4j_session.set_response(
                "dict_metrics_query",
                [
                    {"metric_id": "cpu-load"},
                    {"metric_id": "mem-used"},
                ],
            )

            from services.dictionary_service import get_dictionary

            result = get_dictionary("cisco-2960-v1")

            assert result is not None
            assert result["id"] == "cisco-2960-v1"
            assert result["brand"] == "Cisco"
            assert result["model"] == "Catalyst-2960"
            assert result["metric_ids"] == ["cpu-load", "mem-used"]

    def test_list_dictionaries_returns_all(self, mock_neo4j_session):
        """list_dictionaries should return all dictionaries."""
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_neo4j_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        with patch("services.dictionary_service.get_db", return_value=mock_driver):
            # Query 1: list_dictionaries node query
            mock_neo4j_session.set_response(
                "dict_list_query",
                [
                    {
                        "id": "dict-1",
                        "name": "Dict 1",
                        "brand": "Cisco",
                        "model": "ASR-1000",
                        "polling_interval": 60,
                        "created_at": None,
                        "updated_at": None,
                    },
                    {
                        "id": "dict-2",
                        "name": "Dict 2",
                        "brand": "Dell",
                        "model": "N3048",
                        "polling_interval": 120,
                        "created_at": None,
                        "updated_at": None,
                    },
                ],
            )
            # Query 2: get_metrics_from_dictionary for dict-1
            mock_neo4j_session.set_response("dict1_metrics", [])
            # Query 3: get_metrics_from_dictionary for dict-2
            mock_neo4j_session.set_response("dict2_metrics", [])

            from services.dictionary_service import list_dictionaries

            result = list_dictionaries()

            assert len(result) == 2
            assert result[0]["id"] == "dict-1"
            assert result[1]["id"] == "dict-2"

    def test_create_dictionary_raises_on_duplicate_brand_model(self, mock_neo4j_session):
        """create_dictionary should raise ValueError if brand+model already exists."""
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_neo4j_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        with patch("services.dictionary_service.get_db", return_value=mock_driver):
            # get_dictionary_by_brand_model calls get_dictionary
            mock_neo4j_session.set_response("dict_brand_model_node", [{"id": "existing-dict"}])
            mock_neo4j_session.set_response("dict_brand_model_metrics", [])

            from services.dictionary_service import create_dictionary

            data = {
                "id": "new-dict",
                "name": "New Dictionary",
                "brand": "Cisco",
                "model": "Catalyst-2960",
                "metric_ids": [],
            }

            with pytest.raises(ValueError, match="already exists"):
                create_dictionary(data)

    def test_create_dictionary_creates_node_and_relationships(self, mock_neo4j_session):
        """create_dictionary should create the node and HAS_METRIC relationships."""
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_neo4j_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        with patch("services.dictionary_service.get_db", return_value=mock_driver):
            # get_dictionary_by_brand_model → get_dictionary (node query returns nothing)
            mock_neo4j_session.set_response("dict_brand_model_node", [])
            mock_neo4j_session.set_response("dict_brand_model_metrics", [])
            # MetricDef checks for cpu-load and mem-used
            mock_neo4j_session.set_response("metricdef_cpu", [{"id": "cpu-load"}])
            mock_neo4j_session.set_response("metricdef_mem", [{"id": "mem-used"}])
            # Final get_dictionary after creation
            mock_neo4j_session.set_response("dict_brand_model_node", [
                {
                    "id": "new-dict",
                    "name": "New Dictionary",
                    "brand": "Cisco",
                    "model": "Catalyst-2960",
                    "polling_interval": 60,
                    "created_at": None,
                    "updated_at": None,
                }
            ])
            mock_neo4j_session.set_response("dict_brand_model_metrics", [{"metric_id": "cpu-load"}])

            from services.dictionary_service import create_dictionary

            data = {
                "id": "new-dict",
                "name": "New Dictionary",
                "brand": "Cisco",
                "model": "Catalyst-2960",
                "metric_ids": ["cpu-load", "mem-used"],
                "polling_interval": 60,
            }

            result = create_dictionary(data)

            assert result is not None
            queries = mock_neo4j_session.queries
            assert any("create (md:metricdictionary" in q["query"].lower() for q in queries)

    def test_update_dictionary_updates_properties(self, mock_neo4j_session):
        """update_dictionary should update the node and replace metric_ids."""
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_neo4j_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        with patch("services.dictionary_service.get_db", return_value=mock_driver):
            # get_dictionary existing
            mock_neo4j_session.set_response("dict_update_get_node", [
                {
                    "id": "dict-1",
                    "name": "Old Name",
                    "brand": "Cisco",
                    "model": "Catalyst-2960",
                    "polling_interval": 60,
                    "created_at": None,
                    "updated_at": None,
                }
            ])
            mock_neo4j_session.set_response("dict_update_get_metrics", [])
            # Check brand+model conflict — no conflict
            mock_neo4j_session.set_response("dict_update_conflict_check", [])
            # Update SET query
            mock_neo4j_session.set_response("dict_update_set_props", [])
            # Delete existing HAS_METRIC
            mock_neo4j_session.set_response("dict_update_delete_metrics", [])
            # Create new HAS_METRIC
            mock_neo4j_session.set_response("dict_update_new_metric", [{"id": "new-metric"}])
            # Final get_dictionary
            mock_neo4j_session.set_response("dict_update_get_node", [
                {
                    "id": "dict-1",
                    "name": "New Name",
                    "brand": "Cisco",
                    "model": "Catalyst-2960",
                    "polling_interval": 90,
                    "created_at": None,
                    "updated_at": None,
                }
            ])
            mock_neo4j_session.set_response("dict_update_get_metrics", [{"metric_id": "new-metric"}])

            from services.dictionary_service import update_dictionary

            result = update_dictionary(
                "dict-1",
                {"name": "New Name", "polling_interval": 90, "metric_ids": ["new-metric"]},
            )

            assert result is not None
            assert result["name"] == "New Name"
            assert result["polling_interval"] == 90

    def test_delete_dictionary_removes_node_and_returns_true(self, mock_neo4j_session):
        """delete_dictionary should remove the node and return True."""
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_neo4j_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        with patch("services.dictionary_service.get_db", return_value=mock_driver):
            # get_dictionary existing
            mock_neo4j_session.set_response("dict_delete_get_node", [
                {
                    "id": "dict-to-delete",
                    "name": "To Delete",
                    "brand": "Cisco",
                    "model": "Catalyst-2960",
                    "polling_interval": 60,
                    "created_at": None,
                    "updated_at": None,
                }
            ])
            mock_neo4j_session.set_response("dict_delete_get_metrics", [])
            # Cascade delete AppliedDictionary
            mock_neo4j_session.set_response("dict_delete_cascade", [])
            # DETACH DELETE MetricDictionary
            mock_neo4j_session.set_response("dict_delete_detach", [])

            from services.dictionary_service import delete_dictionary

            result = delete_dictionary("dict-to-delete")

            assert result is True
            queries = mock_neo4j_session.queries
            assert any("detach delete" in q["query"].lower() for q in queries)

    def test_delete_dictionary_returns_false_when_not_found(self, mock_neo4j_session):
        """delete_dictionary should return False if dictionary doesn't exist."""
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_neo4j_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        with patch("services.dictionary_service.get_db", return_value=mock_driver):
            mock_neo4j_session.set_response("dict_delete_get_node", [])

            from services.dictionary_service import delete_dictionary

            result = delete_dictionary("non-existent")

            assert result is False

    def test_validate_metric_ids_all_valid(self, mock_neo4j_session):
        """validate_metric_ids should return True when all ids exist."""
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_neo4j_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        with patch("services.dictionary_service.get_db", return_value=mock_driver):
            # validate_metric_ids uses "MATCH (m:MetricDef {id: $mid})"
            mock_neo4j_session.set_response(
                "metricdef {id",
                [{"id": "cpu-load"}],
            )
            mock_neo4j_session.set_response(
                "metricdef {id",
                [{"id": "mem-used"}],
            )

            from services.dictionary_service import validate_metric_ids

            valid, invalid = validate_metric_ids(["cpu-load", "mem-used"])

            assert valid is True
            assert invalid == []

    def test_validate_metric_ids_returns_invalid_list(self, mock_neo4j_session):
        """validate_metric_ids should return list of invalid ids."""
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_neo4j_session)
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        with patch("services.dictionary_service.get_db", return_value=mock_driver):
            # cpu-load not found
            mock_neo4j_session.set_response("metricdef {id", [])
            # mem-used found
            mock_neo4j_session.set_response("metricdef {id", [{"id": "mem-used"}])

            from services.dictionary_service import validate_metric_ids

            valid, invalid = validate_metric_ids(["cpu-load", "mem-used"])

            assert valid is False
            assert invalid == ["cpu-load"]

    def test_validate_metric_ids_empty_list(self, mock_neo4j_session):
        """validate_metric_ids should return True for empty list."""
        from services.dictionary_service import validate_metric_ids

        valid, invalid = validate_metric_ids([])

        assert valid is True
        assert invalid == []