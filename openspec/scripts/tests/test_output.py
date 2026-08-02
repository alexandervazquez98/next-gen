"""Tests for the output layer (build_output_payload, write_output, _validate_ci_id)."""

from __future__ import annotations

import io
import json
import re
import sys
import uuid
from contextlib import redirect_stdout
from pathlib import Path

import pytest


SAMPLE_IDS = [
    "ci-test-ap-orphan-001",
    "ci-test-ap-orphan-002",
    "ci-test-ap-orphan-003",
]


class TestBuildOutputPayload:
    def test_returns_exactly_five_keys(self):
        from openspec.scripts.cmdb_backfill_orphans import build_output_payload

        payload = build_output_payload(
            as_of="2026-08-01T12:34:56Z",
            scope="ap",
            rels=["DEPENDS_ON", "HOSTED_ON"],
            ci_ids=list(SAMPLE_IDS),
        )
        assert set(payload.keys()) == {
            "as_of",
            "scope",
            "relationship_types",
            "orphan_count",
            "ci_ids",
        }

    def test_orphan_count_equals_len_ci_ids(self):
        from openspec.scripts.cmdb_backfill_orphans import build_output_payload

        payload = build_output_payload(
            as_of="2026-08-01T12:34:56Z",
            scope="ap",
            rels=["DEPENDS_ON"],
            ci_ids=list(SAMPLE_IDS),
        )
        assert payload["orphan_count"] == len(payload["ci_ids"])
        assert payload["orphan_count"] == 3

    def test_as_of_iso8601_utc_with_trailing_z(self):
        from openspec.scripts.cmdb_backfill_orphans import build_output_payload

        payload = build_output_payload(
            as_of="2026-08-01T12:34:56Z",
            scope="ap",
            rels=["DEPENDS_ON"],
            ci_ids=["ci-test-ap-orphan-001"],
        )
        assert payload["as_of"] == "2026-08-01T12:34:56Z"
        assert payload["as_of"].endswith("Z")

    def test_as_of_default_is_iso8601_utc(self):
        from openspec.scripts.cmdb_backfill_orphans import build_output_payload

        payload = build_output_payload(
            scope="ap", rels=["DEPENDS_ON"], ci_ids=["ci-test-ap-orphan-001"]
        )
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", payload["as_of"])

    def test_scope_passes_through(self):
        from openspec.scripts.cmdb_backfill_orphans import build_output_payload

        payload = build_output_payload(
            scope="ap", rels=["DEPENDS_ON"], ci_ids=["ci-test-ap-orphan-001"]
        )
        assert payload["scope"] == "ap"

    def test_relationship_types_passthrough(self):
        from openspec.scripts.cmdb_backfill_orphans import build_output_payload

        payload = build_output_payload(
            scope="ap",
            rels=["DEPENDS_ON", "HOSTED_ON"],
            ci_ids=["ci-test-ap-orphan-001"],
        )
        assert payload["relationship_types"] == ["DEPENDS_ON", "HOSTED_ON"]

    def test_filters_non_opaque_values(self):
        """REQ-004: a CI record's extra properties must not leak through."""
        from openspec.scripts.cmdb_backfill_orphans import build_output_payload

        mixed = [
            "ci-test-ap-orphan-001",
            "REGION_TAG",
            "10.99.99.99",
            str(uuid.uuid4()),
            None,
            12345,
            "REMOTE_SITE",
            "ci-test-ap-orphan-002",
        ]
        payload = build_output_payload(
            scope="ap", rels=["DEPENDS_ON"], ci_ids=mixed
        )
        assert "REGION_TAG" not in payload["ci_ids"]
        assert "10.99.99.99" not in payload["ci_ids"]
        assert "REMOTE_SITE" not in payload["ci_ids"]
        assert None not in payload["ci_ids"]
        assert 12345 not in payload["ci_ids"]
        assert payload["orphan_count"] == 3  # 2 synthetic + 1 UUID

    def test_dedupes_preserving_first_seen_order(self):
        from openspec.scripts.cmdb_backfill_orphans import build_output_payload

        ids = [
            "ci-test-ap-orphan-002",
            "ci-test-ap-orphan-001",
            "ci-test-ap-orphan-002",
            "ci-test-ap-orphan-001",
            "ci-test-ap-orphan-003",
        ]
        payload = build_output_payload(
            scope="ap", rels=["DEPENDS_ON"], ci_ids=ids
        )
        assert payload["ci_ids"] == [
            "ci-test-ap-orphan-002",
            "ci-test-ap-orphan-001",
            "ci-test-ap-orphan-003",
        ]
        assert payload["orphan_count"] == 3

    def test_empty_input_yields_empty_list(self):
        from openspec.scripts.cmdb_backfill_orphans import build_output_payload

        payload = build_output_payload(scope="ap", rels=["DEPENDS_ON"], ci_ids=[])
        assert payload["ci_ids"] == []
        assert payload["orphan_count"] == 0


class TestWriteOutput:
    def test_writes_file_when_path_given(self, tmp_path):
        from openspec.scripts.cmdb_backfill_orphans import (
            build_output_payload,
            write_output,
        )

        payload = build_output_payload(
            scope="ap", rels=["DEPENDS_ON"], ci_ids=list(SAMPLE_IDS)
        )
        target = tmp_path / "orphans.json"
        with redirect_stdout(io.StringIO()) as captured:
            result = write_output(payload, target)
        assert result is None
        assert target.is_file()
        assert target.read_text(encoding="utf-8").strip(), "file must contain JSON"
        parsed = json.loads(target.read_text(encoding="utf-8"))
        assert set(parsed.keys()) == {
            "as_of",
            "scope",
            "relationship_types",
            "orphan_count",
            "ci_ids",
        }
        assert captured.getvalue() == "", "stdout must remain untouched when path provided"

    def test_writes_stdout_when_path_is_none(self, capsys):
        from openspec.scripts.cmdb_backfill_orphans import (
            build_output_payload,
            write_output,
        )

        payload = build_output_payload(
            scope="ap", rels=["DEPENDS_ON"], ci_ids=list(SAMPLE_IDS)
        )
        result = write_output(payload, None)
        assert result is None
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["scope"] == "ap"
        assert parsed["orphan_count"] == 3

    def test_atomic_rename_target_exists(self, tmp_path):
        """Atomic-write contract: target file exists post-write, no .tmp leftover."""
        from openspec.scripts.cmdb_backfill_orphans import (
            build_output_payload,
            write_output,
        )

        payload = build_output_payload(
            scope="ap", rels=["DEPENDS_ON"], ci_ids=["ci-test-ap-orphan-007"]
        )
        target = tmp_path / "nested" / "subdir" / "orphans.json"
        write_output(payload, target)
        assert target.is_file()
        assert not target.with_suffix(target.suffix + ".tmp").exists()
        siblings = [p for p in target.parent.glob("*.tmp")]
        assert siblings == []

    def test_pathlib_path_accepted(self, tmp_path):
        from openspec.scripts.cmdb_backfill_orphans import (
            build_output_payload,
            write_output,
        )

        payload = build_output_payload(
            scope="ap", rels=["DEPENDS_ON"], ci_ids=["ci-test-ap-orphan-008"]
        )
        target = Path(tmp_path) / "via_pathlib.json"
        write_output(payload, target)
        assert target.is_file()


class TestValidateCiId:
    def test_synthetic_id_accepted(self):
        from openspec.scripts.cmdb_backfill_orphans import _validate_ci_id

        assert _validate_ci_id("ci-test-ap-orphan-001") == "ci-test-ap-orphan-001"

    def test_uuid_accepted(self):
        from openspec.scripts.cmdb_backfill_orphans import _validate_ci_id

        uid = str(uuid.uuid4())
        assert _validate_ci_id(uid) == uid.lower()

    def test_uppercase_uuid_normalized(self):
        from openspec.scripts.cmdb_backfill_orphans import _validate_ci_id

        uid = str(uuid.uuid4()).upper()
        canonical = _validate_ci_id(uid)
        assert canonical == canonical.lower()
        uuid.UUID(canonical)  # must still parse

    @pytest.mark.parametrize(
        "bad",
        [
            "REGION_TAG",
            "10.99.99.99",
            "REMOTE_SITE",
            "UPPERCASE_TOKEN",
            "OFFICE_TAG",
            "not-a-real-id",
            "",
            "ci-test-ap-orphan-abc",  # non-numeric suffix
            "ci-test-ap-orphan-12",  # too few digits
        ],
    )
    def test_real_shape_and_non_opaque_rejected(self, bad):
        from openspec.scripts.cmdb_backfill_orphans import _validate_ci_id

        with pytest.raises(ValueError):
            _validate_ci_id(bad)

    def test_non_string_rejected(self):
        from openspec.scripts.cmdb_backfill_orphans import _validate_ci_id

        with pytest.raises(ValueError):
            _validate_ci_id(None)
        with pytest.raises(ValueError):
            _validate_ci_id(12345)
