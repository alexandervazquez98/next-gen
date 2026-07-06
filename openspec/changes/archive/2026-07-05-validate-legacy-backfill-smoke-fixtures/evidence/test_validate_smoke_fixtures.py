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
    def __init__(
        self,
        fail_seed=False,
        fail_cleanup=False,
        cleanup_verified=True,
        remaining_count=0,
    ):
        self.calls = []
        self.fail_seed = fail_seed
        self.fail_cleanup = fail_cleanup
        self.cleanup_verified = cleanup_verified
        self.remaining_count = remaining_count
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
            if self.fail_cleanup:
                raise RuntimeError("forced cleanup failure")
            return _FakeResult({"deleted_count": 3})
        if query == smoke.POST_CLEANUP_QUERY:
            return _FakeResult(
                {
                    "cleanup_verified": self.cleanup_verified,
                    "remaining_count": self.remaining_count,
                }
            )
        raise AssertionError(f"unexpected query: {query}")


class _FakeDriver:
    def __init__(
        self,
        fail_seed=False,
        fail_cleanup=False,
        cleanup_verified=True,
        remaining_count=0,
    ):
        self.sessions = []
        self.fail_seed = fail_seed
        self.fail_cleanup = fail_cleanup
        self.cleanup_verified = cleanup_verified
        self.remaining_count = remaining_count

    def session(self):
        session = _FakeSession(
            fail_seed=self.fail_seed and not self.sessions,
            fail_cleanup=self.fail_cleanup and bool(self.sessions),
            cleanup_verified=self.cleanup_verified,
            remaining_count=self.remaining_count,
        )
        self.sessions.append(session)
        return session


def _assert_no_absolute_path(test_case, value):
    if isinstance(value, dict):
        for nested in value.values():
            _assert_no_absolute_path(test_case, nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_absolute_path(test_case, nested)
    elif isinstance(value, str):
        test_case.assertFalse(
            value.startswith("/"),
            f"absolute path leaked in audit metadata: {value}",
        )
        test_case.assertNotIn("/Users/", value)


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

    def test_direct_classifier_maps_fixture_plan_to_expected_buckets(self):
        fixtures = smoke.build_fixture_plan("issue155-smoke-test")

        actual = smoke.classify_fixture_buckets(fixtures)

        self.assertEqual(
            actual,
            {
                "issue155-smoke-test-safe": "safe_candidates",
                "issue155-smoke-test-ambiguous": "ambiguous_records",
                "issue155-smoke-test-no-touch": "no_touch_records",
            },
        )

    def test_validation_summary_records_expected_actual_and_audit_binding(self):
        fixtures = smoke.build_fixture_plan("issue155-smoke-test")
        audit_evidence = smoke.build_smoke_scoped_audit_evidence(
            {
                "findings": [
                    {
                        "code": "missing_event_type",
                        "field": "event_type",
                        "id": "issue155-smoke-test-ambiguous:missing_event_type",
                        "record": {"event_id": "issue155-smoke-test-ambiguous"},
                        "severity": "missing",
                    },
                    {
                        "code": "missing_failure_family",
                        "field": "failure_family",
                        "id": "issue155-smoke-test-no-touch:missing_failure_family",
                        "record": {"event_id": "issue155-smoke-test-no-touch"},
                        "severity": "missing",
                    },
                ],
                "summary": {"total_findings": 2},
            },
            {fixture["id"] for fixture in fixtures},
        )

        summary = smoke.build_validation_summary(
            fixtures,
            smoke.classify_fixture_buckets(fixtures),
            audit_evidence,
        )

        self.assertTrue(summary["valid_for_planning"])
        self.assertEqual(summary["expected_counts"], summary["actual_counts"])
        self.assertEqual(summary["mismatches"], [])
        self.assertEqual(summary["audit_evidence"]["status"], "inspected")
        self.assertEqual(summary["audit_evidence"]["missing_expected_finding_event_ids"], [])
        self.assertEqual(
            summary["safe_fixture_validation"]["source"],
            "direct classifier reuse; safe fixtures have no audit finding by design",
        )
        self.assertEqual(
            summary["recommendation_gap"]["status"],
            "gap_recorded",
        )
        self.assertIn("aggregate recommendation JSON", summary["recommendation_gap"]["description"])

    def test_validation_summary_marks_mismatched_bucket_invalid_for_planning(self):
        fixtures = smoke.build_fixture_plan("issue155-smoke-test")
        actual = smoke.classify_fixture_buckets(fixtures)
        actual["issue155-smoke-test-safe"] = "ambiguous_records"

        summary = smoke.build_validation_summary(fixtures, actual, {"findings": []})

        self.assertFalse(summary["valid_for_planning"])
        self.assertEqual(
            summary["mismatches"],
            [
                {
                    "event_id": "issue155-smoke-test-safe",
                    "expected_bucket": "safe_candidates",
                    "actual_bucket": "ambiguous_records",
                }
            ],
        )

    def test_validation_summary_requires_ambiguous_and_no_touch_audit_findings(self):
        fixtures = smoke.build_fixture_plan("issue155-smoke-test")
        audit_evidence = smoke.build_smoke_scoped_audit_evidence(
            {
                "findings": [
                    {
                        "code": "missing_event_type",
                        "field": "event_type",
                        "id": "issue155-smoke-test-ambiguous:missing_event_type",
                        "record": {"event_id": "issue155-smoke-test-ambiguous"},
                        "severity": "missing",
                    }
                ],
                "summary": {"total_findings": 1},
            },
            {fixture["id"] for fixture in fixtures},
        )

        summary = smoke.build_validation_summary(
            fixtures,
            smoke.classify_fixture_buckets(fixtures),
            audit_evidence,
        )

        self.assertFalse(summary["valid_for_planning"])
        self.assertEqual(
            summary["audit_evidence"]["missing_expected_finding_event_ids"],
            ["issue155-smoke-test-no-touch"],
        )

    def test_smoke_scoped_audit_evidence_omits_non_smoke_details_and_raw_counts(self):
        raw_audit = {
            "findings": [
                {
                    "code": "missing_event_type",
                    "field": "event_type",
                    "id": "issue155-smoke-test-ambiguous:missing_event_type",
                    "record": {
                        "event_id": "issue155-smoke-test-ambiguous",
                        "message": "smoke fixture text",
                    },
                    "severity": "missing",
                },
                {
                    "code": "missing_event_type",
                    "field": "event_type",
                    "id": "prod-like-event:missing_event_type",
                    "record": {
                        "event_id": "prod-like-event",
                        "message": "sensitive non-smoke message",
                        "metric_name": "non-smoke metric",
                        "created_at": "2026-07-05T12:00:00Z",
                    },
                    "severity": "missing",
                },
            ],
            "summary": {"total_findings": 2},
        }

        evidence = smoke.build_smoke_scoped_audit_evidence(raw_audit, {"issue155-smoke-test-ambiguous"})

        self.assertEqual(evidence["summary"]["smoke_findings_count"], 1)
        self.assertEqual(evidence["findings"][0]["event_id"], "issue155-smoke-test-ambiguous")
        serialized = json.dumps(evidence, sort_keys=True)
        self.assertNotIn("raw_total_findings", serialized)
        self.assertNotIn("omitted_non_smoke_findings_count", serialized)
        self.assertNotIn("prod-like-event", serialized)
        self.assertNotIn("sensitive non-smoke message", serialized)
        self.assertNotIn("non-smoke metric", serialized)
        self.assertNotIn("2026-07-05T12:00:00Z", serialized)

    def test_audit_json_command_persists_smoke_scoped_output_with_safe_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            evidence_dir = Path(tmp) / "evidence"
            evidence_dir.mkdir()
            output_path = evidence_dir / "smoke-audit.json"

            with mock.patch.object(smoke.subprocess, "run") as run:
                def fake_run(command, **kwargs):
                    raw_output = Path(command[-1])
                    raw_output.write_text(
                        json.dumps(
                            {
                                "findings": [
                                    {
                                        "code": "missing_event_type",
                                        "field": "event_type",
                                        "id": "issue155-smoke-test-ambiguous:missing_event_type",
                                        "record": {"event_id": "issue155-smoke-test-ambiguous"},
                                        "severity": "missing",
                                    },
                                    {
                                        "code": "missing_event_type",
                                        "field": "event_type",
                                        "id": "non-smoke:missing_event_type",
                                        "record": {"event_id": "non-smoke", "message": "do not persist"},
                                        "severity": "missing",
                                    },
                                ],
                                "summary": {"total_findings": 2},
                            }
                        ),
                        encoding="utf-8",
                    )
                    return mock.Mock(returncode=0, stdout="", stderr="")

                run.side_effect = fake_run

                result = smoke.run_audit_json_report(
                    output_path,
                    smoke_event_ids={"issue155-smoke-test-ambiguous"},
                    neo4j_uri="bolt://127.0.0.1:17687",
                    neo4j_user="neo4j",
                    neo4j_password="local-secret",
                    repo_root=Path("/repo"),
                    evidence_dir=evidence_dir,
                )

            self.assertEqual(result["report"], "audit")
            self.assertEqual(result["format"], "json")
            self.assertEqual(result["output"], "smoke-audit.json")
            self.assertEqual(result["output_path_kind"], "evidence-relative")
            _assert_no_absolute_path(self, result)
            persisted = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["summary"]["smoke_findings_count"], 1)
            persisted_text = json.dumps(persisted, sort_keys=True)
            result_text = json.dumps(result, sort_keys=True)
            self.assertNotIn("non-smoke:missing_event_type", persisted_text)
            self.assertNotIn("do not persist", persisted_text)
            self.assertNotIn("raw_total_findings", persisted_text)
            self.assertNotIn("omitted_non_smoke_findings_count", persisted_text)
            self.assertNotIn("local-secret", persisted_text)
            self.assertNotIn("local-secret", result_text)
            self.assertNotIn("NEO4J_PASSWORD", result_text)
        self.assertEqual(result["stdout_captured"], False)
        self.assertEqual(result["stderr_captured"], False)
        self.assertNotIn("stdout", result)
        self.assertNotIn("stderr", result)
        self.assertEqual(result["command"], [
            "python3",
            "backend/scripts/audit_legacy_event_discriminators.py",
            "--report",
            "audit",
            "--format",
            "json",
            "--output",
            "<temporary-broad-audit-json>",
        ])
        self.assertEqual(run.call_args.args[0][0], smoke.PYTHON_EXECUTABLE)
        self.assertEqual(run.call_args.kwargs["cwd"], Path("/repo"))
        self.assertTrue(run.call_args.kwargs["capture_output"])
        self.assertEqual(
            run.call_args.kwargs["env"]["NEO4J_URI"],
            "bolt://127.0.0.1:17687",
        )
        self.assertEqual(run.call_args.kwargs["env"]["NEO4J_USER"], "neo4j")
        self.assertEqual(run.call_args.kwargs["env"]["NEO4J_PASSWORD"], "local-secret")

    def test_audit_json_command_rejects_non_local_target_before_subprocess(self):
        with tempfile.TemporaryDirectory() as tmp:
            evidence_dir = Path(tmp) / "evidence"
            evidence_dir.mkdir()

            with mock.patch.object(smoke.subprocess, "run") as run:
                with self.assertRaisesRegex(smoke.UnsafeTargetError, "shared local Neo4j"):
                    smoke.run_audit_json_report(
                        evidence_dir / "smoke-audit.json",
                        smoke_event_ids={"issue155-smoke-test-ambiguous"},
                        neo4j_uri="bolt://prod.example.com:7687",
                        neo4j_user="neo4j",
                        neo4j_password="local-secret",
                        repo_root=Path("/repo"),
                        evidence_dir=evidence_dir,
                    )

            run.assert_not_called()

    def test_run_seed_cleanup_executes_cleanup_after_audit_generation_failure(self):
        driver = _FakeDriver()

        with mock.patch.object(smoke, "run_audit_json_report", side_effect=smoke.CliError("audit failed")):
            with self.assertRaisesRegex(smoke.CliError, "audit failed"):
                smoke.run_seed_cleanup(driver, "issue155-smoke-test", audit_json_output="smoke-audit.json")

        all_calls = [call for session in driver.sessions for call in session.calls]
        self.assertEqual(all_calls[0][0], smoke.SEED_QUERY)
        self.assertEqual(all_calls[1][0], smoke.CLEANUP_QUERY)
        self.assertEqual(all_calls[2][0], smoke.POST_CLEANUP_QUERY)

    def test_run_seed_cleanup_executes_cleanup_after_classifier_failure(self):
        driver = _FakeDriver()
        with tempfile.TemporaryDirectory() as tmp:
            evidence_dir = Path(tmp) / "evidence"
            evidence_dir.mkdir()
            audit_path = evidence_dir / "smoke-audit.json"
            audit_path.write_text(
                json.dumps(
                    smoke.build_smoke_scoped_audit_evidence(
                        {"findings": [], "summary": {"total_findings": 0}},
                        set(),
                    )
                ),
                encoding="utf-8",
            )

            with mock.patch.object(
                smoke,
                "run_audit_json_report",
                return_value={"output": "smoke-audit.json", "output_path_kind": "evidence-relative"},
            ), mock.patch.object(
                smoke,
                "classify_fixture_buckets",
                side_effect=RuntimeError("classifier failed"),
            ), mock.patch.object(smoke, "EVIDENCE_DIR", evidence_dir):
                with self.assertRaisesRegex(RuntimeError, "classifier failed"):
                    smoke.run_seed_cleanup(
                        driver,
                        "issue155-smoke-test",
                        audit_json_output="smoke-audit.json",
                    )

        all_calls = [call for session in driver.sessions for call in session.calls]
        self.assertEqual(all_calls[0][0], smoke.SEED_QUERY)
        self.assertEqual(all_calls[1][0], smoke.CLEANUP_QUERY)
        self.assertEqual(all_calls[2][0], smoke.POST_CLEANUP_QUERY)

    def test_run_seed_cleanup_reports_cleanup_failure_after_prior_error(self):
        driver = _FakeDriver(fail_cleanup=True)

        with mock.patch.object(smoke, "run_audit_json_report", side_effect=smoke.CliError("audit failed")):
            with self.assertRaisesRegex(RuntimeError, "cleanup failed after prior error"):
                smoke.run_seed_cleanup(driver, "issue155-smoke-test", audit_json_output="smoke-audit.json")

        all_calls = [call for session in driver.sessions for call in session.calls]
        self.assertEqual(all_calls[0][0], smoke.SEED_QUERY)
        self.assertEqual(all_calls[1][0], smoke.CLEANUP_QUERY)

    def test_run_seed_cleanup_reports_cleanup_verification_failure_after_audit_error(self):
        driver = _FakeDriver(cleanup_verified=False, remaining_count=2)

        with mock.patch.object(smoke, "run_audit_json_report", side_effect=smoke.CliError("audit failed")):
            with self.assertRaisesRegex(RuntimeError, "cleanup verification failed"):
                smoke.run_seed_cleanup(driver, "issue155-smoke-test", audit_json_output="smoke-audit.json")

        all_calls = [call for session in driver.sessions for call in session.calls]
        self.assertEqual(all_calls[0][0], smoke.SEED_QUERY)
        self.assertEqual(all_calls[1][0], smoke.CLEANUP_QUERY)
        self.assertEqual(all_calls[2][0], smoke.POST_CLEANUP_QUERY)

    def test_run_seed_cleanup_reports_cleanup_verification_failure_after_classifier_error(self):
        driver = _FakeDriver(cleanup_verified=False, remaining_count=1)
        with tempfile.TemporaryDirectory() as tmp:
            evidence_dir = Path(tmp) / "evidence"
            evidence_dir.mkdir()
            audit_path = evidence_dir / "smoke-audit.json"
            audit_path.write_text(
                json.dumps(
                    smoke.build_smoke_scoped_audit_evidence(
                        {"findings": [], "summary": {"total_findings": 0}},
                        set(),
                    )
                ),
                encoding="utf-8",
            )

            with mock.patch.object(
                smoke,
                "run_audit_json_report",
                return_value={"output": "smoke-audit.json", "output_path_kind": "evidence-relative"},
            ), mock.patch.object(
                smoke,
                "classify_fixture_buckets",
                side_effect=RuntimeError("classifier failed"),
            ), mock.patch.object(smoke, "EVIDENCE_DIR", evidence_dir):
                with self.assertRaisesRegex(RuntimeError, "cleanup verification failed"):
                    smoke.run_seed_cleanup(
                        driver,
                        "issue155-smoke-test",
                        audit_json_output="smoke-audit.json",
                    )

        all_calls = [call for session in driver.sessions for call in session.calls]
        self.assertEqual(all_calls[0][0], smoke.SEED_QUERY)
        self.assertEqual(all_calls[1][0], smoke.CLEANUP_QUERY)
        self.assertEqual(all_calls[2][0], smoke.POST_CLEANUP_QUERY)


if __name__ == "__main__":
    unittest.main()
