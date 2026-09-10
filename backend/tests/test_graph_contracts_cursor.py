"""cursor encode/decode + principal/revision drift tests (#390).

Split out of test_graph_contracts.py so each contract module ships with
its own focused test file (work-unit commits).
"""
from __future__ import annotations

import pytest

class TestCursor:
    """Opaque pagination cursor (REQ-5).

    Wire format: ``base64url(json({v:1, cluster_id, filters_hash,
    revision, principal_hash, nonce}))``

    - ``filters_hash = sha256(canonical_json(filters)).hexdigest()[:16]``
    - ``principal_hash = sha256(sorted(principal.permission_set))[:16]``
    - Invalid base64 / not-a-string / wrong version -> ``InvalidCursorError``
    - Revision mismatch -> ``StaleCursorError`` (carries current_revision)
    - Principal mismatch -> ``PermissionChangedError``
    """

    def test_round_trip_with_default_revision(self):
        from contracts.cursor import (
            decode_cursor,
            derive_filters_hash,
            encode_cursor,
        )
        from contracts.revision import Revision

        filters = {"ci_type": "router"}
        encoded = encode_cursor(
            cluster_id="location:dc-1",
            filters=filters,
            revision=Revision("test-revision-0001"),
            principal_hash="0" * 16,
        )
        decoded = decode_cursor(encoded)
        assert decoded.cluster_id == "location:dc-1"
        # The cursor does NOT carry filter values; it carries the hash.
        assert decoded.filters_hash == derive_filters_hash(filters)
        assert decoded.revision == "test-revision-0001"
        assert decoded.principal_hash == "0" * 16
        assert decoded.version == 1

    def test_filters_hashed_canonically(self):
        """Same filter set in different order must produce the same hash."""
        from contracts.cursor import decode_cursor, encode_cursor
        from contracts.revision import Revision

        a = encode_cursor(
            cluster_id="location:dc-1",
            filters={"ci_type": "router", "status": "ACTIVE"},
            revision=Revision("test-revision-0001"),
            principal_hash="0" * 16,
        )
        b = encode_cursor(
            cluster_id="location:dc-1",
            filters={"status": "ACTIVE", "ci_type": "router"},
            revision=Revision("test-revision-0001"),
            principal_hash="0" * 16,
        )
        assert decode_cursor(a).filters_hash == decode_cursor(b).filters_hash

    def test_different_filters_produce_different_hashes(self):
        from contracts.cursor import decode_cursor, encode_cursor
        from contracts.revision import Revision

        a = encode_cursor(
            cluster_id="location:dc-1",
            filters={"ci_type": "router"},
            revision=Revision("test-revision-0001"),
            principal_hash="0" * 16,
        )
        b = encode_cursor(
            cluster_id="location:dc-1",
            filters={"ci_type": "switch"},
            revision=Revision("test-revision-0001"),
            principal_hash="0" * 16,
        )
        assert decode_cursor(a).filters_hash != decode_cursor(b).filters_hash

    def test_invalid_cursor_string_raises(self):
        from contracts.cursor import InvalidCursorError, decode_cursor

        with pytest.raises(InvalidCursorError):
            decode_cursor("not-base64url-!")

    def test_invalid_cursor_wrong_version_raises(self):
        """Cursor with unknown version is rejected as invalid."""
        import base64
        import json

        from contracts.cursor import InvalidCursorError, decode_cursor

        bad = base64.urlsafe_b64encode(
            json.dumps({"v": 99, "cluster_id": "location:dc-1"}).encode()
        ).rstrip(b"=").decode()
        with pytest.raises(InvalidCursorError):
            decode_cursor(bad)

    def test_stale_cursor_when_revision_drift(self):
        """A cursor with revision != current revision raises StaleCursorError."""
        from contracts.cursor import (
            StaleCursorError,
            decode_cursor,
            encode_cursor,
        )
        from contracts.revision import Revision

        encoded = encode_cursor(
            cluster_id="location:dc-1",
            filters={"ci_type": "router"},
            revision=Revision("rev-A"),
            principal_hash="0" * 16,
        )
        with pytest.raises(StaleCursorError) as excinfo:
            decode_cursor(encoded, current_revision=Revision("rev-B"))
        assert excinfo.value.current_revision == "rev-B"
        assert excinfo.value.stale_revision == "rev-A"

    def test_permission_changed_when_principal_drift(self):
        """Cursor's principal_hash != current principal raises PermissionChangedError."""
        from contracts.cursor import (
            PermissionChangedError,
            decode_cursor,
            encode_cursor,
        )
        from contracts.revision import Revision

        encoded = encode_cursor(
            cluster_id="location:dc-1",
            filters={},
            revision=Revision("test-revision-0001"),
            principal_hash="a" * 16,
        )
        with pytest.raises(PermissionChangedError):
            decode_cursor(encoded, current_principal_hash="b" * 16)

    def test_principal_hash_is_derived_from_sorted_permissions(self):
        """Helper that hashes a permission set must produce a deterministic 16-char hash."""
        from contracts.cursor import derive_principal_hash

        a = derive_principal_hash({"EVENT_VIEW", "CI_VIEW"})
        b = derive_principal_hash({"CI_VIEW", "EVENT_VIEW"})
        assert a == b
        assert len(a) == 16

    def test_principal_hash_differs_for_different_sets(self):
        from contracts.cursor import derive_principal_hash

        a = derive_principal_hash({"EVENT_VIEW"})
        b = derive_principal_hash({"CI_VIEW"})
        assert a != b

    def test_filters_hash_is_16_chars(self):
        from contracts.cursor import derive_filters_hash

        h = derive_filters_hash({"ci_type": "router"})
        assert len(h) == 16

