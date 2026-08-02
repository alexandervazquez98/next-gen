"""Scaffold + SCN-012 (.gitignore coverage for openspec/scripts/output/)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from openspec.scripts.tests.conftest import SYNTHETIC_ID_RE

REPO_ROOT = Path(__file__).resolve().parents[3]
GITIGNORE_PATH = REPO_ROOT / ".gitignore"


def test_synthetic_id_regex_matches_pattern():
    """Sanity check: synthetic pattern matches and rejects real-shape IDs."""
    assert SYNTHETIC_ID_RE.match("ci-test-ap-orphan-001")
    assert SYNTHETIC_ID_RE.match("ci-test-ap-orphan-987654")
    assert not SYNTHETIC_ID_RE.match("REGION_TAG")
    assert not SYNTHETIC_ID_RE.match("10.99.99.99")


def test_openspec_scripts_output_is_gitignored():
    """REQ-009 / SCN-012: ``git check-ignore`` must mark output as ignored."""
    target = "openspec/scripts/output/probe.json"
    result = subprocess.run(
        ["git", "check-ignore", "--", target],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"git check-ignore rejected {target!r}: stdout={result.stdout!r} "
        f"stderr={result.stderr!r}"
    )


def test_gitignore_contains_output_entry():
    """The .gitignore file must include a line matching ``openspec/scripts/output/?$``."""
    assert GITIGNORE_PATH.is_file(), f"missing {GITIGNORE_PATH}"
    pattern = re.compile(r"^openspec/scripts/output/?\s*$", re.MULTILINE)
    assert pattern.search(GITIGNORE_PATH.read_text()), (
        f".gitignore must contain `openspec/scripts/output/` entry; "
        f"actual contents:\n{GITIGNORE_PATH.read_text()}"
    )
