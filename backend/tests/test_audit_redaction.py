"""Unit tests for audit redaction walker — feat-cmdb-ai-handoff.

REQ-AUDIT-003 / REQ-CMAP-013:
- redact SNMP community / authKey / privKey
- redact any key matching *key|*token|*secret|*password (case-insensitive)
- walk nested metadata, snmp, and any other dict
- never mutate the input
"""

from __future__ import annotations

import pytest
from services.audit_service import SECRET_FIELD_PATTERN, redact_manifest_secrets

REDACTED = "<REDACTED>"


class TestSecretFieldPattern:
    def test_pattern_is_module_level_constant(self):
        """The regex MUST be exposed as a module-level constant (REQ-CMAP-013 design)."""
        import re

        assert isinstance(
            SECRET_FIELD_PATTERN, re.Pattern
        ), "SECRET_FIELD_PATTERN must be a compiled regex for reuse + performance"

    @pytest.mark.parametrize(
        "key",
        [
            "apiKey",
            "API_KEY",
            "APIkey",
            "token",
            "refresh_token",
            "accessToken",
            "secret",
            "password",
            "Password",
        ],
    )
    def test_pattern_matches_secret_like_keys(self, key):
        """Keys matching *key|*token|*secret|*password MUST match the regex (case-insensitive)."""
        assert SECRET_FIELD_PATTERN.search(key), f"SECRET_FIELD_PATTERN must match {key!r}"

    @pytest.mark.parametrize(
        "key",
        [
            "community",
            "authkey",
            "privkey",
            "COMMUNITY",
            "AuthKey",
        ],
    )
    def test_hardcoded_snmp_keys_handled_separately(self, key):
        """SNMP-specific leaves (community/authKey/privKey) MUST be matched via the hard-coded set.

        They don't match the regex (no key/token/secret/password substring) but
        the walker also checks a hard-coded set — see ``_is_secret_key``.
        """
        # Use the walker indirectly: redact_manifest_secrets on a manifest with this key
        # in snmp namespace MUST replace its value.
        from services.audit_service import redact_manifest_secrets

        manifest = {"snmp": {key: "secret-value"}}
        result = redact_manifest_secrets(manifest)
        # The walker iterates dict keys directly so the leaf name is the original (mixed-case)
        # in the dict iteration; we check the leaf value was redacted.
        # The walker checks ``leaf in _HARD_CODED_SECRET_LEAVES`` with the leaf lowered.
        assert result["snmp"][key] == REDACTED, f"snmp.{key} MUST be redacted via hard-coded set"


class TestRedactManifestSecrets:
    def test_redact_snmp_community(self):
        """snmp.community MUST be replaced with <REDACTED>."""
        manifest = {"snmp": {"community": "public-ro-xyz"}}
        result = redact_manifest_secrets(manifest)
        assert result["snmp"]["community"] == REDACTED

    def test_redact_snmp_auth_and_priv_keys(self):
        """snmp.authKey and snmp.privKey MUST be replaced."""
        manifest = {
            "snmp": {
                "version": "v3",
                "authKey": "authsecret-xyz",
                "privKey": "privsecret-xyz",
            }
        }
        result = redact_manifest_secrets(manifest)
        assert result["snmp"]["authKey"] == REDACTED
        assert result["snmp"]["privKey"] == REDACTED
        assert result["snmp"]["version"] == "v3"  # non-secret untouched

    def test_redact_keys_tokens_passwords_case_insensitive(self):
        """Any key matching *key|*token|*secret|*password (case-insensitive) MUST be redacted."""
        manifest = {
            "apiKey": "k1",
            "API_KEY": "k2",
            "refresh_token": "tok1",
            "clientSecret": "s1",
            "userPassword": "p1",
            "label": "Router-01",  # non-secret — must remain
        }
        result = redact_manifest_secrets(manifest)
        assert result["apiKey"] == REDACTED
        assert result["API_KEY"] == REDACTED
        assert result["refresh_token"] == REDACTED
        assert result["clientSecret"] == REDACTED
        assert result["userPassword"] == REDACTED
        assert result["label"] == "Router-01"

    def test_redact_walks_nested_metadata(self):
        """Nested metadata dicts MUST be walked too."""
        manifest = {
            "metadata": {
                "api_token": "xyz",
                "rack": "R12",  # safe — stays
                "nested": {"inner_key": "k", "inner_value": "v"},
            }
        }
        result = redact_manifest_secrets(manifest)
        assert result["metadata"]["api_token"] == REDACTED
        assert result["metadata"]["rack"] == "R12"
        assert result["metadata"]["nested"]["inner_key"] == REDACTED
        assert result["metadata"]["nested"]["inner_value"] == "v"

    def test_does_not_mutate_input(self):
        """The walker MUST NOT mutate the input manifest (REQ-CMAP-013 invariant)."""
        manifest = {
            "snmp": {"community": "public-ro-xyz"},
            "metadata": {"api_token": "xyz"},
        }
        original = {
            "snmp": {"community": "public-ro-xyz"},
            "metadata": {"api_token": "xyz"},
        }
        _ = redact_manifest_secrets(manifest)
        assert manifest == original

    def test_walks_lists_of_dicts(self):
        """Lists of dicts (e.g. metrics) MUST also be walked."""
        manifest = {
            "metrics": [
                {"id": "cpu", "api_key": "k"},
                {"id": "mem"},
            ]
        }
        result = redact_manifest_secrets(manifest)
        assert result["metrics"][0]["api_key"] == REDACTED
        assert result["metrics"][0]["id"] == "cpu"
        assert result["metrics"][1]["id"] == "mem"

    def test_safe_value_passes_through(self):
        """A manifest with no secret-shaped keys MUST pass through unchanged (modulo copies)."""
        manifest = {
            "id": "CI-NEW",
            "label": "Core Router",
            "category": "Router",
            "metadata": {"rack": "R12", "role": "edge"},
        }
        result = redact_manifest_secrets(manifest)
        assert result == manifest

    def test_audit_context_allows_proposal_keys(self):
        """AUDIT_CONTEXT_ALLOWED_KEYS MUST include the CI_PROPOSAL_* keys."""
        from services.audit_service import AUDIT_CONTEXT_ALLOWED_KEYS

        for key in (
            "proposal_id",
            "proposed_by",
            "actor_role",
            "previous_state",
            "next_state",
            "version",
            "resulted_ci_id",
            "applied_manifest_summary",
            "applied_manifest_attributes",
            "manifest_diff",
            "revoke_reason",
        ):
            assert (
                key in AUDIT_CONTEXT_ALLOWED_KEYS
            ), f"AUDIT_CONTEXT_ALLOWED_KEYS must include {key}"
