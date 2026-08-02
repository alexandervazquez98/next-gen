"""Strict-TDD tests for the operator runbook and CHANGELOG entry (WU-10).

These tests do not exercise production code; they are content-shape
guard tests that keep the operator documentation honest.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNBOOK_PATH = (
    REPO_ROOT
    / "openspec"
    / "scripts"
    / "OPERATOR_RUNBOOK.md"
)
CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"


def test_runbook_exists_and_contains_canonical_steps():
    assert RUNBOOK_PATH.is_file(), f"missing runbook at {RUNBOOK_PATH}"
    text = RUNBOOK_PATH.read_text(encoding="utf-8")
    for marker in (
        "Export",
        "NEO4J_URI",
        "cmdb_backfill_orphans",
        "delete the file",
    ):
        assert marker in text, f"runbook must mention {marker!r}"


def test_runbook_does_not_instruct_copying_into_repo():
    text = RUNBOOK_PATH.read_text(encoding="utf-8").lower()
    forbidden = [
        "git add",
        "git commit",
        "openspec/scripts/output/report.json",
    ]
    for phrase in forbidden:
        assert phrase not in text, f"runbook must not suggest {phrase!r}"


def test_changelog_unreleased_added_section_references_cli():
    text = CHANGELOG_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        r"##\s*\[Unreleased\][\s\S]*?###\s*Added[\s\S]*?-[\s\S]*?cmdb_backfill_orphans",
        re.MULTILINE,
    )
    assert pattern.search(text), (
        "CHANGELOG.md must contain an [Unreleased] -> ### Added entry referencing cmdb_backfill_orphans"
    )


def test_changelog_entry_does_not_disclose_customer_data():
    text = CHANGELOG_PATH.read_text(encoding="utf-8")
    for forbidden in (
        "REGION_TAG",
        "REGION_TAG",
        "REGION_TAG",
        "REGION_TAG",
        "REGION_TAG",
        "10.99.99.99",
    ):
        assert forbidden not in text, f"CHANGELOG.md must not mention {forbidden!r}"
