from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("validate_smoke_fixtures.py")
spec = importlib.util.spec_from_file_location("validate_smoke_fixtures", MODULE_PATH)
smoke = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(smoke)


class _FakeRecord(dict):
    pass


class _FakeResult:
    def __init__(self, record):
        self._record = _FakeRecord(record)

    def single(self, strict=False):
        return self._record


class _FakeSession:
    def __init__(self, fail_seed=False):
        self.calls = []
        self.fail_seed = fail_seed
        self.execute_write_calls = 0

    def execute_write(self, callback):
        self.execute_write_calls += 1
        return callback(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, query, **params):
        self.calls.append((query, params))
        if query == smoke.SEED_QUERY:
            if self.fail_seed:
                raise RuntimeError("forced seed failure")
            return _FakeResult({"seeded_count": len(params["fixtures"])})
        if query == smoke.CLEANUP_QUERY:
            return _FakeResult({"deleted_count": 3})
        if query == smoke.POST_CLEANUP_QUERY:
            return _FakeResult({"cleanup_verified": True, "remaining_count": 0})
        raise AssertionError(f"unexpected query: {query}")


class _FakeDriver:
    def __init__(self, fail_seed=False):
        self.sessions = []
        self.fail_seed = fail_seed

    def session(self):
        session = _FakeSession(fail_seed=self.fail_seed and not self.sessions)
        self.sessions.append(session)
        return session


class SmokeFixtureHarnessTests(unittest.TestCase):
    def test_fixture_plan_marks_every_event_with_run_id_and_covers_expected_buckets(self):
        fixtures = smoke.build_fixture_plan("issue155-smoke-test")

        self.assertEqual(
            [fixture["expected_bucket"] for fixture in fixtures],
            ["safe_candidates", "ambiguous_records", "no_touch_records"],
        )
        self.assertEqual({fixture["issue155_smoke"] for fixture in fixtures}, {True})
        self.assertEqual(
            {fixture["issue155_smoke_run_id"] for fixture in fixtures},
            {"issue155-smoke-test"},
        )
        self.assertEqual(
            [fixture["id"] for fixture in fixtures],
            [
                "issue155-smoke-test-safe",
                "issue155-smoke-test-ambiguous",
                "issue155-smoke-test-no-touch",
            ],
        )

    def test_local_uri_guard_accepts_shared_local_neo4j_only(self):
        self.assertEqual(
            smoke.validate_local_neo4j_uri("bolt://127.0.0.1:17687"),
            "bolt://127.0.0.1:17687",
        )
        self.assertEqual(
            smoke.validate_local_neo4j_uri("neo4j://localhost:17687"),
            "neo4j://localhost:17687",
        )

    def test_local_uri_guard_rejects_default_container_and_remote_targets(self):
        for uri in (
            "bolt://neo4j:7687",
            "bolt://10.1.2.3:17687",
            "neo4j+s://db.example.com:7687",
        ):
            with self.subTest(uri=uri):
                with self.assertRaisesRegex(smoke.UnsafeTargetError, "shared local Neo4j"):
                    smoke.validate_local_neo4j_uri(uri)

    def test_cleanup_verification_query_proves_zero_marked_events_for_run_id(self):
        self.assertIn("issue155_smoke:true", smoke.POST_CLEANUP_QUERY)
        self.assertIn("issue155_smoke_run_id:$run_id", smoke.POST_CLEANUP_QUERY)
        self.assertIn("RETURN count(e)=0", smoke.POST_CLEANUP_QUERY)

    def test_cleanup_query_deletes_only_marker_and_run_id_scoped_events(self):
        self.assertIn("issue155_smoke:true", smoke.CLEANUP_QUERY)
        self.assertIn("issue155_smoke_run_id:$run_id", smoke.CLEANUP_QUERY)
        self.assertIn("DETACH DELETE", smoke.CLEANUP_QUERY)
        self.assertNotIn("MATCH (e:Event)\n", smoke.CLEANUP_QUERY)


    def test_resolve_evidence_output_accepts_relative_path_under_evidence_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            evidence_dir = Path(tmp) / "evidence"
            evidence_dir.mkdir()

            output_path = smoke.resolve_evidence_output_path("manifest.json", evidence_dir=evidence_dir)

            self.assertEqual(output_path, (evidence_dir / "manifest.json").resolve())

    def test_resolve_evidence_output_rejects_traversal_and_absolute_paths_outside_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            evidence_dir = Path(tmp) / "evidence"
            outside_dir = Path(tmp) / "outside"
            evidence_dir.mkdir()
            outside_dir.mkdir()

            for requested in ("../outside/manifest.json", outside_dir / "manifest.json"):
                with self.subTest(requested=str(requested)):
                    with self.assertRaisesRegex(smoke.OutputTargetError, "evidence directory"):
                        smoke.resolve_evidence_output_path(requested, evidence_dir=evidence_dir)


    def test_write_json_accepts_new_output_under_evidence_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            evidence_dir = Path(tmp) / "evidence"
            evidence_dir.mkdir()
            output_path = smoke.resolve_evidence_output_path("nested/manifest.json", evidence_dir=evidence_dir)

            smoke.write_json_exclusive(output_path, {"status": "ok"}, evidence_dir=evidence_dir)

            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8")), {"status": "ok"})

    def test_missing_neo4j_dependency_raises_concise_cli_error(self):
        real_import = __import__

        def fake_import(name, *args, **kwargs):
            if name == "neo4j":
                raise ImportError("missing neo4j")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=fake_import):
            with self.assertRaisesRegex(smoke.CliError, "neo4j package is required"):
                smoke._load_driver("bolt://127.0.0.1:17687", "neo4j", "password")

    def test_write_json_rejects_existing_output_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            evidence_dir = Path(tmp) / "evidence"
            evidence_dir.mkdir()
            output_path = evidence_dir / "manifest.json"
            output_path.write_text("existing\n", encoding="utf-8")

            with self.assertRaisesRegex(smoke.OutputTargetError, "already exists"):
                smoke.write_json_exclusive(output_path, {"status": "new"}, evidence_dir=evidence_dir)

            self.assertEqual(output_path.read_text(encoding="utf-8"), "existing\n")

    def test_run_seed_cleanup_seeds_marker_fixtures_then_verifies_cleanup(self):
        driver = _FakeDriver()

        payload = smoke.run_seed_cleanup(driver, "issue155-smoke-test")

        self.assertEqual(payload["seeded_count"], 3)
        self.assertEqual(payload["cleanup"]["remaining_count"], 0)
        self.assertTrue(payload["cleanup"]["cleanup_verified"])
        all_calls = [call for session in driver.sessions for call in session.calls]
        self.assertEqual(all_calls[0][0], smoke.SEED_QUERY)
        self.assertEqual(all_calls[1][0], smoke.CLEANUP_QUERY)
        self.assertEqual(all_calls[2][0], smoke.POST_CLEANUP_QUERY)
        self.assertEqual([session.execute_write_calls for session in driver.sessions], [1, 1])
        self.assertEqual(all_calls[0][1]["fixtures"][0]["issue155_smoke_run_id"], "issue155-smoke-test")
        self.assertEqual(all_calls[1][1]["run_id"], "issue155-smoke-test")
        self.assertEqual(all_calls[2][1]["run_id"], "issue155-smoke-test")

    def test_run_seed_cleanup_executes_cleanup_after_seed_failure(self):
        driver = _FakeDriver(fail_seed=True)

        with self.assertRaisesRegex(RuntimeError, "forced seed failure"):
            smoke.run_seed_cleanup(driver, "issue155-smoke-test")

        all_calls = [call for session in driver.sessions for call in session.calls]
        self.assertEqual(all_calls[0][0], smoke.SEED_QUERY)
        self.assertEqual(all_calls[1][0], smoke.CLEANUP_QUERY)
        self.assertEqual(all_calls[2][0], smoke.POST_CLEANUP_QUERY)
        self.assertEqual(all_calls[1][1]["run_id"], "issue155-smoke-test")
        self.assertEqual(all_calls[2][1]["run_id"], "issue155-smoke-test")


if __name__ == "__main__":
    unittest.main()
