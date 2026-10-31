"""Managed MetricDictionary lookup seam + seed vocabulary tests (feature #480).

Covers:
- S2/S5: the lookup seam reads managed values per ``dictionary_key`` and is
  the single read seam shared by the HTTP contract and the XLSX import path.
- S5: the seed module exposes the tier / criticality vocabularies used by the
  ITIL-aligned Service Catalog dropdowns.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from services.itsm_imports import seed_data
from services.itsm_imports.value_stream_lookup import (
    MetricDictionaryCriticalityLookup,
    MetricDictionaryLookup,
    MetricDictionaryTierLookup,
    MetricDictionaryValueStreamLookup,
)


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)

    def single(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Records the Cypher statements and returns canned rows."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.queries: list[tuple[str, dict[str, Any]]] = []

    def run(self, query: str, **params: Any) -> _FakeResult:
        self.queries.append((query, params))
        return _FakeResult(self.rows)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class _FakeDriver:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def session(self):
        return self._session


class TestManagedDictionaryLookupSeam:
    """The lookup seam is reusable by the router and by the import path."""

    def test_value_stream_lookup_targets_the_value_stream_key(self):
        session = _FakeSession([{"value": "operate", "label": "Operate"}])
        lookup = MetricDictionaryValueStreamLookup(driver=_FakeDriver(session))

        rows = lookup.list_active()

        assert rows == [{"value": "operate", "label": "Operate"}]
        query, params = session.queries[0]
        assert "MetricDictionary" in query
        assert params["key"] == "value_stream"
        assert params["active"] is True

    def test_tier_and_criticality_lookups_use_their_own_keys(self):
        session = _FakeSession([{"value": "gold", "label": "Gold"}])

        MetricDictionaryTierLookup(driver=_FakeDriver(session)).list_active()
        assert session.queries[-1][1]["key"] == "tier"

        MetricDictionaryCriticalityLookup(driver=_FakeDriver(session)).list_active()
        assert session.queries[-1][1]["key"] == "criticality"

    def test_is_active_reports_unknown_values_as_inactive(self):
        session = _FakeSession([])
        lookup = MetricDictionaryValueStreamLookup(driver=_FakeDriver(session))

        assert lookup.is_active("retire") is False
        assert lookup.is_active("") is False

    def test_is_active_reads_the_active_flag(self):
        session = _FakeSession([{"active": True}])
        lookup = MetricDictionaryTierLookup(driver=_FakeDriver(session))

        assert lookup.is_active("gold") is True

    def test_generic_lookup_accepts_an_explicit_key(self):
        session = _FakeSession([{"value": "x", "label": "X"}])
        lookup = MetricDictionaryLookup("custom_key", driver=_FakeDriver(session))

        lookup.list_active()

        assert session.queries[-1][1]["key"] == "custom_key"

    def test_lookup_satisfies_the_import_lookup_protocol(self):
        """The import path consumes ``list_active``/``is_active`` only."""
        session = _FakeSession([{"value": "operate", "label": "Operate"}])
        lookup = MetricDictionaryValueStreamLookup(driver=_FakeDriver(session))

        assert callable(lookup.list_active)
        assert callable(lookup.is_active)
        assert lookup.list_active()[0]["value"] == "operate"


class TestSeedDataTierAndCriticality:
    """The seed module writes tier + criticality MetricDictionary entries."""

    def test_seed_data_module_exposes_tier_and_criticality_constants(self):
        assert seed_data.TIER_VALUES == ("bronze", "silver", "gold", "platinum")
        assert seed_data.CRITICALITY_VALUES == ("low", "medium", "high", "critical")

    def test_seed_tier_criticality_is_idempotent_merges(self):
        driver = MagicMock()
        session = MagicMock()
        driver.session.return_value.__enter__.return_value = session
        driver.session.return_value.__exit__.return_value = False

        with patch("services.itsm_imports.seed_data.get_db", return_value=driver):
            result = seed_data.seed_tier_criticality_dictionaries()

        assert result["tier_count"] == len(seed_data.TIER_VALUES)
        assert result["criticality_count"] == len(seed_data.CRITICALITY_VALUES)

        statements = [call.args[0] for call in session.run.call_args_list]
        assert any("MERGE" in stmt and "'tier'" in stmt for stmt in statements)
        assert any("MERGE" in stmt and "'criticality'" in stmt for stmt in statements)
        # Idempotent: every statement MERGEs on the (dictionary_key, value) pair.
        assert all("MERGE" in stmt for stmt in statements)

    def test_seed_passes_every_seeded_value_to_the_driver(self):
        driver = MagicMock()
        session = MagicMock()
        driver.session.return_value.__enter__.return_value = session
        driver.session.return_value.__exit__.return_value = False

        with patch("services.itsm_imports.seed_data.get_db", return_value=driver):
            seed_data.seed_tier_criticality_dictionaries()

        payloads = [call.kwargs.get("values") for call in session.run.call_args_list]
        flat = [row["value"] for batch in payloads for row in batch]
        assert flat == list(seed_data.TIER_VALUES) + list(seed_data.CRITICALITY_VALUES)


@pytest.mark.parametrize(
    ("lookup_class", "expected_key"),
    [
        (MetricDictionaryValueStreamLookup, "value_stream"),
        (MetricDictionaryTierLookup, "tier"),
        (MetricDictionaryCriticalityLookup, "criticality"),
    ],
)
def test_lookup_classes_expose_a_stable_dictionary_key(lookup_class, expected_key):
    assert expected_key == lookup_class.DICTIONARY_KEY
