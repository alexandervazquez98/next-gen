"""REQ-CORR-3: CLI poll alert correlation tests.

`backend/engines/cli_worker.py:check_nan_threshold()` emits a `CLI_POLL_ALERT`
Event after 3 consecutive NaN misses for a CLI metric. PR 2 wires the same
correlation tagging into that event so cascade-deduplication works for CLI
metrics too:

- A CLI alert for a CI with an open failing upstream parent → PROPAGATED with
  the parent's event id and root CI id.
- A CLI alert for a CI with no open upstream parent → ROOT with
  `root_cause_ci_id` equal to its own CI.
- The CI lookup for the metric must come from the topology (CI owning the
  MetricDef), not from the `node_label` string (which is purely cosmetic).
- Failures in the CI lookup or the resolver must NOT block event emission —
  the alert still writes, defaulting to ROOT.
"""

from __future__ import annotations

import os
import sys
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engines"))

from unittest.mock import MagicMock, patch


def _mock_driver_with_ci(ci_id: str | None) -> MagicMock:
    """Build a mock driver whose session.run returns `ci_id` for the CI lookup.

    The first session.run call is treated as the CI lookup query (any MATCH on
    MetricDef); subsequent runs are no-ops. The CREATE query (the last one)
    is captured via `mock_session.run.call_args_list`.
    """
    mock_session = MagicMock()
    mock_session.run.side_effect = None

    def _run(query, **params):
        # CI lookup query matches by `MATCH (n:CI)-[:HAS_METRIC]->(m:MetricDef`
        if ci_id is not None and "match (n:ci)-[:has_metric]->(m:metricdef" in query.lower():
            record = MagicMock()
            record.get.return_value = ci_id
            return MagicMock(single=MagicMock(return_value=record))
        # Default: empty result
        return MagicMock(single=MagicMock(return_value=None))

    mock_session.run.side_effect = _run

    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
    return mock_driver


def _last_create_query(mock_session) -> tuple[str, dict]:
    """Return the (query, params) of the most recent CREATE Event call."""
    for call in reversed(mock_session.run.call_args_list):
        query = call[0][0]
        params = call[1] if len(call) > 1 else {}
        if "CREATE (e:Event" in query:
            return query, params
    raise AssertionError(
        "no CREATE Event query was executed. Captured calls: "
        f"{[c[0][0][:80] for c in mock_session.run.call_args_list]!r}"
    )


class TestCliPollAlertCorrelation:
    """REQ-CORR-3: CLI_POLL_ALERT events must carry correlation fields."""

    def setup_method(self):
        """Reset the module-level NaN tracker before each test."""
        from cli_worker import _nan_tracker
        _nan_tracker.clear()

    def _drive_to_alert(self, metric_id: str, node_label: str, ci_id: str | None,
                         correlation_return: dict):
        """Drive the CLI worker through 3 NaN misses and emit the alert.

        Returns the captured mock_session so the test can inspect the CREATE.
        """
        from cli_worker import check_nan_threshold

        mock_driver = _mock_driver_with_ci(ci_id)
        raw_outputs = ["raw-0", "raw-1", "raw-2"]

        with patch("cli_worker.driver", mock_driver), \
             patch(
                 "services.event_service.resolve_correlation_fields",
                 return_value=correlation_return,
             ):
            for raw in raw_outputs:
                check_nan_threshold(
                    metric_id, float("nan"), raw, node_label
                )
        return mock_driver.session.return_value.__enter__.return_value

    def test_cli_alert_propagated_when_failing_parent_exists(self):
        """CLI alert for a CI with an open upstream parent event → PROPAGATED
        with the parent's event id and root CI id."""
        mock_session = self._drive_to_alert(
            metric_id="ospf-neighbor",
            node_label="Router-01",
            ci_id="ci-B",
            correlation_return={
                "correlation_type": "PROPAGATED",
                "propagated_from": "evt-A-root",
                "root_cause_ci_id": "ci-A",
            },
        )

        query, params = _last_create_query(mock_session)
        assert "correlation_type: $correlation_type" in query, (
            "CLI alert CREATE must declare correlation_type as a Cypher param "
            "(REQ-CORR-3)"
        )
        assert "propagated_from: $propagated_from" in query
        assert "root_cause_ci_id: $root_cause_ci_id" in query
        assert params["correlation_type"] == "PROPAGATED", (
            f"expected correlation_type='PROPAGATED', got "
            f"{params.get('correlation_type')!r}. CLI alert not tagged."
        )
        assert params["propagated_from"] == "evt-A-root", (
            f"expected propagated_from='evt-A-root', got "
            f"{params.get('propagated_from')!r}"
        )
        assert params["root_cause_ci_id"] == "ci-A", (
            f"expected root_cause_ci_id='ci-A', got "
            f"{params.get('root_cause_ci_id')!r}"
        )

    def test_cli_alert_root_when_no_failing_parent(self):
        """CLI alert for a CI with no open upstream parent → ROOT with
        root_cause_ci_id equal to the CI's own id."""
        mock_session = self._drive_to_alert(
            metric_id="bgp-peer-state",
            node_label="Router-01",
            ci_id="ci-A",
            correlation_return={
                "correlation_type": "ROOT",
                "propagated_from": None,
                "root_cause_ci_id": "ci-A",
            },
        )

        _, params = _last_create_query(mock_session)
        assert params["correlation_type"] == "ROOT", (
            f"expected correlation_type='ROOT', got "
            f"{params.get('correlation_type')!r}"
        )
        assert params["propagated_from"] is None, (
            f"expected propagated_from=None for ROOT, got "
            f"{params.get('propagated_from')!r}"
        )
        assert params["root_cause_ci_id"] == "ci-A"

    def test_cli_alert_emits_when_ci_lookup_returns_none(self):
        """If the CI for the metric cannot be found in the topology, the alert
        STILL emits — fail-safe behavior. Default to ROOT with the metric_id
        as the fallback root_cause_ci_id so the event is never lost."""
        mock_session = self._drive_to_alert(
            metric_id="orphan-metric",
            node_label="Orphan",
            ci_id=None,
            correlation_return={
                "correlation_type": "ROOT",
                "propagated_from": None,
                "root_cause_ci_id": "orphan-metric",
            },
        )

        _, params = _last_create_query(mock_session)
        assert params["correlation_type"] == "ROOT"
        assert params["propagated_from"] is None
        # When ci_id can't be resolved, the metric_id is the fallback. The
        # resolver was NOT called (no ci_id to look up), so the call site
        # defaulted correlation to ROOT with metric_id as root_cause_ci_id.
        assert params["root_cause_ci_id"] == "orphan-metric"

    def test_cli_alert_uses_metric_owning_ci_not_node_label(self):
        """The correlation is computed from the CI that OWNS the MetricDef,
        not from the cosmetic node_label string. Two alerts for the same
        MetricDef (regardless of node_label) must resolve against the same
        CI id."""
        from cli_worker import _nan_tracker, check_nan_threshold

        _nan_tracker.clear()
        mock_driver = _mock_driver_with_ci("ci-B")
        with patch("cli_worker.driver", mock_driver), \
             patch(
                 "services.event_service.resolve_correlation_fields",
                 return_value={
                     "correlation_type": "PROPAGATED",
                     "propagated_from": "evt-A-root",
                     "root_cause_ci_id": "ci-A",
                 },
             ) as mock_resolve:
            # Two alerts with different node_label but same MetricDef.
            # Reset tracker between so each goes through the 3-NaN threshold
            # independently.
            for label in ("Router-01", "router-01", "ROUTER-01"):
                _nan_tracker.clear()
                for i in range(3):
                    check_nan_threshold(
                        "ospf-neighbor",
                        float("nan"),
                        f"raw-{label}-{i}",
                        label,
                    )

        # resolve_correlation_fields MUST have been called — once per alert.
        assert len(mock_resolve.call_args_list) == 3, (
            f"expected 3 resolve_correlation_fields calls (one per alert), "
            f"got {len(mock_resolve.call_args_list)}. CLI alert path is not "
            f"calling the resolver yet (REQ-CORR-3 not implemented)."
        )
        # Every resolve call must be against ci-B (the CI for the MetricDef),
        # never against the cosmetic node_label.
        for call in mock_resolve.call_args_list:
            called_ci_id = call[0][0]
            assert called_ci_id == "ci-B", (
                f"CLI correlation must resolve against the CI owning the "
                f"MetricDef (ci-B), got {called_ci_id!r} (looks like the "
                f"cosmetic node_label was used instead)."
            )
