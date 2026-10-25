"""Managed MetricDictionary lookup seam for Service Management imports.

The Service Catalog form (feature #480) and the XLSX import path read their
controlled vocabularies from the same ``MetricDictionary`` node model:
``value_stream`` (PR2 seeded ``operate`` and ``deliver``), plus ``tier`` and
``criticality`` seeded by ``services.itsm_imports.seed_data``.

Keeping the lookup in its own module avoids leaking the dictionary surface
into the import path, while the shared base class keeps the dropdown source
and the import validation on exactly the same Cypher.
"""

from __future__ import annotations

from typing import Any

from services.dictionary_service import MetricDictionaryLookup


class MetricDictionaryValueStreamLookup(MetricDictionaryLookup):
    """Read active value streams from ``MetricDictionary`` nodes."""

    DICTIONARY_KEY = "value_stream"

    def __init__(self, driver: Any | None = None) -> None:
        super().__init__(self.DICTIONARY_KEY, driver=driver)


class MetricDictionaryTierLookup(MetricDictionaryLookup):
    """Read active service tiers (``bronze|silver|gold|platinum``)."""

    DICTIONARY_KEY = "tier"

    def __init__(self, driver: Any | None = None) -> None:
        super().__init__(self.DICTIONARY_KEY, driver=driver)


class MetricDictionaryCriticalityLookup(MetricDictionaryLookup):
    """Read active service criticalities (``low|medium|high|critical``)."""

    DICTIONARY_KEY = "criticality"

    def __init__(self, driver: Any | None = None) -> None:
        super().__init__(self.DICTIONARY_KEY, driver=driver)


__all__ = [
    "MetricDictionaryCriticalityLookup",
    "MetricDictionaryLookup",
    "MetricDictionaryTierLookup",
    "MetricDictionaryValueStreamLookup",
]
