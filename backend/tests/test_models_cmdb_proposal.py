"""Unit tests for the CI proposal Pydantic models — feat-cmdb-ai-handoff.

Covers REQ-CMAP-001:
- happy path: manifest with schema_version=1 and a complete ci block is accepted.
- malformed: missing ci.id / ci.label raises ValidationError.
- blocked metadata keys: ci.metadata containing a key in BLOCKED_AI_UPDATE_FIELDS
  raises ValidationError.

Also covers REQ-CMAP-013 at the model boundary: nested ``snmp.community`` is
preserved through ManifestPayload (the audit layer is what redacts).
"""

from __future__ import annotations

import pytest
from models.cmdb_proposal import CIProposalStatus, ManifestPayload
from models.core import BLOCKED_AI_UPDATE_FIELDS
from pydantic import ValidationError


def _manifest_ci(**overrides):
    ci = {
        "id": "CI-N9X3K2",
        "label": "Core Router Bogotá",
        "category": "Router",
        "brand": "Cisco",
        "model": "ASR-1000",
        "serialNumber": "FOC1234X5YZ",
        "firmwareVersion": "17.09.01a",
        "ip": "10.20.30.1",
        "owner": "NOC-LATAM",
        "location_name": "Bogotá DC-1",
        "status": "OK",
        "pollingInterval": 60,
        "metadata": {"rack": "R12", "role": "edge"},
        "snmp": {"version": "v2c", "community": "public-ro-xyz"},
    }
    ci.update(overrides)
    return ci


def _manifest_payload(**overrides):
    payload = {
        "schema_version": 1,
        "ci": _manifest_ci(),
        "rationale": "Spoke router for Bogotá DC upgrade.",
        "source_refs": ["chat:msg-2026-09-13-001"],
    }
    payload.update(overrides)
    return payload


class TestManifestPayload:
    def test_manifest_payload_accepts_v1(self):
        """Happy-path manifest passes validation (REQ-CMAP-001)."""
        payload = ManifestPayload(**_manifest_payload())
        assert payload.schema_version == 1
        assert payload.ci.id == "CI-N9X3K2"
        # category is coerced to type (Node.required). The audit layer and
        # category-resolution helpers consume ``ci.type`` everywhere.
        assert payload.ci.type == "Router"
        assert payload.ci.snmp["community"] == "public-ro-xyz"

    def test_manifest_rejects_missing_ci_id(self):
        """Missing ci.id MUST raise ValidationError (REQ-CMAP-001)."""
        ci = _manifest_ci()
        ci.pop("id")
        with pytest.raises(ValidationError) as exc:
            ManifestPayload(**_manifest_payload(ci=ci))
        # Error must mention the missing field path so the API client can fix it.
        flat = exc.value.errors()
        assert any(err.get("loc") and "id" in err["loc"] for err in flat), (
            f"ValidationError did not mention 'id' field: {flat}"
        )

    def test_manifest_rejects_missing_ci_label(self):
        """Missing ci.label MUST raise ValidationError (REQ-CMAP-001)."""
        ci = _manifest_ci()
        ci.pop("label")
        with pytest.raises(ValidationError):
            ManifestPayload(**_manifest_payload(ci=ci))

    def test_manifest_rejects_blocked_metadata_keys(self):
        """ci.metadata MUST NOT contain keys in BLOCKED_AI_UPDATE_FIELDS (REQ-CMAP-001)."""
        # The 'ip' key is in the blocked list. Even though 'ip' is also a top-level
        # Node field, the validator must reject its presence inside metadata.
        ci = _manifest_ci(metadata={"ip": "1.2.3.4", "rack": "R12"})
        with pytest.raises(ValidationError) as exc:
            ManifestPayload(**_manifest_payload(ci=ci))
        assert "blocked" in str(exc.value).lower(), (
            f"ValidationError should mention 'blocked': {exc.value}"
        )
        assert "ip" in str(exc.value), (
            f"ValidationError should mention 'ip' as the offending key: {exc.value}"
        )

    def test_manifest_rejects_unknown_schema_version(self):
        """schema_version != 1 MUST raise ValidationError (REQ-CMAP-001)."""
        with pytest.raises(ValidationError) as exc:
            ManifestPayload(**_manifest_payload(schema_version=2))
        assert "schema_version" in str(exc.value)

    def test_manifest_rejects_negative_schema_version(self):
        """Negative schema_version MUST raise ValidationError (REQ-CMAP-001)."""
        with pytest.raises(ValidationError):
            ManifestPayload(**_manifest_payload(schema_version=-1))

    def test_manifest_accepts_optional_rationale_and_source_refs(self):
        """rationale and source_refs are optional but default to safe values."""
        payload = ManifestPayload.model_validate(
            {
                "schema_version": 1,
                "ci": _manifest_ci(),
            }
        )
        assert payload.rationale == ""
        assert payload.source_refs == []


class TestBlockedFieldsConstant:
    def test_blocked_ai_update_fields_is_a_frozenset(self):
        """The constant MUST be a frozenset so callers cannot mutate it."""
        from models.core import BLOCKED_AI_UPDATE_FIELDS as F
        assert isinstance(F, frozenset), (
            f"BLOCKED_AI_UPDATE_FIELDS should be immutable (frozenset), got {type(F)}"
        )

    def test_blocked_includes_security_sensitive_fields(self):
        """Blocked keys MUST include security-sensitive CI fields."""
        for key in ("id", "label", "ip", "snmp", "brand", "model"):
            assert key in BLOCKED_AI_UPDATE_FIELDS, (
                f"{key} must be in BLOCKED_AI_UPDATE_FIELDS"
            )


class TestCIProposalStatus:
    def test_status_enum_has_three_values(self):
        """CIProposalStatus MUST have DRAFT, APPROVED, REVOKED."""
        members = {member.value for member in CIProposalStatus}
        assert members == {"DRAFT", "APPROVED", "REVOKED"}

    def test_status_values_are_strings(self):
        """All status values must be strings (str enum)."""
        for member in CIProposalStatus:
            assert isinstance(member, str)
            assert isinstance(member.value, str)
