"""Tests for backend session policy resolution."""

import os
from types import SimpleNamespace

from services.session_policy import (
    SessionPolicy,
    resolve_session_policy_for_user,
    get_standard_session_policy,
    get_operational_session_policy,
)


class TestSessionPolicyResolution:
    def test_operational_role_is_resolved_from_config(self, monkeypatch):
        """A configured operational role resolves to operational profile."""
        monkeypatch.setenv("SESSION_OPERATIONAL_ENABLED", "true")
        monkeypatch.setenv("SESSION_OPERATIONAL_ROLES", "NOC,SOC")
        monkeypatch.setenv("SESSION_OPERATIONAL_USERS", "")
        monkeypatch.setenv("SESSION_OPERATIONAL_REFRESH_DAYS", "14")

        user = SimpleNamespace(username="operator", role="NOC")
        policy = resolve_session_policy_for_user(user)

        assert policy.profile == "operational"
        assert policy.access_token_minutes == int(
            os.getenv("SESSION_OPERATIONAL_ACCESS_MINUTES", "15")
        )
        assert policy.refresh_token_days == 14
        assert policy.persistent is True

    def test_operational_user_allowlist_is_resolved(self, monkeypatch):
        """Configured operational users are resolved as operational even if role differs."""
        monkeypatch.setenv("SESSION_OPERATIONAL_ENABLED", "true")
        monkeypatch.setenv("SESSION_OPERATIONAL_ROLES", "")
        monkeypatch.setenv("SESSION_OPERATIONAL_USERS", "ops1, ops2")

        user = SimpleNamespace(username="ops2", role="OPERATOR")
        policy = resolve_session_policy_for_user(user)

        assert policy.profile == "operational"

    def test_standard_policy_is_default_when_not_operational(self, monkeypatch):
        """When operational mode is disabled or role not in allowlist, policy is standard."""
        monkeypatch.delenv("SESSION_OPERATIONAL_ENABLED", raising=False)
        monkeypatch.setenv("SESSION_OPERATIONAL_ROLES", "NOC,SOC")
        monkeypatch.setenv("SESSION_STANDARD_ACCESS_MINUTES", "13")
        monkeypatch.setenv("SESSION_STANDARD_REFRESH_DAYS", "9")
        monkeypatch.setenv("SESSION_STANDARD_IDLE_TIMEOUT_MINUTES", "21")

        user = SimpleNamespace(username="jane", role="OPERATOR")
        policy = resolve_session_policy_for_user(user)

        assert policy.profile == "standard"
        assert policy.access_token_minutes == 13
        assert policy.refresh_token_days == 9
        assert policy.idle_timeout_minutes == 21
        assert policy.persistent is False

    def test_standard_profile_when_operational_is_explicitly_disabled(self, monkeypatch):
        """Explicit disable bypasses allowlist role/user resolution."""
        monkeypatch.setenv("SESSION_OPERATIONAL_ENABLED", "false")
        monkeypatch.setenv("SESSION_OPERATIONAL_ROLES", "NOC,SOC")
        monkeypatch.setenv("SESSION_OPERATIONAL_USERS", "ops2")

        user = SimpleNamespace(username="ops2", role="NOC")
        policy = resolve_session_policy_for_user(user)

        assert policy.profile == "standard"

    def test_standard_policy_helper_constructor(self):
        """Factory defaults are standard policy."""
        policy = get_standard_session_policy()
        assert policy.profile == "standard"
        assert policy.access_token_minutes > 0
        assert policy.refresh_token_days > 0
        assert policy.idle_timeout_minutes is not None

    def test_operational_policy_helper_constructor(self):
        """Factory defaults are operational policy."""
        policy = get_operational_session_policy()
        assert policy.profile == "operational"
        assert policy.persistent is True
        assert policy.idle_timeout_minutes is None
