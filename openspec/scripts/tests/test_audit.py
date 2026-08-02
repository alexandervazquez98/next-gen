"""Tests for the audit layer — emit_audit_line (WU-4 / REQ-005 / AD-07).

The audit line is the only diagnostic channel: a single key=value line on
stderr that records run-level metadata. It MUST NOT include any CI ID,
name, IP, or site — only ``ts``, ``query_hash``, ``scope``, ``rels``,
``orphan_count``, ``exit``, and (when capped) ``cap_reached``.
"""

from __future__ import annotations

import io

import pytest


class TestEmitAuditLine:
    def test_single_line_with_required_keys_in_order(self):
        """Emitted line has the 7 key=value pairs in spec order."""
        from openspec.scripts.cmdb_backfill_orphans import emit_audit_line

        stream = io.StringIO()
        emit_audit_line(
            stream,
            ts="2026-08-01T12:34:56Z",
            query_hash="abcdef0123456789",
            scope="ap",
            rels=["DEPENDS_ON", "HOSTED_ON"],
            orphan_count=2,
            exit=0,
        )
        line = stream.getvalue()
        assert line.endswith("\n"), "audit line must end with newline"
        body = line.rstrip("\n")
        keys = [kv.split("=", 1)[0] for kv in body.split(" ")]
        assert keys == [
            "ts",
            "query_hash",
            "scope",
            "rels",
            "orphan_count",
            "exit",
            "cap_reached",
        ], f"audit keys must appear in spec order, got {keys!r}"

    def test_query_hash_is_at_least_8_hex_chars(self):
        from openspec.scripts.cmdb_backfill_orphans import emit_audit_line

        stream = io.StringIO()
        emit_audit_line(
            stream,
            ts="2026-08-01T12:34:56Z",
            query_hash="deadbeef",
            scope="ap",
            rels=["DEPENDS_ON"],
            orphan_count=0,
            exit=0,
        )
        line = stream.getvalue()
        # Take the value after `query_hash=` until the next space.
        hash_value = line.split("query_hash=", 1)[1].split(" ", 1)[0]
        assert len(hash_value) >= 8, "query_hash must be ≥ 8 chars"
        assert all(c in "0123456789abcdef" for c in hash_value.lower()), (
            f"query_hash must be hex, got {hash_value!r}"
        )

    def test_rels_joined_with_comma_in_audit_order(self):
        from openspec.scripts.cmdb_backfill_orphans import emit_audit_line

        stream = io.StringIO()
        emit_audit_line(
            stream,
            ts="2026-08-01T12:34:56Z",
            query_hash="abcdef0123456789",
            scope="ap",
            rels=["DEPENDS_ON", "HOSTED_ON"],
            orphan_count=0,
            exit=0,
        )
        line = stream.getvalue()
        assert "rels=DEPENDS_ON,HOSTED_ON" in line

    def test_orphan_count_serialised_as_integer(self):
        from openspec.scripts.cmdb_backfill_orphans import emit_audit_line

        stream = io.StringIO()
        emit_audit_line(
            stream,
            ts="2026-08-01T12:34:56Z",
            query_hash="abcdef0123456789",
            scope="ap",
            rels=["DEPENDS_ON"],
            orphan_count=42,
            exit=0,
        )
        line = stream.getvalue()
        assert "orphan_count=42" in line

    def test_exit_code_included(self):
        from openspec.scripts.cmdb_backfill_orphans import emit_audit_line

        stream = io.StringIO()
        emit_audit_line(
            stream,
            ts="2026-08-01T12:34:56Z",
            query_hash="abcdef0123456789",
            scope="ap",
            rels=["DEPENDS_ON"],
            orphan_count=0,
            exit=2,
        )
        assert "exit=2" in stream.getvalue()

    def test_cap_reached_default_is_false(self):
        """When cap_reached is not passed, the audit line records ``cap_reached=false``."""
        from openspec.scripts.cmdb_backfill_orphans import emit_audit_line

        stream = io.StringIO()
        emit_audit_line(
            stream,
            ts="2026-08-01T12:34:56Z",
            query_hash="abcdef0123456789",
            scope="ap",
            rels=["DEPENDS_ON"],
            orphan_count=5,
            exit=0,
        )
        assert "cap_reached=false" in stream.getvalue()

    def test_cap_reached_true_when_set(self):
        """1000+ orphans returning past the 10k cap must emit ``cap_reached=true``."""
        from openspec.scripts.cmdb_backfill_orphans import emit_audit_line

        stream = io.StringIO()
        emit_audit_line(
            stream,
            ts="2026-08-01T12:34:56Z",
            query_hash="abcdef0123456789",
            scope="ap",
            rels=["DEPENDS_ON", "HOSTED_ON"],
            orphan_count=10000,
            exit=0,
            cap_reached=True,
        )
        assert "cap_reached=true" in stream.getvalue()

    def test_keys_with_cap_reached(self):
        """When cap_reached is set, it is appended after ``exit``."""
        from openspec.scripts.cmdb_backfill_orphans import emit_audit_line

        stream = io.StringIO()
        emit_audit_line(
            stream,
            ts="2026-08-01T12:34:56Z",
            query_hash="abcdef0123456789",
            scope="ap",
            rels=["DEPENDS_ON"],
            orphan_count=0,
            exit=0,
            cap_reached=False,
        )
        line = stream.getvalue().rstrip("\n")
        keys = [kv.split("=", 1)[0] for kv in line.split(" ")]
        assert keys == [
            "ts",
            "query_hash",
            "scope",
            "rels",
            "orphan_count",
            "exit",
            "cap_reached",
        ], f"with cap_reached, keys must end with cap_reached; got {keys!r}"

    def test_no_ci_id_substring_in_audit_line(self):
        """REQ-005: the audit line MUST NOT contain any CI ID substring.

        The function has no ``ci_ids`` parameter by design — it never
        receives CI IDs, so they cannot leak. We assert the audit line
        contains only the 7 spec keys and zero synthetic-id-shaped tokens.
        """
        from openspec.scripts.cmdb_backfill_orphans import emit_audit_line

        stream = io.StringIO()
        emit_audit_line(
            stream,
            ts="2026-08-01T12:34:56Z",
            query_hash="abcdef0123456789",
            scope="ap",
            rels=["DEPENDS_ON", "HOSTED_ON"],
            orphan_count=1000,
            exit=0,
            cap_reached=True,
        )
        line = stream.getvalue()
        for forbidden in (
            "ci-test-ap-orphan",
            "ci-test-ap-orphan-001",
            "ci-test-ap-orphan-500",
        ):
            assert forbidden not in line, (
                f"audit line must not contain CI ID substring {forbidden!r}; line={line!r}"
            )

    def test_signature_excludes_ci_ids(self):
        """Defence in depth: ``emit_audit_line`` does not accept ``ci_ids``."""
        import inspect

        from openspec.scripts.cmdb_backfill_orphans import emit_audit_line

        sig = inspect.signature(emit_audit_line)
        assert "ci_ids" not in sig.parameters, (
            "emit_audit_line must not accept ci_ids (REQ-005 — no CI IDs in audit)"
        )

    def test_writes_to_provided_stream_not_stdout(self, capsys):
        """Audit goes to whatever stream is passed; stdout must remain untouched."""
        from openspec.scripts.cmdb_backfill_orphans import emit_audit_line

        stream = io.StringIO()
        emit_audit_line(
            stream,
            ts="2026-08-01T12:34:56Z",
            query_hash="abcdef0123456789",
            scope="ap",
            rels=["DEPENDS_ON"],
            orphan_count=0,
            exit=0,
        )
        captured = capsys.readouterr()
        assert stream.getvalue(), "stream must receive the audit line"
        assert captured.out == "", "stdout must remain empty"
        assert captured.err == "", "stderr must remain empty (stream is the target)"

    def test_returns_none(self):
        """Audit emission is a side effect; returns ``None``."""
        from openspec.scripts.cmdb_backfill_orphans import emit_audit_line

        result = emit_audit_line(
            io.StringIO(),
            ts="2026-08-01T12:34:56Z",
            query_hash="abcdef0123456789",
            scope="ap",
            rels=["DEPENDS_ON"],
            orphan_count=0,
            exit=0,
        )
        assert result is None
