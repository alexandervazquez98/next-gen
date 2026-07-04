from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = BACKEND_ROOT / "tests"
EXCLUDED_DISCOVERY_DIRS = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "env",
    "htmlcov",
    "node_modules",
    "site-packages",
    "support",
    "tests",
    "vendor",
    "venv",
}


@dataclass(frozen=True)
class ProtectedWriterEvidence:
    path: str
    rationale: str
    evidence_tests: tuple[str, ...]
    lock_symbols_or_wrappers: tuple[str, ...]


PROTECTED_EVENT_WRITERS = {
    "services/snmp_service.py": ProtectedWriterEvidence(
        path="services/snmp_service.py",
        rationale="legacy SNMP writer for polling Event deduplication",
        evidence_tests=(
            "tests/test_snmp_service_collection_failures.py",
            "tests/test_writer_advisory_lock.py",
        ),
        lock_symbols_or_wrappers=("acquire_event_triplet_lock",),
    ),
    "engines/snmp_worker.py": ProtectedWriterEvidence(
        path="engines/snmp_worker.py",
        rationale="external SNMP worker Event writer",
        evidence_tests=("tests/test_snmp_worker.py", "tests/test_writer_advisory_lock.py"),
        lock_symbols_or_wrappers=("acquire_event_triplet_lock",),
    ),
    "polling/event_writer.py": ProtectedWriterEvidence(
        path="polling/event_writer.py",
        rationale="queue polling Event writer",
        evidence_tests=("tests/test_polling_event_writer.py", "tests/test_writer_advisory_lock.py"),
        lock_symbols_or_wrappers=("_acquire_sorted_locks",),
    ),
}

EXEMPT_EVENT_EMITTERS = {
    "engines/cli_worker.py": "CLI_POLL_ALERT operational health emitter, not polling triplet deduplication",
    "services/backup_service.py": "SYSTEM/BACKUP administrative status emitter, not metric polling deduplication",
}

_CLAUSE_START_RE = re.compile(r"\b(?:CREATE|MERGE|FOREACH)\b", re.IGNORECASE)
_CLAUSE_BOUNDARY_RE = re.compile(
    r"\b(?:MATCH|OPTIONAL\s+MATCH|WITH|RETURN|SET|DELETE|DETACH\s+DELETE|UNWIND|CALL)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class EventCreationSpan:
    text: str
    start: int
    line: int


@dataclass(frozen=True)
class ClassificationResult:
    unclassified: set[str]
    overlap: set[str]

    @property
    def failure_message(self) -> str:
        parts: list[str] = []
        if self.unclassified:
            parts.append(
                "Unclassified production Event emitter(s): "
                f"{', '.join(sorted(self.unclassified))}. Register each module in "
                "PROTECTED_EVENT_WRITERS with lock evidence metadata or in "
                "EXEMPT_EVENT_EMITTERS with an exemption rationale."
            )
        if self.overlap:
            parts.append(
                "Event emitter(s) classified as both protected and exempt: "
                f"{', '.join(sorted(self.overlap))}. A writer must appear in exactly one registry."
            )
        return "\n".join(parts)


def _line_number(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


def find_event_creation_spans(source: str) -> list[EventCreationSpan]:
    """Return Cypher CREATE/MERGE/FOREACH spans that create Event nodes."""
    spans: list[EventCreationSpan] = []
    starts = list(_CLAUSE_START_RE.finditer(source))

    for index, match in enumerate(starts):
        next_start = starts[index + 1].start() if index + 1 < len(starts) else len(source)
        boundary = _CLAUSE_BOUNDARY_RE.search(source, match.end(), next_start)
        end = boundary.start() if boundary else next_start
        clause = source[match.start() : end]
        if ":Event" in clause:
            spans.append(
                EventCreationSpan(
                    clause.strip(), match.start(), _line_number(source, match.start())
                )
            )

    return spans


def _is_production_python_path(path: Path, backend_root: Path) -> bool:
    if path.suffix != ".py":
        return False
    relative_parts = path.relative_to(backend_root).parts
    return not any(part in EXCLUDED_DISCOVERY_DIRS for part in relative_parts)


def _iter_production_python_paths(backend_root: Path) -> list[Path]:
    return sorted(
        path
        for path in backend_root.rglob("*.py")
        if _is_production_python_path(path, backend_root)
    )


def discover_event_emitter_paths(backend_root: Path = BACKEND_ROOT) -> set[str]:
    discovered: set[str] = set()
    for path in _iter_production_python_paths(backend_root):
        source = path.read_text(encoding="utf-8")
        if find_event_creation_spans(source):
            discovered.add(path.relative_to(backend_root).as_posix())
    return discovered


def classify_event_emitters(discovered: set[str]) -> ClassificationResult:
    protected = set(PROTECTED_EVENT_WRITERS)
    exempt = set(EXEMPT_EVENT_EMITTERS)
    return ClassificationResult(
        unclassified=discovered - protected - exempt,
        overlap=protected & exempt,
    )


def _registry_path_to_backend_file(path: str, backend_root: Path = BACKEND_ROOT) -> Path:
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(
            f"Registry path must be backend-relative and contained in backend/: {path}"
        )
    resolved_root = backend_root.resolve()
    resolved = (resolved_root / candidate).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ValueError(f"Registry path escapes backend/: {path}")
    return resolved


def _evidence_test_to_file(path: str, backend_root: Path = BACKEND_ROOT) -> Path:
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts or candidate.parts[:1] != ("tests",):
        raise ValueError(f"Evidence test must be a backend/tests relative path: {path}")
    resolved_tests_root = (
        TESTS_ROOT.resolve() if backend_root == BACKEND_ROOT else (backend_root / "tests").resolve()
    )
    resolved = (backend_root / candidate).resolve()
    if not resolved.is_relative_to(resolved_tests_root):
        raise ValueError(f"Evidence test escapes backend/tests/: {path}")
    return resolved


def validate_protected_writer_evidence(
    protected_writers: dict[str, ProtectedWriterEvidence] = PROTECTED_EVENT_WRITERS,
    backend_root: Path = BACKEND_ROOT,
) -> list[str]:
    failures: list[str] = []
    for registry_path, evidence in protected_writers.items():
        if registry_path != evidence.path:
            failures.append(f"{registry_path}: evidence.path must match the registry key")
        try:
            writer_file = _registry_path_to_backend_file(registry_path, backend_root)
        except ValueError as exc:
            failures.append(str(exc))
            writer_file = None
        protected_source_available = False
        if writer_file is not None:
            if not writer_file.exists():
                failures.append(f"{registry_path}: protected writer source does not exist")
                protected_source = ""
            else:
                protected_source = writer_file.read_text(encoding="utf-8")
                protected_source_available = True
        else:
            protected_source = ""
        if not evidence.rationale.strip():
            failures.append(f"{registry_path}: rationale is required")
        if not evidence.evidence_tests or any(not item.strip() for item in evidence.evidence_tests):
            failures.append(
                f"{registry_path}: at least one non-empty evidence_tests reference is required"
            )
        for evidence_test in evidence.evidence_tests:
            try:
                evidence_file = _evidence_test_to_file(evidence_test, backend_root)
            except ValueError as exc:
                failures.append(f"{registry_path}: {exc}")
                continue
            if not evidence_file.exists():
                failures.append(f"{registry_path}: evidence test does not exist: {evidence_test}")
        if not evidence.lock_symbols_or_wrappers or any(
            not item.strip() for item in evidence.lock_symbols_or_wrappers
        ):
            failures.append(f"{registry_path}: lock_symbols_or_wrappers is required")
        for symbol in evidence.lock_symbols_or_wrappers:
            if symbol.strip() and protected_source_available and symbol not in protected_source:
                failures.append(
                    f"{registry_path}: protected source is missing claimed lock evidence: {symbol}"
                )
        if (
            registry_path == "polling/event_writer.py"
            and "_acquire_sorted_locks" not in evidence.lock_symbols_or_wrappers
        ):
            failures.append(
                "polling/event_writer.py: _acquire_sorted_locks is the approved wrapper evidence"
            )
        if evidence.lock_symbols_or_wrappers == ("_acquire_unsorted_locks",):
            failures.append(
                f"{registry_path}: _acquire_unsorted_locks alone is not approved wrapper evidence"
            )
    return failures


def test_event_creation_discovery_handles_multiline_cypher_shapes():
    source = """
        session.run('''
            MATCH (ci:CI {id: $ci_id})
            CREATE (ci)-[:HAS_EVENT]->
                   (event:Event {
                     id: randomUUID()
                   })
        ''')

        session.run('''
            MERGE
              (:Event {id: $event_id})
        ''')

        session.run('''
            FOREACH (_ IN CASE WHEN missing THEN [1] ELSE [] END |
                CREATE (created:Event {id: randomUUID()})
            )
        ''')
    """

    spans = find_event_creation_spans(source)

    assert len(spans) == 3
    assert all(":Event" in span.text for span in spans)


def test_event_creation_discovery_ignores_read_only_match():
    source = """
        session.run('''
            MATCH (event:Event {id: $event_id})
            RETURN event
        ''')
    """

    assert find_event_creation_spans(source) == []


def test_production_python_discovery_excludes_tests_and_support_paths(tmp_path: Path):
    backend_root = tmp_path / "backend"
    (backend_root / "services").mkdir(parents=True)
    (backend_root / "tests").mkdir(parents=True)
    (backend_root / "support").mkdir(parents=True)
    (backend_root / "services" / "writer.py").write_text(
        "session.run('CREATE (e:Event {id: randomUUID()})')\n",
        encoding="utf-8",
    )
    (backend_root / "tests" / "test_writer.py").write_text(
        "session.run('CREATE (e:Event {id: randomUUID()})')\n",
        encoding="utf-8",
    )
    (backend_root / "support" / "fixture.py").write_text(
        "session.run('CREATE (e:Event {id: randomUUID()})')\n",
        encoding="utf-8",
    )

    discovered = discover_event_emitter_paths(backend_root)

    assert discovered == {"services/writer.py"}


def test_production_python_discovery_ignores_local_virtualenv_and_cache_trees(tmp_path: Path):
    backend_root = tmp_path / "backend"
    (backend_root / "services").mkdir(parents=True)
    (backend_root / ".venv" / "lib").mkdir(parents=True)
    (backend_root / "venv" / "lib").mkdir(parents=True)
    (backend_root / ".pytest_cache").mkdir(parents=True)
    (backend_root / "services" / "writer.py").write_text(
        "session.run('CREATE (e:Event {id: randomUUID()})')\n",
        encoding="utf-8",
    )
    (backend_root / ".venv" / "lib" / "shadow_writer.py").write_text(
        "session.run('CREATE (e:Event {id: randomUUID()})')\n",
        encoding="utf-8",
    )
    (backend_root / "venv" / "lib" / "shadow_writer.py").write_text(
        "session.run('CREATE (e:Event {id: randomUUID()})')\n",
        encoding="utf-8",
    )
    (backend_root / ".pytest_cache" / "shadow_writer.py").write_text(
        "session.run('CREATE (e:Event {id: randomUUID()})')\n",
        encoding="utf-8",
    )

    discovered = discover_event_emitter_paths(backend_root)

    assert discovered == {"services/writer.py"}


def test_discovered_event_emitters_are_classified_exactly_once():
    result = classify_event_emitters(discover_event_emitter_paths(BACKEND_ROOT))

    assert result.overlap == set(), result.failure_message
    assert result.unclassified == set(), result.failure_message


def test_classification_fails_for_unclassified_emitters_with_actionable_message():
    result = classify_event_emitters({"services/new_writer.py"})

    assert result.unclassified == {"services/new_writer.py"}
    assert "services/new_writer.py" in result.failure_message
    assert "PROTECTED_EVENT_WRITERS" in result.failure_message
    assert "EXEMPT_EVENT_EMITTERS" in result.failure_message


def test_classification_fails_for_protected_exempt_overlap_with_actionable_message(
    monkeypatch,
):
    monkeypatch.setitem(EXEMPT_EVENT_EMITTERS, "services/snmp_service.py", "bad overlap")

    result = classify_event_emitters({"services/snmp_service.py"})

    assert result.overlap == {"services/snmp_service.py"}
    assert "services/snmp_service.py" in result.failure_message
    assert "both protected and exempt" in result.failure_message


def test_exempt_emitters_have_backend_relative_paths_and_non_empty_rationales():
    assert EXEMPT_EVENT_EMITTERS
    for path, rationale in EXEMPT_EVENT_EMITTERS.items():
        assert path.endswith(".py")
        assert not path.startswith("backend/")
        assert not Path(path).is_absolute()
        assert rationale.strip(), f"{path} must document its exemption rationale"
        _registry_path_to_backend_file(path)


def test_registry_paths_are_normalized_and_must_stay_inside_backend(tmp_path: Path):
    backend_root = tmp_path / "backend"
    (backend_root / "services").mkdir(parents=True)
    writer = backend_root / "services" / "writer.py"
    writer.write_text("", encoding="utf-8")

    assert _registry_path_to_backend_file("services/writer.py", backend_root) == writer.resolve()

    rejected_paths = ["../outside.py", "/tmp/outside.py", "services/../../outside.py"]
    for path in rejected_paths:
        try:
            _registry_path_to_backend_file(path, backend_root)
        except ValueError as exc:
            assert path in str(exc)
        else:
            raise AssertionError(f"{path} should be rejected")


def test_protected_writer_entries_include_required_evidence_metadata():
    assert set(PROTECTED_EVENT_WRITERS) == {
        "services/snmp_service.py",
        "engines/snmp_worker.py",
        "polling/event_writer.py",
    }

    failures = validate_protected_writer_evidence()

    assert failures == []


def test_evidence_tests_must_resolve_under_backend_tests(tmp_path: Path):
    backend_root = tmp_path / "backend"
    (backend_root / "tests").mkdir(parents=True)
    (backend_root / "tests" / "test_writer.py").write_text("", encoding="utf-8")
    evidence = {
        "services/writer.py": ProtectedWriterEvidence(
            path="services/writer.py",
            rationale="polling writer",
            evidence_tests=(
                "tests/test_writer.py",
                "/tmp/test_escape.py",
                "tests/../escape.py",
                "support/test_writer.py",
            ),
            lock_symbols_or_wrappers=("acquire_event_triplet_lock",),
        )
    }

    failures = validate_protected_writer_evidence(evidence, backend_root)

    assert any("/tmp/test_escape.py" in failure for failure in failures)
    assert any("tests/../escape.py" in failure for failure in failures)
    assert any("support/test_writer.py" in failure for failure in failures)
    assert not any("tests/test_writer.py" in failure for failure in failures)


def test_missing_evidence_metadata_fails_with_writer_name(tmp_path: Path):
    backend_root = tmp_path / "backend"
    (backend_root / "tests").mkdir(parents=True)
    evidence = {
        "services/writer.py": ProtectedWriterEvidence(
            path="services/writer.py",
            rationale="",
            evidence_tests=("",),
            lock_symbols_or_wrappers=(),
        )
    }

    failures = validate_protected_writer_evidence(evidence, backend_root)

    assert any("services/writer.py: rationale is required" in failure for failure in failures)
    assert any(
        "services/writer.py: at least one non-empty evidence_tests" in failure
        for failure in failures
    )
    assert any(
        "services/writer.py: lock_symbols_or_wrappers is required" in failure
        for failure in failures
    )


def test_protected_writer_claimed_lock_evidence_must_exist_in_source(tmp_path: Path):
    backend_root = tmp_path / "backend"
    (backend_root / "services").mkdir(parents=True)
    (backend_root / "tests").mkdir(parents=True)
    (backend_root / "services" / "writer.py").write_text(
        "def write_event():\n    return True\n",
        encoding="utf-8",
    )
    (backend_root / "tests" / "test_writer.py").write_text("", encoding="utf-8")
    evidence = {
        "services/writer.py": ProtectedWriterEvidence(
            path="services/writer.py",
            rationale="polling writer",
            evidence_tests=("tests/test_writer.py",),
            lock_symbols_or_wrappers=("acquire_event_triplet_lock",),
        )
    }

    failures = validate_protected_writer_evidence(evidence, backend_root)

    assert any(
        "services/writer.py: protected source is missing claimed lock evidence: acquire_event_triplet_lock"
        in failure
        for failure in failures
    )


def test_polling_event_writer_accepts_sorted_wrapper_and_rejects_unsorted_alone(tmp_path: Path):
    backend_root = tmp_path / "backend"
    (backend_root / "polling").mkdir(parents=True)
    (backend_root / "tests").mkdir(parents=True)
    (backend_root / "polling" / "event_writer.py").write_text(
        "def _acquire_sorted_locks():\n    return True\n\n"
        "def _acquire_unsorted_locks():\n    return True\n",
        encoding="utf-8",
    )
    (backend_root / "tests" / "test_polling_event_writer.py").write_text("", encoding="utf-8")
    sorted_evidence = {
        "polling/event_writer.py": ProtectedWriterEvidence(
            path="polling/event_writer.py",
            rationale="queue polling Event writer",
            evidence_tests=("tests/test_polling_event_writer.py",),
            lock_symbols_or_wrappers=("_acquire_sorted_locks",),
        )
    }
    unsorted_evidence = {
        "polling/event_writer.py": ProtectedWriterEvidence(
            path="polling/event_writer.py",
            rationale="queue polling Event writer",
            evidence_tests=("tests/test_polling_event_writer.py",),
            lock_symbols_or_wrappers=("_acquire_unsorted_locks",),
        )
    }

    assert validate_protected_writer_evidence(sorted_evidence, backend_root) == []
    failures = validate_protected_writer_evidence(unsorted_evidence, backend_root)

    assert any(
        "_acquire_sorted_locks is the approved wrapper evidence" in failure for failure in failures
    )
    assert any("_acquire_unsorted_locks alone is not approved" in failure for failure in failures)
