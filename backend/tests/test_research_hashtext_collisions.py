"""Strict-TDD tests for ``backend/scripts/research_hashtext_collisions.py``.

We exercise three contracts:

1. ``hashtext_port(text)`` — a faithful Python port of PostgreSQL's
   ``hashtext()`` (which calls ``hash_any()`` from
   ``src/backend/utils/hash/hashfuncs.c``). The port MUST return a signed
   32-bit integer and MUST agree with a snapshot of reference values computed
   against the same algorithm. If ``DATABASE_URL`` is set, the test also
   cross-checks the port against a live PostgreSQL ``SELECT hashtext(:k)``
   query — that gate is the definitive proof that the port matches PG's
   reference implementation.

2. ``analyze_collisions(triplets)`` — the collision-bucketing helper MUST
   satisfy the invariant ``len(buckets) + collisions == total_triplets`` so
   any under/over-counting of duplicates is caught.

3. End-to-end smoke — synthetic data generation must produce the requested
   volume and the analysis must complete on 1,000 triplets without raising.

The script under test is ``research_hashtext_collisions`` (see the matching
``scripts/`` module). All tests are unit-level; the only integration point
is the optional PG cross-check, which is guarded by ``@pytest.mark.integration``
plus the ``DATABASE_URL`` env var so default test runs skip it.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
from importlib import import_module
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = REPO_ROOT / "backend" / "scripts"


def _import_script_module():
    """Import the script as a module without executing its top-level side effects.

    ``research_hashtext_collisions.py`` only does work inside ``main()`` /
    helper functions, so a plain ``importlib`` import is safe. We expect
    ``ImportError`` until the script ships — that failure is the TDD signal.
    """
    import sys

    sys.path.insert(0, str(SCRIPT_DIR.parent))
    return import_module("scripts.research_hashtext_collisions")


# ---------------------------------------------------------------------------
# Hashtext port
# ---------------------------------------------------------------------------


class TestHashtextPort:
    """Validates the Python port of PostgreSQL's ``hashtext()``."""

    def test_module_imports(self):
        """The script module must be importable — TDD gate."""
        mod = _import_script_module()
        assert hasattr(mod, "hashtext_port"), "missing hashtext_port function"
        assert hasattr(mod, "analyze_collisions"), "missing analyze_collisions helper"

    def test_returns_signed_32bit_int(self):
        mod = _import_script_module()
        h = mod.hashtext_port
        samples = [b"", b"a", b"hello", b"snmp.if.in_errors", b"\x00\xff" * 32]
        for s in samples:
            v = h(s)
            assert isinstance(v, int), f"hashtext({s!r}) -> non-int {type(v).__name__}"
            assert -(2**31) <= v < 2**31, f"hashtext({s!r}) -> {v} out of int32 range"

    def test_deterministic(self):
        mod = _import_script_module()
        h = mod.hashtext_port
        for s in [b"abc", b"the quick brown fox", b"ci-1|snmp.if.in|AVAILABILITY"]:
            assert h(s) == h(s), f"hashtext({s!r}) is non-deterministic"

    def test_known_answer_table(self):
        """Snapshot of values computed from the PG algorithm.

        These values were produced by a faithful Python port of
        ``hash_any()`` from ``src/backend/utils/hash/hashfuncs.c`` (Jenkins
        lookup3 hashlittle2 with PG-specific init constants). They are NOT
        ground truth on their own — the live-PG integration test (see below)
        is the proof — but they catch accidental refactors that change the
        algorithm without anyone noticing.
        """
        mod = _import_script_module()
        h = mod.hashtext_port
        cases = {
            b"": 450340318,
            b"a": -425142634,
            b"hello": 1151802707,
            b"helloworld": 1031275612,
            b"snmp.if.in_errors": 1444673387,
            b"COLLECTION_FAILURE": 96606080,
            b"ci-000001|snmp.if.in_errors|COLLECTION_FAILURE": -114110231,
            b"ci-000001|snmp.if.in_errors|AVAILABILITY": 645247062,
            b"ci-000001|snmp.if.in_errors|THRESHOLD_BREACH": -135386541,
            b"ci-000001|snmp.if.in_errors|": 463411012,
            b"ci-000002|snmp.if.in_errors|COLLECTION_FAILURE": 720726474,
            b"ci-000001|snmp.icmp.latency_ms|THRESHOLD_BREACH": -1299857824,
            b"router-test-1|snmp.collection_failure|COLLECTION_FAILURE": 1362327835,
        }
        for key, expected in cases.items():
            actual = h(key)
            assert actual == expected, (
                f"hashtext({key!r}) -> {actual}, expected {expected}. "
                "Either the port is wrong or the snapshot is stale — "
                "verify against `SELECT hashtext(:k)` on PostgreSQL."
            )

    def test_distinct_inputs_likely_distinct_outputs(self):
        """Statistical sanity: 1024 random strings should produce 1024 distinct
        hashes with very high probability (birthday paradox puts collisions in
        the 1024²/2^32 ≈ 0.0002 range for 32-bit hashes). One collision is
        tolerable; more than one would mean the algorithm is broken.
        """
        mod = _import_script_module()
        h = mod.hashtext_port
        rng = random.Random(0xDEADBEEF)
        keys = [
            "".join(chr(rng.randint(32, 126)) for _ in range(rng.randint(3, 32))).encode()
            for _ in range(1024)
        ]
        hashes = [h(k) for k in keys]
        distinct = len(set(hashes))
        assert (
            distinct >= 1023
        ), f"only {distinct}/1024 distinct hashes on random keys — port is suspicious"

    @pytest.mark.integration
    def test_port_matches_live_postgres(self):
        """If a Postgres is reachable, cross-check the port against the real
        ``hashtext()`` SQL function. This is the only test that proves the
        port is correct end-to-end.
        """
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            pytest.skip("DATABASE_URL not set; live-PG cross-check skipped")

        try:
            import psycopg2  # noqa: F401
        except ImportError:
            pytest.skip("psycopg2 not installed; live-PG cross-check skipped")

        import psycopg2

        mod = _import_script_module()
        h = mod.hashtext_port

        # At least 5 sample keys covering: empty, single byte, multi-byte,
        # production-style triplet, NULL-event-type variant.
        samples = [
            b"",
            b"a",
            b"hello",
            b"snmp.if.in_errors",
            b"ci-000001|snmp.if.in_errors|COLLECTION_FAILURE",
            b"ci-000007|snmp.icmp.latency_ms|THRESHOLD_BREACH",
        ]
        with psycopg2.connect(db_url) as conn, conn.cursor() as cur:
            for key in samples:
                key_text = key.decode("latin1")  # PG text type; latin1 preserves bytes
                cur.execute("SELECT hashtext(%s)::int", (key_text,))
                (pg_value,) = cur.fetchone()
                py_value = h(key)
                assert (
                    py_value == pg_value
                ), f"port drift on {key!r}: python={py_value} postgres={pg_value}"


# ---------------------------------------------------------------------------
# Collision bucketing invariants
# ---------------------------------------------------------------------------


class TestBucketingInvariants:
    """Validates the collision analyzer used by the research script."""

    def test_buckets_plus_collisions_equals_total(self):
        """For every input ``T = N + sum_over_buckets(bucket_size - 1)``
        rearranges to ``len(buckets) + collisions == total_triplets``.

        The analyzer MUST report ``collisions`` as ``sum(bucket_size - 1)``
        (i.e. the number of "extra" entries that landed in a shared bucket),
        not as ``len(buckets_with_size_>_1)`` — the issue's decision rule
        relies on the collision-RATE, which is collisions/total. Any
        inconsistency in that ratio silently flips the recommendation.
        """
        mod = _import_script_module()
        analyze = mod.analyze_collisions

        # Mix of colliding and non-colliding synthetic triplets.
        triplets = [(f"ci-{i}", f"m.{i % 7}", f"et{i % 3}") for i in range(500)]
        # Force a couple of collisions by reusing the same triplet twice.
        triplets.append(("ci-1", "m.1", "et0"))
        triplets.append(("ci-1", "m.1", "et0"))

        result = analyze(triplets)
        total = result["total_triplets"]
        buckets = result["distinct_buckets"]
        collisions = result["collision_count"]
        assert buckets + collisions == total, (
            f"invariant broken: buckets({buckets}) + collisions({collisions}) "
            f"!= total_triplets({total})"
        )
        # At least the 2 we forced.
        assert collisions >= 2, f"expected >=2 forced collisions, got {collisions}"

    def test_synthetic_smoke_1000_triplets(self):
        """End-to-end: generate 1,000 distinct triplets, run analysis, assert
        the analyzer returns the requested volume and at most 1,000 buckets.
        """
        mod = _import_script_module()
        analyze = mod.analyze_collisions
        rng = random.Random(1234)
        triplets = [
            (f"ci-{i}", f"snmp.metric_{i % 17}", rng.choice(["COLLECTION_FAILURE", "AVAILABILITY"]))
            for i in range(1000)
        ]
        result = analyze(triplets)
        assert result["total_triplets"] == 1000
        assert result["distinct_buckets"] <= 1000
        assert "max_bucket_size" in result
        assert "percentiles" in result
        for p in ("p50", "p90", "p99", "p100"):
            assert p in result["percentiles"], f"missing percentile {p}"

    def test_collision_rate_zero_for_unique_inputs(self):
        """If every triplet is unique, the collision rate must be 0.0."""
        mod = _import_script_module()
        analyze = mod.analyze_collisions
        triplets = [(f"ci-{i}", f"m.{i}", "AVAILABILITY") for i in range(50)]
        result = analyze(triplets)
        assert result["collision_count"] == 0
        assert result["collision_rate"] == 0.0


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


class TestScriptCLI:
    """Verifies the argparse surface advertises every required flag and
    rejects invalid arguments. Keeps the script self-documenting and
    protects future authors from accidentally deleting flags.
    """

    def test_help_lists_required_flags(self):
        """The CLI must advertise: --mode, --num-cis, --metrics-per-ci,
        --samples-per-triplet, --seed, --include-null-event-type, --output,
        --write-report. These are the knobs the report's methodology section
        documents.
        """
        proc = subprocess.run(
            ["python3", str(SCRIPT_DIR / "research_hashtext_collisions.py"), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, f"--help failed: {proc.stderr}"
        help_text = proc.stdout
        for flag in (
            "--mode",
            "--num-cis",
            "--metrics-per-ci",
            "--samples-per-triplet",
            "--seed",
            "--include-null-event-type",
            "--output",
            "--write-report",
        ):
            assert flag in help_text, f"missing flag {flag!r} in --help output"

    def test_invalid_mode_rejected(self):
        proc = subprocess.run(
            [
                "python3",
                str(SCRIPT_DIR / "research_hashtext_collisions.py"),
                "--mode",
                "totally-bogus",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode != 0, "invalid --mode was accepted; should fail"


# ---------------------------------------------------------------------------
# Smoke run end-to-end
# ---------------------------------------------------------------------------


class TestScriptSmokeRun:
    """Run the script as a subprocess and validate the JSON output shape.

    This catches import-time errors, argparse regressions, and JSON schema
    drift before the report uses the data.
    """

    def test_synthetic_run_produces_valid_json(self, tmp_path):
        out = tmp_path / "summary.json"
        proc = subprocess.run(
            [
                "python3",
                str(SCRIPT_DIR / "research_hashtext_collisions.py"),
                "--mode",
                "synthetic",
                "--num-cis",
                "100",
                "--metrics-per-ci",
                "3",
                "--seed",
                "42",
                "--output",
                str(out),
            ],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "PYTHONPATH": str(SCRIPT_DIR.parent)},
        )
        assert proc.returncode == 0, f"script failed: stdout={proc.stdout} stderr={proc.stderr}"
        payload = json.loads(out.read_text())
        # The script may emit a single run or a list of runs depending on --mode.
        # For --mode synthetic we expect exactly one run inside ``runs``.
        assert "runs" in payload, f"missing top-level 'runs' key in {payload}"
        assert len(payload["runs"]) == 1, f"expected 1 run, got {len(payload['runs'])}"
        run = payload["runs"][0]
        # Required keys — the report depends on these.
        for key in (
            "mode",
            "total_triplets",
            "distinct_buckets",
            "collision_count",
            "collision_rate",
            "max_bucket_size",
            "percentiles",
            "config",
        ):
            assert key in run, f"missing key {key!r} in JSON run summary"
        # 100 CIs * 3 metrics * (4 event types - 0 if null excluded) = 1200 or 1500
        # Default includes the NULL event_type → 100 * 3 * 4 = 1200 triplets.
        assert (
            run["total_triplets"] == 1200
        ), f"expected 1200 default-event-type triplets, got {run['total_triplets']}"
        assert run["collision_count"] >= 0
        assert 0.0 <= run["collision_rate"] <= 1.0
