"""
Unit tests for the CLI Engine Worker — engines/cli_worker.py

Covers:
- extract_regex_value(): regex parsing, capture groups, keyword mapping, edge cases
- resolve_credential(): env key resolution with fallback
- apply_escalation(): command sequence sending with paramiko mock

Uses paramiko mock to avoid requiring live SSH connectivity.
"""

import sys
import os
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engines"))

from unittest.mock import MagicMock, patch


class TestExtractRegexValue:
    """Tests for extract_regex_value(raw_output, extractor)."""

    def test_keyword_up_maps_to_1(self):
        """'up' keyword from interface status maps to numeric 1.0."""
        from cli_worker import extract_regex_value

        raw = "GigabitEthernet0/0 is up"
        extractor = "regex:is (up|down)"
        extracted, value = extract_regex_value(raw, extractor)

        assert extracted == "up"
        assert value == 1.0

    def test_keyword_down_maps_to_0(self):
        """'down' keyword maps to numeric 0.0."""
        from cli_worker import extract_regex_value

        raw = "GigabitEthernet0/0 is down"
        extractor = "regex:is (up|down)"
        extracted, value = extract_regex_value(raw, extractor)

        assert extracted == "down"
        assert value == 0.0

    def test_digit_pattern_extracts_numeric(self):
        """'load 45' extracted via regex and converted to float 45.0."""
        from cli_worker import extract_regex_value

        raw = "5 minute load: 45%"
        extractor = "regex:load:\\s*(\\d+)"
        extracted, value = extract_regex_value(raw, extractor)

        assert extracted == "45"
        assert value == 45.0

    def test_decimal_digit_pattern(self):
        """Decimal digits like '3.5' are correctly parsed as float."""
        from cli_worker import extract_regex_value

        raw = "CPU utilization: 73.5 percent"
        extractor = "regex:utilization: (\\d+\\.\\d+)"
        extracted, value = extract_regex_value(raw, extractor)

        assert extracted == "73.5"
        assert value == 73.5

    def test_unknown_string_returns_nan(self):
        """String with no numeric mapping returns NaN."""
        from cli_worker import extract_regex_value

        raw = "This is some non-matching text xyz123abc"
        extractor = "regex:cpu load (\\d+)"
        extracted, value = extract_regex_value(raw, extractor)

        assert extracted is None
        assert math.isnan(value)

    def test_no_match_returns_nan(self):
        """Regex pattern that does not match returns NaN."""
        from cli_worker import extract_regex_value

        raw = "Interface status: link down"
        extractor = "regex:uptime (\\d+)"
        extracted, value = extract_regex_value(raw, extractor)

        assert extracted is None
        assert math.isnan(value)

    def test_capture_group_index_1(self):
        """Capture group (1) extracts first group, not full match."""
        from cli_worker import extract_regex_value

        raw = "Description: FastEthernet0/1"
        extractor = "regex:Description: ([\\w/]+)"
        extracted, value = extract_regex_value(raw, extractor)

        assert extracted == "FastEthernet0/1"
        # FastEthernet0/1 is not a digit pattern and has no keyword → NaN
        assert math.isnan(value)

    def test_capture_group_index_2(self):
        """Capture group (2) extracts second group when multiple groups exist."""
        from cli_worker import extract_regex_value

        raw = "ip: 10.0.0.1, mask: 255.255.255.0"
        extractor = "regex:ip: ([0-9.]+), mask: ([0-9.]+)"
        extracted, value = extract_regex_value(raw, extractor)

        # Without explicit (n), uses group(1) → "10.0.0.1"
        assert extracted == "10.0.0.1"

    def test_explicit_group_2_returns_second_group(self):
        """Pattern with explicit (2) extracts the second capture group."""
        from cli_worker import extract_regex_value

        raw = "ip: 10.0.0.1, mask: 255.255.255.0"
        extractor = "regex:ip: ([0-9.]+), mask: ([0-9.]+)(2)"
        extracted, value = extract_regex_value(raw, extractor)

        assert extracted == "255.255.255.0"

    def test_empty_input_returns_nan(self):
        """Empty raw_output string returns NaN."""
        from cli_worker import extract_regex_value

        extracted, value = extract_regex_value("", "regex:foo")
        assert extracted is None
        assert math.isnan(value)

    def test_none_extractor_returns_nan(self):
        """Null extractor returns NaN."""
        from cli_worker import extract_regex_value

        extracted, value = extract_regex_value("some output", None)
        assert extracted is None
        assert math.isnan(value)

    def test_non_regex_prefix_returns_nan(self):
        """Extractor without 'regex:' prefix returns NaN."""
        from cli_worker import extract_regex_value

        extracted, value = extract_regex_value("some output", "just a pattern")
        assert extracted is None
        assert math.isnan(value)

    def test_invalid_regex_returns_nan(self):
        """Malformed regex pattern returns NaN."""
        from cli_worker import extract_regex_value

        extracted, value = extract_regex_value("some output", "regex:[invalid")
        assert extracted is None
        assert math.isnan(value)

    def test_enabled_keyword_maps_to_1(self):
        """'enabled' keyword maps to 1.0."""
        from cli_worker import extract_regex_value

        raw = "Port status: enabled"
        extractor = "regex:enabled"
        extracted, value = extract_regex_value(raw, extractor)

        assert value == 1.0

    def test_disabled_keyword_maps_to_0(self):
        """'disabled' keyword maps to 0.0."""
        from cli_worker import extract_regex_value

        raw = "Port status: disabled"
        extractor = "regex:disabled"
        extracted, value = extract_regex_value(raw, extractor)

        assert value == 0.0

    def test_ok_keyword_maps_to_1(self):
        """'ok' keyword maps to 1.0."""
        from cli_worker import extract_regex_value

        raw = "Operation: ok"
        extractor = "regex:ok"
        extracted, value = extract_regex_value(raw, extractor)

        assert value == 1.0

    def test_error_keyword_maps_to_0(self):
        """'error' keyword maps to 0.0."""
        from cli_worker import extract_regex_value

        raw = "Status: error"
        extractor = "regex:error"
        extracted, value = extract_regex_value(raw, extractor)

        assert value == 0.0

    def test_fail_keyword_maps_to_0(self):
        """'fail' keyword maps to 0.0."""
        from cli_worker import extract_regex_value

        raw = "Check: fail"
        extractor = "regex:fail"
        extracted, value = extract_regex_value(raw, extractor)

        assert value == 0.0


class TestResolveCredential:
    """Tests for resolve_credential(cli_credential_ref)."""

    def test_resolves_specific_ref_user_pass(self):
        """Given a credential ref, resolves USER and PASS from env."""
        with patch.dict(os.environ, {"MYDEV_USER": "admin", "MYDEV_PASS": "secret123"}):
            from cli_worker import resolve_credential
            username, password = resolve_credential("MYDEV")

            assert username == "admin"
            assert password == "secret123"

    def test_falls_back_to_default_when_ref_not_set(self):
        """When specific ref env vars are absent, falls back to CLI_DEFAULT_*."""
        env_backup = os.environ.get("CLI_DEFAULT_USER")
        pass_backup = os.environ.get("CLI_DEFAULT_PASS")

        try:
            os.environ["CLI_DEFAULT_USER"] = "default_user"
            os.environ["CLI_DEFAULT_PASS"] = "default_pass"
            # MYDEV_* not set
            with patch.dict(os.environ, {"CLI_DEFAULT_USER": "default_user", "CLI_DEFAULT_PASS": "default_pass"}, clear=False):
                # Ensure MYDEV_* are not present
                env = {k: v for k, v in os.environ.items() if k != "CLI_DEFAULT_USER" and k != "CLI_DEFAULT_PASS"}
                with patch.dict(os.environ, env, clear=False):
                    from cli_worker import resolve_credential
                    username, password = resolve_credential("MYDEV")

                    assert username == "default_user"
                    assert password == "default_pass"
        finally:
            if env_backup is not None:
                os.environ["CLI_DEFAULT_USER"] = env_backup
            else:
                os.environ.pop("CLI_DEFAULT_USER", None)
            if pass_backup is not None:
                os.environ["CLI_DEFAULT_PASS"] = pass_backup
            else:
                os.environ.pop("CLI_DEFAULT_PASS", None)

    def test_none_ref_defaults_to_cli_default(self):
        """When cli_credential_ref is None, uses CLI_DEFAULT_*."""
        with patch.dict(os.environ, {"CLI_DEFAULT_USER": "fallback_user", "CLI_DEFAULT_PASS": "fallback_pass"}, clear=False):
            from cli_worker import resolve_credential
            username, password = resolve_credential(None)

            assert username == "fallback_user"
            assert password == "fallback_pass"

    def test_partial_env_falls_back_correctly(self):
        """If only USER is set, PASS falls back even if specific ref provided."""
        with patch.dict(os.environ, {"MYDEV_USER": "specific_user", "CLI_DEFAULT_PASS": "fallback_pass"}, clear=False):
            from cli_worker import resolve_credential
            username, password = resolve_credential("MYDEV")

            assert username == "specific_user"
            assert password == "fallback_pass"


class TestApplyEscalation:
    """Tests for apply_escalation(client, escalation_script)."""

    def test_empty_script_returns_true(self):
        """Empty escalation_script returns True immediately."""
        from cli_worker import apply_escalation

        mock_client = MagicMock()
        result = apply_escalation(mock_client, "")
        assert result is True

    def test_none_script_returns_true(self):
        """None escalation_script returns True immediately."""
        from cli_worker import apply_escalation

        mock_client = MagicMock()
        result = apply_escalation(mock_client, None)
        assert result is True

    def test_single_enable_command_sends_one_line(self):
        """Single enable command is sent via client.send()."""
        from cli_worker import apply_escalation

        mock_client = MagicMock()
        mock_client.recv_ready.return_value = False
        mock_client.recv.return_value = b"router#"
        mock_client.settimeout = MagicMock()

        result = apply_escalation(mock_client, "enable")

        assert result is True
        mock_client.send.assert_called_once_with("enable\r")

    def test_two_line_script_sends_both_commands(self):
        """Two-line escalation script sends both commands in sequence."""
        from cli_worker import apply_escalation

        mock_client = MagicMock()
        mock_client.recv_ready.side_effect = [False, False]
        mock_client.recv.return_value = b"router#"
        mock_client.settimeout = MagicMock()

        result = apply_escalation(mock_client, "enable\nsecret_password")

        assert mock_client.send.call_count == 2
        mock_client.send.assert_any_call("enable\r")
        mock_client.send.assert_any_call("secret_password\r")

    def test_trims_whitespace_from_commands(self):
        """Leading/trailing whitespace is stripped from each command."""
        from cli_worker import apply_escalation

        mock_client = MagicMock()
        mock_client.recv_ready.return_value = False
        mock_client.recv.return_value = b"router#"
        mock_client.settimeout = MagicMock()

        result = apply_escalation(mock_client, "  enable  \n  secret_password  ")

        assert mock_client.send.call_count == 2
        mock_client.send.assert_any_call("enable\r")

    def test_ignores_empty_lines(self):
        """Empty lines in script are ignored."""
        from cli_worker import apply_escalation

        mock_client = MagicMock()
        mock_client.recv_ready.return_value = False
        mock_client.recv.return_value = b"router#"
        mock_client.settimeout = MagicMock()

        result = apply_escalation(mock_client, "enable\n\nsecret_password\n")

        assert mock_client.send.call_count == 2

    def test_no_hash_in_response_returns_false(self):
        """When output does not contain '#' prompt, returns False."""
        from cli_worker import apply_escalation

        mock_client = MagicMock()
        mock_client.recv_ready.return_value = False
        mock_client.recv.return_value = b"router>"
        mock_client.settimeout = MagicMock()

        result = apply_escalation(mock_client, "enable")

        assert result is False

    def test_configure_in_response_returns_true(self):
        """When '#' or 'configure' appears in output, returns True."""
        from cli_worker import apply_escalation

        mock_client = MagicMock()
        mock_client.recv_ready.return_value = False
        mock_client.recv.return_value = b"router#configure terminal"
        mock_client.settimeout = MagicMock()

        result = apply_escalation(mock_client, "enable")

        assert result is True


class TestNanRateLimiter:
    """Tests for NaN rate limiting logic."""

    def test_consecutive_nan_increments_counter(self):
        from cli_worker import _nan_tracker, check_nan_threshold, nan_rate_limiter

        # Reset tracker
        _nan_tracker.clear()

        metric_id = "test-cli-metric"

        # First NaN
        nan_rate_limiter(metric_id, float('nan'), "raw output", "Router-01")
        assert _nan_tracker.get(metric_id, 0) == 1

        # Second NaN
        nan_rate_limiter(metric_id, float('nan'), "raw output 2", "Router-01")
        assert _nan_tracker.get(metric_id, 0) == 2

    def test_valid_value_resets_counter(self):
        from cli_worker import _nan_tracker, nan_rate_limiter

        _nan_tracker.clear()
        metric_id = "test-cli-metric"

        _nan_tracker[metric_id] = 2  # Simulate 2 prior NaNs
        nan_rate_limiter(metric_id, 45.0, "output", "Router-01")

        assert _nan_tracker.get(metric_id, 0) == 0

    def test_threshold_3_triggers_alert(self):
        """At 3 consecutive NaNs, check_nan_threshold should emit an alert to Neo4j."""
        from cli_worker import _nan_tracker, check_nan_threshold

        _nan_tracker.clear()
        metric_id = "alert-test-metric"

        with patch("cli_worker.driver") as mock_driver:
            mock_session = MagicMock()
            mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

            for i in range(3):
                check_nan_threshold(metric_id, float('nan'), f"raw-{i}", "Router-01")

            # After 3rd NaN, should have emitted alert
            mock_session.run.assert_called()
            call_args = mock_session.run.call_args
            assert "CREATE (e:Event" in call_args[0][0]
            assert call_args[1]["mid"] == metric_id

    def test_valid_value_after_threshold_resets(self):
        """After alert is triggered, a valid value resets the counter."""
        from cli_worker import _nan_tracker, nan_rate_limiter

        _nan_tracker.clear()
        metric_id = "reset-test-metric"
        _nan_tracker[metric_id] = 3

        nan_rate_limiter(metric_id, 99.0, "good output", "Router-01")

        assert _nan_tracker.get(metric_id, 0) == 0
