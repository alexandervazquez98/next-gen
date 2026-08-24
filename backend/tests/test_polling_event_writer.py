from datetime import UTC, datetime, timedelta

from tests.conftest import MockNeo4jDriver


def _event_row(value: float | None = 97.0, status="OK", metadata=None):
    return {
        "idempotency_key": None,
        "ci_id": "ci-1",
        "metric_id": "cpu",
        "protocol": "SNMP",
        "source": "10.0.0.1:161/1.2.3",
        "observed_at": datetime(2026, 1, 1, tzinfo=UTC),
        "status": status,
        "value": {"numeric": value, "raw": value},
        "error": {"message": None},
        "metadata": metadata or {"critical": 90, "warning": 80, "criticality": 3, "operator": ">="},
    }


def test_event_writer_ignores_icmp_latency_and_jitter_as_availability_events():
    from polling.event_writer import build_event_rows

    rows = build_event_rows(
        [
            {
                **_event_row(0.0),
                "protocol": "ICMP",
                "metric_id": "PING-CHECK",
                "metadata": {"name": "PING-CHECK", "criticality": 3, "availability_source": "PING"},
            },
            {
                **_event_row(0.0),
                "protocol": "ICMP",
                "metric_id": "PING-router",
                "metadata": {
                    "name": "PING-router",
                    "criticality": 3,
                    "availability_source": "ICMP",
                },
            },
            {
                **_event_row(0.0),
                "protocol": "ICMP",
                "metric_id": "icmp_latency_ms",
                "metadata": {"name": "ICMP Latency", "criticality": 3},
            },
            {
                **_event_row(0.0),
                "protocol": "ICMP",
                "metric_id": "icmp_jitter_ms",
                "metadata": {"name": "ICMP Jitter", "criticality": 3},
            },
            {
                **_event_row(0.0),
                "protocol": "ICMP",
                "metric_id": "icmp_latency_ms",
                "metadata": {
                    "name": "ICMP Latency",
                    "criticality": 3,
                    "metric_kind": "availability",
                },
            },
            {
                **_event_row(0.0),
                "protocol": "ICMP",
                "metric_id": "icmp_jitter_ms",
                "metadata": {
                    "name": "ICMP Jitter",
                    "criticality": 3,
                    "metric_kind": "availability",
                },
            },
        ]
    )

    assert rows[0]["event_type"] == "AVAILABILITY"
    assert rows[1]["event_type"] == "AVAILABILITY"
    for row in rows[2:]:
        assert row["event_type"] is None
        assert row["is_breach"] is False


def test_event_writer_requires_explicit_availability_source_tag():
    from polling.event_writer import build_event_rows

    rows = build_event_rows(
        [
            {
                **_event_row(0.0),
                "protocol": "ICMP",
                "metric_id": "PING-CHECK",
                "metadata": {"name": "PING-CHECK", "criticality": 3},
            },
            {
                **_event_row(0.0),
                "protocol": "SNMP",
                "metric_id": "mariadb-GS",
                "metadata": {"name": "mariadb-GS", "criticality": 3},
            },
            {
                **_event_row(0.0),
                "protocol": "ICMP",
                "metric_id": "PING-CHECK",
                "metadata": {"name": "PING-CHECK", "criticality": 3, "availability_source": "PING"},
            },
        ]
    )

    assert rows[0]["event_type"] is None
    assert rows[0]["is_breach"] is False
    assert rows[1]["event_type"] is None
    assert rows[1]["is_breach"] is False
    assert rows[2]["event_type"] == "AVAILABILITY"
    assert rows[2]["availability_source"] == "PING"


def test_event_writer_derives_threshold_breach_and_availability_recovery_rows():
    from polling.event_writer import build_event_rows

    rows = build_event_rows(
        [
            _event_row(97.0),
            {
                **_event_row(1.0),
                "protocol": "ICMP",
                "metric_id": "PING-CHECK",
                "metadata": {"availability_source": "PING", "criticality": 3},
            },
            {
                **_event_row(0.0),
                "protocol": "ICMP",
                "metric_id": "PING-CHECK",
                "metadata": {"availability_source": "PING", "criticality": 3},
            },
        ]
    )

    assert rows[0]["is_breach"] is True
    assert rows[0]["severity"] == "CRITICAL"
    assert rows[0]["correlation_type"] == "ROOT"
    assert rows[0]["root_cause_ci_id"] == "ci-1"
    assert "Critical Threshold Breached" in rows[0]["message"]
    assert rows[1]["is_breach"] is False
    assert rows[1]["recover_non_collection_event"] is True
    assert rows[2]["is_breach"] is True
    assert rows[2]["event_type"] == "AVAILABILITY"
    assert rows[2]["source_protocol"] == "ICMP"
    assert rows[2]["availability_source"] == "PING"
    assert rows[2]["severity"] == "CRITICAL"
    assert "Service/Host Down" in rows[2]["message"]


def test_event_writer_derives_icmp_latency_warning_and_critical_threshold_rows():
    from polling.event_writer import build_event_rows

    base = {
        **_event_row(99.9),
        "protocol": "ICMP",
        "metric_id": "icmp_latency_ms",
        "metadata": {
            "name": "ICMP Latency",
            "warning": 100,
            "critical": 500,
            "operator": ">=",
            "metric_kind": "telemetry",
            "criticality": 3,
        },
    }

    rows = build_event_rows(
        [
            base,
            {**base, "value": {"numeric": 100.0, "raw": 100.0}},
            {**base, "value": {"numeric": 499.9, "raw": 499.9}},
            {**base, "value": {"numeric": 500.0, "raw": 500.0}},
            {**base, "value": {"numeric": None, "raw": None}},
        ]
    )

    assert rows[0]["is_breach"] is False
    assert rows[0]["recover_non_collection_event"] is True
    assert rows[1]["severity"] == "WARNING"
    assert rows[1]["event_type"] == "THRESHOLD_BREACH"
    assert rows[2]["severity"] == "WARNING"
    assert rows[3]["severity"] == "CRITICAL"
    assert rows[4]["is_breach"] is False
    assert rows[4]["recover_non_collection_event"] is False


def test_event_writer_derives_icmp_jitter_warning_and_critical_threshold_rows():
    from polling.event_writer import build_event_rows

    base = {
        **_event_row(49.9),
        "protocol": "ICMP",
        "metric_id": "icmp_jitter_ms",
        "metadata": {
            "name": "ICMP Jitter",
            "warning": 50,
            "critical": 150,
            "operator": ">=",
            "metric_kind": "telemetry",
            "criticality": 2,
        },
    }

    rows = build_event_rows(
        [
            base,
            {**base, "value": {"numeric": 50.0, "raw": 50.0}},
            {**base, "value": {"numeric": 149.9, "raw": 149.9}},
            {**base, "value": {"numeric": 150.0, "raw": 150.0}},
        ]
    )

    assert rows[0]["is_breach"] is False
    assert rows[0]["recover_non_collection_event"] is True
    assert rows[1]["severity"] == "WARNING"
    assert rows[1]["event_type"] == "THRESHOLD_BREACH"
    assert rows[2]["severity"] == "WARNING"
    assert rows[3]["severity"] == "CRITICAL"


def test_event_writer_derives_icmp_packet_loss_warning_and_critical_threshold_rows():
    from polling.event_writer import build_event_rows

    base = {
        **_event_row(9.9),
        "protocol": "ICMP",
        "metric_id": "packet_loss_pct",
        "metadata": {
            "name": "ICMP Packet Loss",
            "warning": 10,
            "critical": 50,
            "operator": ">=",
            "metric_kind": "telemetry",
            "criticality": 3,
        },
    }

    rows = build_event_rows(
        [
            base,
            {**base, "value": {"numeric": 10.0, "raw": 10.0}},
            {**base, "value": {"numeric": 49.9, "raw": 49.9}},
            {**base, "value": {"numeric": 50.0, "raw": 50.0}},
            {**base, "value": {"numeric": 100.0, "raw": 100.0}},
        ]
    )

    assert rows[0]["is_breach"] is False
    assert rows[0]["recover_non_collection_event"] is True
    assert rows[1]["severity"] == "WARNING"
    assert rows[1]["event_type"] == "THRESHOLD_BREACH"
    assert rows[2]["severity"] == "WARNING"
    assert rows[3]["severity"] == "CRITICAL"
    # CI-down path: 100% packet loss must always surface as CRITICAL.
    assert rows[4]["severity"] == "CRITICAL"


def test_event_writer_uses_unwind_for_latest_breach_and_recovery_updates():
    from polling.event_writer import batch_update_events

    driver = MockNeo4jDriver()
    batch_update_events(
        driver, [_event_row(95.0), {**_event_row(1.0), "idempotency_key": "idem-2"}]
    )

    queries = "\n".join(q["query"] for q in driver.mock_session.queries)
    assert queries.count("UNWIND $rows AS row") >= 3
    assert "MERGE (n)-[r:HAS_METRIC]->(m)" in queries
    assert "CREATE (res:MetricResult" in queries or "MERGE (res:MetricResult" in queries
    assert "status: 'OPEN'" in queries
    assert "id: randomUUID()" in queries
    assert "e.id = coalesce(e.id, randomUUID())" not in queries
    assert "RECOVERED" in queries
    assert "existing.status IN ['OPEN', 'ACK', 'RECOVERED']" not in queries
    assert "correlation_type" in queries
    assert "root_cause_ci_id" in queries
    assert "PROPAGATED" in queries


def test_event_writer_creates_a_new_incident_after_availability_recovery():
    from polling.event_writer import batch_update_events

    class LifecycleSession:
        def __init__(self):
            self.events = []
            self.queries = []
            self._clock = datetime(2026, 1, 1, tzinfo=UTC)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def run(self, query, **params):
            self.queries.append({"query": query, "params": params})
            rows = params.get("rows", [])
            if "WITH row WHERE row.is_breach AND row.event_type <> 'COLLECTION_FAILURE'" in query:
                eligible_statuses = {"OPEN", "ACK"}
                if "'RECOVERED'" in query:
                    eligible_statuses.add("RECOVERED")
                for row in rows:
                    if not row["is_breach"]:
                        continue
                    existing = next(
                        (
                            event
                            for event in self.events
                            if event["ci_id"] == row["ci_id"]
                            and event["metric_id"] == row["metric_id"]
                            and event["event_type"] == row["event_type"]
                            and event["status"] in eligible_statuses
                        ),
                        None,
                    )
                    if existing is None:
                        self._clock += timedelta(minutes=1)
                        self.events.append(
                            {
                                "ci_id": row["ci_id"],
                                "metric_id": row["metric_id"],
                                "event_type": row["event_type"],
                                "status": "OPEN",
                                "created_at": self._clock,
                                "recovered_at": None,
                            }
                        )
                    else:
                        existing["status"] = "OPEN"
                        existing["recovered_at"] = None
            elif "WITH row WHERE row.recover_non_collection_event" in query:
                for row in rows:
                    if not row["recover_non_collection_event"]:
                        continue
                    for event in self.events:
                        if (
                            event["ci_id"] == row["ci_id"]
                            and event["metric_id"] == row["metric_id"]
                            and event["status"] in {"OPEN", "ACK"}
                        ):
                            self._clock += timedelta(minutes=1)
                            event["status"] = "RECOVERED"
                            event["recovered_at"] = self._clock
            return []

    class LifecycleDriver:
        def __init__(self):
            self.session_obj = LifecycleSession()

        def session(self):
            return self.session_obj

    driver = LifecycleDriver()
    failed_ping = {
        **_event_row(0.0),
        "protocol": "ICMP",
        "metric_id": "PING-CHECK",
        "metadata": {"availability_source": "PING", "criticality": 3},
    }
    recovered_ping = {**failed_ping, "value": {"numeric": 1.0, "raw": 1.0}}

    batch_update_events(driver, [failed_ping])
    batch_update_events(driver, [recovered_ping])
    first_incident = driver.session_obj.events[0].copy()
    batch_update_events(driver, [failed_ping])

    assert first_incident["status"] == "RECOVERED"
    assert first_incident["recovered_at"] is not None
    assert len(driver.session_obj.events) == 2
    next_incident = driver.session_obj.events[1]
    assert next_incident["status"] == "OPEN"
    assert next_incident["created_at"] > first_incident["created_at"]


def test_event_writer_deduplicates_idempotent_payload_rows_before_metric_result_write():
    from polling.event_writer import batch_update_events

    driver = MockNeo4jDriver()
    first_payload = {**_event_row(95.0), "idempotency_key": "idem-1"}
    duplicate_payload = {**first_payload, "value": {"numeric": 95.0, "raw": 95.0}}

    batch_update_events(
        driver,
        [first_payload, duplicate_payload],
    )

    metric_queries = [
        q
        for q in driver.mock_session.queries
        if "MetricResult" in q["query"] and "MERGE" in q["query"]
    ]
    assert len(metric_queries) == 1
    deduped_rows = metric_queries[0]["params"]["rows"]
    assert len(deduped_rows) == 1
    assert deduped_rows[0]["idempotency_key"] == first_payload["idempotency_key"]
    assert deduped_rows[0]["ci_id"] == first_payload["ci_id"]
    assert deduped_rows[0]["metric_id"] == first_payload["metric_id"]
    assert "MERGE (res)-[:FOR_METRIC]->(m)" in metric_queries[0]["query"]
    assert "CREATE (res)-[:FOR_METRIC]->(m)" not in metric_queries[0]["query"]


def test_metric_result_idempotency_migration_adds_uniqueness_guard():
    from pathlib import Path

    migration = (
        Path(__file__).resolve().parents[1] / "migrations/004_mqtt_metric_result_idempotency.cypher"
    )

    assert migration.exists()
    cypher = migration.read_text().lower()
    assert "metricresult" in cypher
    assert "idempotency_key" in cypher
    assert "is unique" in cypher


def test_event_writer_icmp_success_recovers_only_icmp_availability_events():
    from polling.event_writer import batch_update_events

    driver = MockNeo4jDriver()
    batch_update_events(
        driver, [{**_event_row(1.0), "protocol": "ICMP", "metric_id": "PING-CHECK"}]
    )

    recovery_queries = [
        q["query"]
        for q in driver.mock_session.queries
        if "WITH row WHERE row.recover_non_collection_event" in q["query"]
    ]
    assert recovery_queries
    recovery_query = recovery_queries[0]
    assert "row.source_protocol = 'ICMP'" in recovery_query
    assert "e.event_type = 'AVAILABILITY'" in recovery_query
    assert "toUpper(e.source_protocol) = row.source_protocol" in recovery_query
    assert "pe.propagated_from = e.id" in recovery_query


def test_event_writer_icmp_latency_ok_recovers_threshold_breach_events():
    from polling.event_writer import batch_update_events

    driver = MockNeo4jDriver()
    batch_update_events(
        driver,
        [
            {
                **_event_row(42.0),
                "protocol": "ICMP",
                "metric_id": "icmp_latency_ms",
                "metadata": {
                    "name": "ICMP Latency",
                    "warning": 100,
                    "critical": 500,
                    "operator": ">=",
                    "metric_kind": "telemetry",
                    "criticality": 3,
                },
            }
        ],
    )

    recovery_query = next(
        q for q in driver.mock_session.queries if "row.recover_non_collection_event" in q["query"]
    )
    assert "e.event_type = 'THRESHOLD_BREACH'" in recovery_query["query"]
    assert "row.metric_id = e.metric_id" in recovery_query["query"]


def test_event_writer_direct_latency_recovery_excludes_propagated_events():
    from polling.event_writer import batch_update_events

    driver = MockNeo4jDriver()
    batch_update_events(
        driver,
        [
            {
                **_event_row(42.0),
                "protocol": "ICMP",
                "metric_id": "icmp_latency_ms",
                "metadata": {
                    "name": "ICMP Latency",
                    "warning": 100,
                    "critical": 500,
                    "operator": ">=",
                    "metric_kind": "telemetry",
                    "criticality": 3,
                },
            }
        ],
    )

    recovery_query = next(
        q for q in driver.mock_session.queries if "row.recover_non_collection_event" in q["query"]
    )["query"]
    assert "coalesce(e.correlation_type, 'ROOT') = 'ROOT'" in recovery_query
    assert "pe.root_cause_ci_id = e.ci_id" in recovery_query
    assert "pe.correlation_type = 'PROPAGATED'" in recovery_query


def test_event_writer_threshold_breach_refresh_updates_open_or_ack_events_without_merge_duplicate():
    from unittest.mock import MagicMock, patch

    from polling.event_writer import batch_update_events

    driver = MockNeo4jDriver()
    lock_db = MagicMock()
    # Track call ORDER between lock helper and session.run, tagged with the
    # query so we can verify the lock precedes the SPECIFIC breach query
    # (not just any neo4j call — earlier writes like ``latest_metric_rows``
    # legitimately run before the lock for the breach batch).
    call_order: list[tuple[str, str | None]] = []

    with patch("polling.event_writer.acquire_event_triplet_lock") as mock_lock:
        mock_lock.side_effect = lambda *_a, **_kw: call_order.append(("lock", None))
        original_run = driver.mock_session.run

        def tracking_run(query, **params):
            call_order.append(("neo4j", query))
            return original_run(query, **params)

        driver.mock_session.run = tracking_run

        batch_update_events(
            driver,
            [
                {
                    **_event_row(500.0),
                    "protocol": "ICMP",
                    "metric_id": "icmp_latency_ms",
                    "metadata": {
                        "name": "ICMP Latency",
                        "warning": 100,
                        "critical": 500,
                        "operator": ">=",
                        "metric_kind": "telemetry",
                        "criticality": 3,
                    },
                }
            ],
            lock_db=lock_db,
        )

    breach_query = next(
        q
        for q in driver.mock_session.queries
        if "row.is_breach AND row.event_type <> 'COLLECTION_FAILURE'" in q["query"]
    )
    assert "existing.status IN ['OPEN', 'ACK']" in breach_query["query"]
    assert (
        "coalesce(existing.correlation_type, 'ROOT') = coalesce(row.correlation_type, 'ROOT')"
        in breach_query["query"]
    )
    assert "coalesce(row.correlation_type, 'ROOT') <> 'PROPAGATED'" in breach_query["query"]
    # #322 / design §6/§11 — POSITIVE flipped assertion: lock helper IS called
    # with the open PG session and the breach triplet. Replaces the old
    # negative MERGE-absent check.
    assert (
        mock_lock.call_count == 1
    ), f"acquire_event_triplet_lock MUST be called once; got {mock_lock.call_count}"
    lock_args = mock_lock.call_args_list[0].args
    lock_kwargs = mock_lock.call_args_list[0].kwargs
    assert lock_args[0] is lock_db, "lock helper must receive the open PG session"
    assert lock_args[1] == "ci-1"
    assert lock_args[2] == "icmp_latency_ms"
    assert lock_args[3] == "THRESHOLD_BREACH"
    assert lock_kwargs["writer_context"] == "polling_event_writer"
    # Lock MUST be acquired BEFORE the breach query's session.run.
    lock_idx = next(i for i, (kind, _) in enumerate(call_order) if kind == "lock")
    breach_idx = next(
        i
        for i, (kind, q) in enumerate(call_order)
        if kind == "neo4j"
        and "row.is_breach AND row.event_type <> 'COLLECTION_FAILURE'" in (q or "")
    )
    assert lock_idx < breach_idx, (
        f"lock (idx {lock_idx}) must precede breach query (idx {breach_idx}); "
        f"order={call_order!r}"
    )
    # Defensive regression: no MERGE pattern in the breach query.
    assert (
        "MERGE (e:Event {ci_id: row.ci_id, metric_id: row.metric_id, event_type: row.event_type, status: 'OPEN'})"
        not in breach_query["query"]
    )
    assert "created_at: datetime(), last_seen: datetime()" in breach_query["query"]
    assert "SET existing.severity = row.severity" in breach_query["query"]
    assert (
        "existing.created_at = coalesce(existing.created_at, existing.last_seen, datetime())"
        in breach_query["query"]
    )
    assert (
        "existing.ack = CASE WHEN existing.status = 'ACK' THEN existing.ack ELSE false END"
        in breach_query["query"]
    )


def test_event_writer_propagated_breach_refresh_matches_correlation_and_root_identifiers():
    from polling.event_writer import batch_update_events

    driver = MockNeo4jDriver()
    batch_update_events(
        driver,
        [
            {
                **_event_row(500.0),
                "protocol": "ICMP",
                "metric_id": "icmp_latency_ms",
                "metadata": {
                    "name": "ICMP Latency",
                    "warning": 100,
                    "critical": 500,
                    "operator": ">=",
                    "metric_kind": "telemetry",
                    "criticality": 3,
                    "correlation_type": "PROPAGATED",
                    "propagated_from": "event-parent",
                    "root_cause_event_id": "event-root",
                    "root_cause_ci_id": "ci-root",
                },
            }
        ],
    )

    breach_query = next(
        q
        for q in driver.mock_session.queries
        if "row.is_breach AND row.event_type <> 'COLLECTION_FAILURE'" in q["query"]
    )
    query = breach_query["query"]
    assert (
        "coalesce(existing.correlation_type, 'ROOT') = coalesce(row.correlation_type, 'ROOT')"
        in query
    )
    assert "row.propagated_from IS NULL OR existing.propagated_from = row.propagated_from" in query
    assert (
        "row.root_cause_event_id IS NULL OR existing.root_cause_event_id = row.root_cause_event_id"
        in query
    )
    assert (
        "row.root_cause_ci_id IS NULL OR existing.root_cause_ci_id = row.root_cause_ci_id" in query
    )
    assert breach_query["params"]["rows"][0]["correlation_type"] == "PROPAGATED"
    assert breach_query["params"]["rows"][0]["root_cause_event_id"] == "event-root"


def test_event_writer_deduplicates_non_collection_breaches_before_create_query():
    from polling.event_writer import batch_update_events

    driver = MockNeo4jDriver()
    batch_update_events(
        driver,
        [
            {
                **_event_row(100.0),
                "protocol": "ICMP",
                "metric_id": "icmp_latency_ms",
                "metadata": {
                    "name": "ICMP Latency",
                    "warning": 100,
                    "critical": 500,
                    "operator": ">=",
                    "metric_kind": "telemetry",
                    "criticality": 3,
                },
            },
            {
                **_event_row(500.0),
                "protocol": "ICMP",
                "metric_id": "icmp_latency_ms",
                "metadata": {
                    "name": "ICMP Latency",
                    "warning": 100,
                    "critical": 500,
                    "operator": ">=",
                    "metric_kind": "telemetry",
                    "criticality": 3,
                },
            },
        ],
    )

    breach_query = next(
        q
        for q in driver.mock_session.queries
        if "row.is_breach AND row.event_type <> 'COLLECTION_FAILURE'" in q["query"]
    )
    assert len(breach_query["params"]["rows"]) == 1
    assert breach_query["params"]["rows"][0]["severity"] == "CRITICAL"
    assert breach_query["params"]["rows"][0]["value"] == "500.0"


def test_event_writer_keeps_distinct_propagated_roots_in_non_collection_batch():
    from polling.event_writer import batch_update_events

    driver = MockNeo4jDriver()
    batch_update_events(
        driver,
        [
            {
                **_event_row(500.0),
                "protocol": "ICMP",
                "metric_id": "icmp_latency_ms",
                "metadata": {
                    "name": "ICMP Latency",
                    "critical": 500,
                    "operator": ">=",
                    "metric_kind": "telemetry",
                    "criticality": 3,
                    "correlation_type": "PROPAGATED",
                    "propagated_from": "event-parent-a",
                    "root_cause_event_id": "event-root-a",
                    "root_cause_ci_id": "ci-root-a",
                },
            },
            {
                **_event_row(500.0),
                "protocol": "ICMP",
                "metric_id": "icmp_latency_ms",
                "metadata": {
                    "name": "ICMP Latency",
                    "critical": 500,
                    "operator": ">=",
                    "metric_kind": "telemetry",
                    "criticality": 3,
                    "correlation_type": "PROPAGATED",
                    "propagated_from": "event-parent-b",
                    "root_cause_event_id": "event-root-b",
                    "root_cause_ci_id": "ci-root-b",
                },
            },
        ],
    )

    breach_query = next(
        q
        for q in driver.mock_session.queries
        if "row.is_breach AND row.event_type <> 'COLLECTION_FAILURE'" in q["query"]
    )
    assert len(breach_query["params"]["rows"]) == 2


def test_event_writer_uses_latest_non_collection_state_for_ok_then_warning_batch():
    from polling.event_writer import batch_update_events

    driver = MockNeo4jDriver()
    batch_update_events(
        driver,
        [
            {
                **_event_row(42.0),
                "protocol": "ICMP",
                "metric_id": "icmp_latency_ms",
                "observed_at": datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
                "metadata": {
                    "name": "ICMP Latency",
                    "warning": 100,
                    "critical": 500,
                    "operator": ">=",
                    "metric_kind": "telemetry",
                    "criticality": 3,
                },
            },
            {
                **_event_row(100.0),
                "protocol": "ICMP",
                "metric_id": "icmp_latency_ms",
                "observed_at": datetime(2026, 1, 1, 12, 1, tzinfo=UTC),
                "metadata": {
                    "name": "ICMP Latency",
                    "warning": 100,
                    "critical": 500,
                    "operator": ">=",
                    "metric_kind": "telemetry",
                    "criticality": 3,
                },
            },
        ],
    )

    latest_query = driver.mock_session.queries[0]
    breach_query = next(
        q
        for q in driver.mock_session.queries
        if "row.is_breach AND row.event_type <> 'COLLECTION_FAILURE'" in q["query"]
    )
    recovery_query = next(
        q for q in driver.mock_session.queries if "row.recover_non_collection_event" in q["query"]
    )
    assert len(latest_query["params"]["rows"]) == 1
    assert latest_query["params"]["rows"][0]["status"] == "WARNING"
    assert len(breach_query["params"]["rows"]) == 1
    assert breach_query["params"]["rows"][0]["severity"] == "WARNING"
    assert recovery_query["params"]["rows"][0]["recover_non_collection_event"] is False


def test_event_writer_uses_latest_non_collection_state_for_warning_then_ok_batch():
    from polling.event_writer import batch_update_events

    driver = MockNeo4jDriver()
    batch_update_events(
        driver,
        [
            {
                **_event_row(100.0),
                "protocol": "ICMP",
                "metric_id": "icmp_latency_ms",
                "observed_at": datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
                "metadata": {
                    "name": "ICMP Latency",
                    "warning": 100,
                    "critical": 500,
                    "operator": ">=",
                    "metric_kind": "telemetry",
                    "criticality": 3,
                },
            },
            {
                **_event_row(42.0),
                "protocol": "ICMP",
                "metric_id": "icmp_latency_ms",
                "observed_at": datetime(2026, 1, 1, 12, 1, tzinfo=UTC),
                "metadata": {
                    "name": "ICMP Latency",
                    "warning": 100,
                    "critical": 500,
                    "operator": ">=",
                    "metric_kind": "telemetry",
                    "criticality": 3,
                },
            },
        ],
    )

    latest_query = driver.mock_session.queries[0]
    breach_query = next(
        q
        for q in driver.mock_session.queries
        if "row.is_breach AND row.event_type <> 'COLLECTION_FAILURE'" in q["query"]
    )
    recovery_query = next(
        q for q in driver.mock_session.queries if "row.recover_non_collection_event" in q["query"]
    )
    assert len(latest_query["params"]["rows"]) == 1
    assert latest_query["params"]["rows"][0]["status"] == "OK"
    assert breach_query["params"]["rows"] == []
    assert len(recovery_query["params"]["rows"]) == 1
    assert recovery_query["params"]["rows"][0]["recover_non_collection_event"] is True


def test_event_writer_prefers_latest_observed_timestamp_over_last_duplicate_order():
    from polling.event_writer import batch_update_events

    driver = MockNeo4jDriver()
    batch_update_events(
        driver,
        [
            {
                **_event_row(42.0),
                "protocol": "ICMP",
                "metric_id": "icmp_latency_ms",
                "observed_at": datetime(2026, 1, 1, 12, 2, tzinfo=UTC),
                "metadata": {
                    "name": "ICMP Latency",
                    "warning": 100,
                    "critical": 500,
                    "operator": ">=",
                    "metric_kind": "telemetry",
                    "criticality": 3,
                },
            },
            {
                **_event_row(500.0),
                "protocol": "ICMP",
                "metric_id": "icmp_latency_ms",
                "observed_at": datetime(2026, 1, 1, 12, 1, tzinfo=UTC),
                "metadata": {
                    "name": "ICMP Latency",
                    "warning": 100,
                    "critical": 500,
                    "operator": ">=",
                    "metric_kind": "telemetry",
                    "criticality": 3,
                },
            },
        ],
    )

    latest_query = driver.mock_session.queries[0]
    breach_query = next(
        q
        for q in driver.mock_session.queries
        if "row.is_breach AND row.event_type <> 'COLLECTION_FAILURE'" in q["query"]
    )
    recovery_query = next(
        q for q in driver.mock_session.queries if "row.recover_non_collection_event" in q["query"]
    )
    assert latest_query["params"]["rows"][0]["status"] == "OK"
    assert breach_query["params"]["rows"] == []
    assert recovery_query["params"]["rows"][0]["value"] == "42.0"


def test_event_writer_preserves_propagated_correlation_metadata():
    from polling.event_writer import build_event_rows

    rows = build_event_rows(
        [
            _event_row(
                95.0,
                metadata={
                    "critical": 90,
                    "criticality": 3,
                    "operator": ">=",
                    "correlation_type": "PROPAGATED",
                    "propagated_from": "event-root",
                    "root_cause_ci_id": "ci-root",
                    "business_service_id": "bs-1",
                },
            )
        ]
    )

    assert rows[0]["correlation_type"] == "PROPAGATED"
    assert rows[0]["propagated_from"] == "event-root"
    assert rows[0]["root_cause_event_id"] is None
    assert rows[0]["root_cause_ci_id"] == "ci-root"
    assert rows[0]["business_service_id"] == "bs-1"


def test_event_writer_derives_snmp_no_data_as_warning_collection_failure():
    from polling.event_writer import build_event_rows

    rows = build_event_rows(
        [
            _event_row(
                None,
                status="NO_DATA",
                metadata={"name": "ifInOctets", "criticality": 1},
            )
        ]
    )

    assert rows[0]["is_breach"] is True
    assert rows[0]["severity"] == "WARNING"
    assert rows[0]["event_type"] == "COLLECTION_FAILURE"
    assert rows[0]["failure_family"] == "SNMP_NO_RESPONSE"
    assert rows[0]["source_protocol"] == "SNMP"
    assert rows[0]["message"].startswith("Metric Collection Failed:")


def test_event_writer_does_not_label_generic_snmp_error_as_no_response():
    from polling.event_writer import build_event_rows

    rows = build_event_rows(
        [
            {
                **_event_row(
                    None,
                    status="ERROR",
                    metadata={"name": "ifInOctets", "criticality": 3},
                ),
                "error": {"code": "value_error", "message": "could not convert string to float"},
            }
        ]
    )

    assert rows[0]["is_breach"] is True
    assert rows[0]["severity"] == "CRITICAL"
    assert rows[0]["event_type"] == "COLLECTION_FAILURE"
    assert rows[0]["failure_family"] is None
    assert "SNMP_NO_RESPONSE" not in rows[0]["message"]


def test_event_writer_labels_explicit_snmp_timeout_error_as_no_response_warning():
    from polling.event_writer import build_event_rows

    rows = build_event_rows(
        [
            {
                **_event_row(
                    None, status="ERROR", metadata={"name": "ifInOctets", "criticality": 3}
                ),
                "error": {"code": "timeout", "message": "No SNMP response received before timeout"},
            }
        ]
    )

    assert rows[0]["severity"] == "WARNING"
    assert rows[0]["event_type"] == "COLLECTION_FAILURE"
    assert rows[0]["failure_family"] == "SNMP_NO_RESPONSE"


def test_event_writer_marks_valid_rows_for_collection_failure_recovery_even_on_breach():
    from polling.event_writer import build_event_rows

    rows = build_event_rows(
        [
            _event_row(42.0, metadata={"name": "cpu", "criticality": 3, "critical": 90}),
            _event_row(
                97.0, metadata={"name": "cpu", "criticality": 3, "critical": 90, "operator": ">="}
            ),
            {
                **_event_row(
                    97.0,
                    metadata={
                        "name": "cli-health",
                        "criticality": 3,
                        "critical": 90,
                        "operator": ">=",
                    },
                ),
                "protocol": "CLI",
                "metric_id": "cli-health",
            },
        ]
    )

    assert rows[0]["is_breach"] is False
    assert rows[0]["recover_collection_failure"] is True
    assert rows[0]["event_type"] is None
    assert rows[1]["is_breach"] is True
    assert rows[1]["recover_collection_failure"] is True
    assert rows[1]["event_type"] == "THRESHOLD_BREACH"
    assert rows[2]["is_breach"] is True
    assert rows[2]["recover_collection_failure"] is True
    assert rows[2]["event_type"] == "THRESHOLD_BREACH"


def test_event_writer_uses_discriminator_aware_event_queries():
    from unittest.mock import MagicMock, patch

    from polling.event_writer import batch_update_events

    driver = MockNeo4jDriver()
    lock_db = MagicMock()

    # Two envelopes that produce TWO distinct Event types in the same batch:
    #   1. NO_DATA → COLLECTION_FAILURE (failure_family = SNMP_NO_RESPONSE)
    #   2. value=500 + critical=100 → THRESHOLD_BREACH
    with patch("polling.event_writer.acquire_event_triplet_lock") as mock_lock:
        batch_update_events(
            driver,
            [
                _event_row(None, status="NO_DATA"),  # COLLECTION_FAILURE
                {
                    **_event_row(500.0),
                    "protocol": "SNMP",
                    "metric_id": "cpu",
                    "metadata": {
                        "name": "cpu",
                        "criticality": 3,
                        "critical": 100,
                        "warning": 80,
                        "operator": ">=",
                    },
                },
            ],
            lock_db=lock_db,
        )

    queries = "\n".join(q["query"] for q in driver.mock_session.queries)
    assert "event_type" in queries
    assert "failure_family" in queries
    assert "Metric Collection Failed:" in queries
    # #322 / design §6/§11 — POSITIVE flipped assertion: lock helper IS called
    # for each distinct triplet in the batch (one COLLECTION_FAILURE +
    # one THRESHOLD_BREACH). Replaces the old negative MERGE-absent check
    # on the union of queries.
    assert mock_lock.call_count >= 2, (
        f"acquire_event_triplet_lock MUST be called once per distinct triplet; "
        f"got {mock_lock.call_count} calls"
    )
    triplets = [
        (call.args[1], call.args[2], call.args[3], call.kwargs.get("writer_context"))
        for call in mock_lock.call_args_list
        if len(call.args) >= 4
    ]
    # The collection-failure envelope and the threshold-breach envelope
    # produce different triplets — both MUST be locked.
    assert (
        "ci-1",
        "cpu",
        "COLLECTION_FAILURE",
        "polling_event_writer",
    ) in triplets, f"collection-failure triplet MUST be locked; got {triplets!r}"
    assert (
        "ci-1",
        "cpu",
        "THRESHOLD_BREACH",
        "polling_event_writer",
    ) in triplets, f"threshold-breach triplet MUST be locked; got {triplets!r}"
    # Defensive regression: no MERGE pattern in any of the queries.
    assert (
        "MERGE (e:Event {ci_id: row.ci_id, metric_id: row.metric_id, status: 'OPEN'})"
        not in queries
    )
    assert "COLLECTION_FAILURE" in queries
    assert "SNMP_NO_RESPONSE" in queries


def test_event_writer_acquires_locks_in_lexicographic_order_across_batch():
    """#322 / design §4 — deterministic lock ordering (mandatory).

    When a batch contains MULTIPLE distinct triplets, lock acquisition MUST
    be in lexicographic order by ``(ci_id, metric_id, event_type)`` BEFORE
    the Neo4j UNWIND query. Without this rule, two concurrent batches with
    overlapping triplets contended in opposite order would trigger
    Postgres deadlock detection.

    Reverse-ordered input proves the sort happens internally: the writer
    sees envelopes in order Z, Y, X but MUST acquire locks in X, Y, Z order.
    """
    from unittest.mock import MagicMock, patch

    from polling.event_writer import batch_update_events

    driver = MockNeo4jDriver()
    lock_db = MagicMock()
    lock_call_order: list[tuple[str, str, str]] = []

    def _capture(lock_db_arg, ci_id, metric_id, event_type, *, writer_context):
        lock_call_order.append((ci_id, metric_id, event_type, writer_context))

    # Input ORDER is Z, Y, X — writer MUST sort to X, Y, Z internally.
    envelopes_in_reverse = [
        {
            **_event_row(500.0),
            "ci_id": "ci-Z",
            "metric_id": "metric-Z",
            "protocol": "ICMP",
            "metadata": {
                "name": "metric-Z",
                "warning": 100,
                "critical": 500,
                "operator": ">=",
                "metric_kind": "telemetry",
                "criticality": 3,
            },
        },
        {
            **_event_row(500.0),
            "ci_id": "ci-Y",
            "metric_id": "metric-Y",
            "protocol": "ICMP",
            "metadata": {
                "name": "metric-Y",
                "warning": 100,
                "critical": 500,
                "operator": ">=",
                "metric_kind": "telemetry",
                "criticality": 3,
            },
        },
        {
            **_event_row(500.0),
            "ci_id": "ci-X",
            "metric_id": "metric-X",
            "protocol": "ICMP",
            "metadata": {
                "name": "metric-X",
                "warning": 100,
                "critical": 500,
                "operator": ">=",
                "metric_kind": "telemetry",
                "criticality": 3,
            },
        },
    ]

    with patch("polling.event_writer.acquire_event_triplet_lock", side_effect=_capture):
        batch_update_events(driver, envelopes_in_reverse, lock_db=lock_db)

    # Acquisitions MUST be in lexicographic order regardless of input order.
    assert lock_call_order == [
        ("ci-X", "metric-X", "THRESHOLD_BREACH", "polling_event_writer"),
        ("ci-Y", "metric-Y", "THRESHOLD_BREACH", "polling_event_writer"),
        ("ci-Z", "metric-Z", "THRESHOLD_BREACH", "polling_event_writer"),
    ], f"locks MUST be acquired in lexicographic order; got {lock_call_order!r}"


def test_event_writer_persists_poll_collector_id_on_event_create():
    """#322 / spec §Poll collector identity persistence — every Event row
    built by ``build_event_rows`` MUST include ``poll_collector_id`` so the
    writer can persist it on CREATE / SET.
    """
    from polling.event_writer import build_event_rows

    rows = build_event_rows(
        [
            _event_row(500.0, metadata={"name": "cpu", "criticality": 3, "critical": 90}),
        ]
    )

    assert rows, "expected at least one row"
    for row in rows:
        assert (
            "poll_collector_id" in row
        ), f"row MUST carry poll_collector_id; got keys={list(row.keys())!r}"
        assert row[
            "poll_collector_id"
        ], f"poll_collector_id MUST be non-empty; got {row['poll_collector_id']!r}"


def test_event_writer_collection_failure_matching_does_not_treat_null_family_as_wildcard():
    from polling.event_writer import batch_update_events

    driver = MockNeo4jDriver()
    batch_update_events(
        driver,
        [
            {
                **_event_row(
                    None,
                    status="ERROR",
                    metadata={"name": "ifInOctets", "criticality": 3},
                ),
                "error": {"code": "value_error", "message": "could not convert string to float"},
            }
        ],
    )

    collection_query = next(
        q
        for q in driver.mock_session.queries
        if "row.event_type = 'COLLECTION_FAILURE'" in q["query"]
    )["query"]
    assert (
        "row.failure_family IS NULL OR existing.failure_family = row.failure_family"
        not in collection_query
    )
    assert "row.failure_family IS NULL AND existing.failure_family IS NULL" in collection_query
    assert "row.failure_family IS NOT NULL" in collection_query


def test_event_writer_recovers_non_collection_events_on_normal_rows():
    from polling.event_writer import batch_update_events, build_event_rows

    rows = build_event_rows(
        [_event_row(42.0, metadata={"name": "cpu", "criticality": 3, "critical": 90})]
    )
    assert rows[0]["recover_collection_failure"] is True
    assert rows[0]["recover_non_collection_event"] is True

    driver = MockNeo4jDriver()
    batch_update_events(
        driver, [_event_row(42.0, metadata={"name": "cpu", "criticality": 3, "critical": 90})]
    )

    queries = "\n".join(q["query"] for q in driver.mock_session.queries)
    assert "row.recover_non_collection_event" in queries
    assert "e.created_at = coalesce(e.created_at, e.last_seen, datetime())" in queries
    assert "e.event_type <> 'COLLECTION_FAILURE'" in queries
    assert (
        "NOT (e.event_type IS NULL AND e.message STARTS WITH 'Metric Collection Failed:')"
        in queries
    )


def test_event_writer_recovers_non_snmp_collection_failures_on_valid_rows_even_when_breaching():
    from polling.event_writer import batch_update_events, build_event_rows

    envelope = {
        **_event_row(
            97.0,
            metadata={"name": "cli-health", "criticality": 3, "critical": 90, "operator": ">="},
        ),
        "protocol": "CLI",
        "metric_id": "cli-health",
    }
    rows = build_event_rows([envelope])
    assert rows[0]["is_breach"] is True
    assert rows[0]["recover_collection_failure"] is True

    driver = MockNeo4jDriver()
    batch_update_events(driver, [envelope])

    recovery_query = next(
        q for q in driver.mock_session.queries if "row.recover_collection_failure" in q["query"]
    )
    assert "e.event_type = 'COLLECTION_FAILURE'" in recovery_query["query"]
    assert (
        "e.event_type IS NULL AND e.message STARTS WITH 'Metric Collection Failed:'"
        in recovery_query["query"]
    )
    assert "toUpper(e.source_protocol) = row.source_protocol" in recovery_query["query"]


def test_event_writer_deduplicates_collection_failure_rows_before_event_write():
    from polling.event_writer import batch_update_events

    driver = MockNeo4jDriver()
    batch_update_events(
        driver,
        [
            _event_row(None, status="NO_DATA"),
            {**_event_row(None, status="NO_DATA"), "idempotency_key": "idem-2"},
        ],
    )

    collection_query = next(
        q
        for q in driver.mock_session.queries
        if "row.event_type = 'COLLECTION_FAILURE'" in q["query"]
    )
    assert len(collection_query["params"]["rows"]) == 1


def test_event_writer_uses_collection_recovery_message_for_threshold_breach_recovery():
    from polling.event_writer import batch_update_events, build_event_rows

    rows = build_event_rows(
        [_event_row(97.0, metadata={"name": "cpu", "criticality": 3, "critical": 90})]
    )
    assert rows[0]["is_breach"] is True
    assert rows[0]["message"].startswith("Critical Threshold Breached")
    assert rows[0]["collection_recovery_message"].startswith("Metric collection recovered")

    driver = MockNeo4jDriver()
    batch_update_events(
        driver, [_event_row(97.0, metadata={"name": "cpu", "criticality": 3, "critical": 90})]
    )

    recovery_query = next(
        q for q in driver.mock_session.queries if "row.recover_collection_failure" in q["query"]
    )
    assert (
        "e.created_at = coalesce(e.created_at, e.last_seen, datetime())" in recovery_query["query"]
    )
    assert "row.collection_recovery_message" in recovery_query["query"]
