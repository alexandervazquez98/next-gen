"""Entrypoint regression test (post-WU-10 follow-up).

Locks the ``if __name__ == "__main__": sys.exit(main())`` block so the
script stays invokable from the shell after future refactors.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = (
    REPO_ROOT / "openspec" / "scripts" / "cmdb_backfill_orphans.py"
)


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def test_script_invokable_with_help_flag():
    """`python cmdb_backfill_orphans.py --help` exits 0 and prints usage."""
    result = _run(["--help"])
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "usage:" in result.stdout, (
        f"expected argparse usage line in stdout; got {result.stdout!r}"
    )
    assert "--neo4j-uri" in result.stdout
    assert "--scope" in result.stdout
    assert "--relationship-types" in result.stdout


def test_script_rejects_invalid_scope_at_invocation():
    """Invoking the script with --scope switch fails fast before any I/O."""
    result = _run(["--scope", "switch"])
    assert result.returncode != 0, (
        f"expected non-zero exit for invalid scope; got {result.returncode}; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    # The error must mention the offending scope so the operator can debug.
    assert "switch" in result.stderr or "switch" in result.stdout


def test_script_rejects_unsupported_format():
    """Invoking the script with --format yaml fails fast before any I/O."""
    result = _run(["--format", "yaml"])
    assert result.returncode != 0, (
        f"expected non-zero exit for unsupported format; got {result.returncode}; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_script_help_does_not_leak_query_or_session_state():
    """`--help` must not initialize Neo4j connections or log credentials."""
    result = _run(["--help"])
    assert result.returncode == 0
    # No password/credential fragments should appear in help output.
    sensitive_patterns = [
        re.compile(r"password", re.IGNORECASE),
        re.compile(r"neo4j://[^@]+@"),
        re.compile(r"bolt://[^@]+@"),
    ]
    combined = result.stdout + result.stderr
    for pattern in sensitive_patterns:
        assert not pattern.search(combined), (
            f"help output leaked sensitive info via {pattern.pattern!r}; "
            f"combined output={combined!r}"
        )
