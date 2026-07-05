import json
import re

from services.legacy_event_discriminator_audit import (
    classify_legacy_event_records,
    result_to_json_dict,
    result_to_markdown,
    run_legacy_event_discriminator_audit,
)


def legacy_record(**overrides):
    record = {
        "event_id": "event-1",
        "ci_id": "ci-1",
        "metric_id": "metric-1",
        "status": "OPEN",
        "severity": "WARNING",
        "message": "Metric Collection Failed: Timeout waiting for SNMP response",
        "event_type": "COLLECTION_FAILURE",
        "failure_family": "SNMP_NO_RESPONSE",
        "source_protocol": "SNMP",
        "availability_source": None,
        "created_at": "2026-07-01T00:00:00Z",
        "last_seen": "2026-07-01T00:05:00Z",
        "ci_name": "Core Router",
        "metric_name": "SNMP Uptime",
    }
    record.update(overrides)
    return record


def finding_codes(result):
    return [finding.code for finding in result.findings]


def finding_keys(result):
    return [(finding.record.event_id, finding.code) for finding in result.findings]


def test_classifies_missing_discriminator_fields_independently():
    result = classify_legacy_event_records(
        [
            legacy_record(
                event_id="event-missing", event_type=None, failure_family=None, source_protocol=None
            )
        ]
    )

    assert finding_codes(result) == [
        "ambiguous_collection_failure_boundary",
        "missing_event_type",
        "missing_failure_family",
        "missing_source_protocol",
    ]
    assert result.summary.total_records == 1
    assert result.summary.total_findings == 4
    assert result.summary.findings_by_code == {
        "ambiguous_collection_failure_boundary": 1,
        "missing_event_type": 1,
        "missing_failure_family": 1,
        "missing_source_protocol": 1,
    }
    assert all(finding.record.event_id == "event-missing" for finding in result.findings)


def test_populated_discriminators_are_not_reported_as_missing():
    result = classify_legacy_event_records([legacy_record(event_id="event-complete")])

    assert result.findings == []
    assert result.summary.total_records == 1
    assert result.summary.total_findings == 0


def test_classifies_legacy_null_ambiguity_boundaries_without_definitive_values():
    result = classify_legacy_event_records(
        [
            legacy_record(
                event_id="event-threshold-or-availability",
                event_type=None,
                failure_family=None,
                source_protocol="ICMP",
                availability_source="PING",
                message="Service/Host Down: WAN Reachability",
            ),
            legacy_record(
                event_id="event-generic-or-snmp",
                event_type=None,
                failure_family=None,
                source_protocol=None,
                message="Metric Collection Failed: Timeout",
            ),
        ]
    )

    ambiguous = [finding for finding in result.findings if finding.severity == "ambiguous"]
    assert [finding.code for finding in ambiguous] == [
        "ambiguous_collection_failure_boundary",
        "ambiguous_threshold_or_availability",
    ]
    assert all(finding.recommended_value is None for finding in ambiguous)
    assert "SNMP no-response" in ambiguous[0].description
    assert "threshold or availability" in ambiguous[1].description


def test_outputs_are_deterministic_and_share_ordered_result_model():
    records = [
        legacy_record(event_id="event-z", ci_id="ci-2", metric_id="metric-9", event_type=None),
        legacy_record(event_id="event-a", ci_id="ci-1", metric_id="metric-1", source_protocol=None),
        legacy_record(event_id="event-m", ci_id="ci-1", metric_id="metric-1", failure_family=None),
    ]

    first = classify_legacy_event_records(records)
    second = classify_legacy_event_records(reversed(records))
    json_payload = result_to_json_dict(first)
    markdown = result_to_markdown(first)

    assert finding_keys(first) == finding_keys(second)
    assert [item["id"] for item in json_payload["findings"]] == [
        finding.finding_id for finding in first.findings
    ]
    assert [item["code"] for item in json_payload["findings"]] == finding_codes(first)
    assert f"Total records: {first.summary.total_records}" in markdown
    assert f"Total findings: {first.summary.total_findings}" in markdown
    for finding in first.findings:
        assert finding.finding_id in markdown
        assert finding.code in markdown
    assert json.dumps(json_payload, sort_keys=True) == json.dumps(
        result_to_json_dict(first), sort_keys=True
    )


def test_empty_results_render_stable_json_and_markdown():
    result = classify_legacy_event_records([])

    json_payload = result_to_json_dict(result)
    markdown = result_to_markdown(result)

    assert json_payload == {
        "summary": {
            "total_records": 0,
            "total_findings": 0,
            "findings_by_code": {},
        },
        "findings": [],
    }
    assert "- Total records: 0" in markdown
    assert "- Total findings: 0" in markdown
    assert "### Findings by Code\n- None" in markdown
    assert "No legacy discriminator risks found." in markdown


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class FakeTransaction:
    def __init__(self, session):
        self.session = session

    def run(self, query, **parameters):
        return self.session.run(query, **parameters)


class FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []
        self.execute_read_calls = 0
        self.read_transaction_calls = 0
        self.closed = False

    def run(self, query, **parameters):
        self.queries.append((query, parameters))
        return FakeResult(self.rows)

    def execute_read(self, callback):
        self.execute_read_calls += 1
        return callback(FakeTransaction(self))

    def read_transaction(self, callback):
        self.read_transaction_calls += 1
        return callback(FakeTransaction(self))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.closed = True


class FakeDriver:
    def __init__(self, rows):
        self.session_obj = FakeSession(rows)
        self.session_kwargs = []

    def session(self, **kwargs):
        self.session_kwargs.append(kwargs)
        return self.session_obj


def test_read_only_runner_uses_match_query_and_classifies_rows():
    driver = FakeDriver(
        [
            legacy_record(
                event_id="event-read", event_type=None, failure_family=None, source_protocol=None
            )
        ]
    )

    result = run_legacy_event_discriminator_audit(driver, limit=25)

    query, parameters = driver.session_obj.queries[0]
    assert "MATCH" in query
    assert driver.session_obj.execute_read_calls == 1
    assert driver.session_obj.read_transaction_calls == 0
    try:
        from neo4j import READ_ACCESS
    except ImportError:
        expected_session_kwargs = {}
    else:
        expected_session_kwargs = {"default_access_mode": READ_ACCESS}
    assert driver.session_kwargs == [expected_session_kwargs]
    for mutation_clause in ("SET", "DELETE", "CREATE", "MERGE", "REMOVE", "DETACH"):
        assert re.search(rf"\b{mutation_clause}\b", query, flags=re.IGNORECASE) is None
    assert parameters == {"limit": 25}
    assert result.summary.total_records == 1
    assert "missing_event_type" in finding_codes(result)
    assert driver.session_obj.closed is True
