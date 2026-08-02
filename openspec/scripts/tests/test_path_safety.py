"""Tests for path safety — resolve_output_path (WU-5 / REQ-006 / AD-02).

The CLI writes JSON to either stdout (no path) or a file path that
MUST stay inside the working tree. Escape attempts via `..`
traversal, absolute paths to outside the cwd, or symlinks that
resolve outside the cwd MUST be rejected with a clear error before
any write happens.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


class TestResolveOutputPath:
    def test_none_returns_none(self):
        """No path: caller should emit JSON to stdout."""
        from openspec.scripts.cmdb_backfill_orphans import resolve_output_path

        assert resolve_output_path(None) is None

    def test_dash_returns_none(self):
        """The POSIX ``-`` sentinel for stdout MUST also return ``None``."""
        from openspec.scripts.cmdb_backfill_orphans import resolve_output_path

        assert resolve_output_path("-") is None

    def test_empty_string_returns_none(self):
        """Empty string is treated like ``-`` (stdout)."""
        from openspec.scripts.cmdb_backfill_orphans import resolve_output_path

        assert resolve_output_path("") is None

    def test_relative_path_resolves_inside_cwd(self, tmp_path, monkeypatch):
        """`report.json` becomes `cwd/report.json` and stays inside cwd."""
        from openspec.scripts.cmdb_backfill_orphans import resolve_output_path

        monkeypatch.chdir(tmp_path)
        resolved = resolve_output_path("report.json")
        assert resolved is not None
        assert resolved.is_absolute()
        assert resolved == (tmp_path / "report.json").resolve()
        assert str(resolved).startswith(str(tmp_path.resolve()))

    def test_nested_relative_path_inside_cwd(self, tmp_path, monkeypatch):
        """`openspec/scripts/output/x.json` resolves inside cwd."""
        from openspec.scripts.cmdb_backfill_orphans import resolve_output_path

        monkeypatch.chdir(tmp_path)
        resolved = resolve_output_path("openspec/scripts/output/x.json")
        assert resolved is not None
        assert resolved.is_absolute()
        assert str(resolved).startswith(str(tmp_path.resolve()))

    def test_relative_traversal_rejected(self, tmp_path, monkeypatch):
        """`../escape.json` MUST be rejected — escapes cwd."""
        from openspec.scripts.cmdb_backfill_orphans import resolve_output_path

        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValueError) as exc_info:
            resolve_output_path("../escape.json")
        assert "escape" in str(exc_info.value).lower() or "escape" in str(exc_info.value)
        assert "--output" in str(exc_info.value)

    def test_deep_traversal_rejected(self, tmp_path, monkeypatch):
        """`a/../../escape.json` MUST be rejected even when the prefix is valid."""
        from openspec.scripts.cmdb_backfill_orphans import resolve_output_path

        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValueError):
            resolve_output_path("a/../../escape.json")

    def test_absolute_path_outside_cwd_rejected(self, tmp_path, monkeypatch):
        """`/etc/passwd` MUST be rejected (absolute, outside cwd)."""
        from openspec.scripts.cmdb_backfill_orphans import resolve_output_path

        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValueError):
            resolve_output_path("/etc/passwd")

    def test_absolute_path_inside_cwd_accepted(self, tmp_path, monkeypatch):
        """An absolute path that resolves inside cwd is accepted."""
        from openspec.scripts.cmdb_backfill_orphans import resolve_output_path

        monkeypatch.chdir(tmp_path)
        absolute_inside = str((tmp_path / "subdir" / "report.json").resolve())
        resolved = resolve_output_path(absolute_inside)
        assert resolved is not None
        assert str(resolved).startswith(str(tmp_path.resolve()))

    def test_symlink_pointing_outside_cwd_rejected(self, tmp_path, monkeypatch):
        """A symlink that resolves outside cwd MUST be rejected."""
        from openspec.scripts.cmdb_backfill_orphans import resolve_output_path

        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        monkeypatch.chdir(tmp_path)

        # Create a symlink inside cwd that points outside.
        link = tmp_path / "escape_link.json"
        link.symlink_to(outside_dir / "escape.json")

        with pytest.raises(ValueError):
            resolve_output_path(str(link))

    def test_pathlib_input_accepted(self, tmp_path, monkeypatch):
        """`Path` objects are accepted alongside strings."""
        from openspec.scripts.cmdb_backfill_orphans import resolve_output_path

        monkeypatch.chdir(tmp_path)
        resolved = resolve_output_path(Path("report.json"))
        assert resolved is not None
        assert resolved == (tmp_path / "report.json").resolve()

    def test_pathlib_input_traversal_rejected(self, tmp_path, monkeypatch):
        """Even a `Path` literal containing `..` is rejected."""
        from openspec.scripts.cmdb_backfill_orphans import resolve_output_path

        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValueError):
            resolve_output_path(Path("..") / "escape.json")
