"""Unit tests for AIPermission enum — pure model validation, no external deps."""

from models.user import AIPermission, UserPermission


class TestAIPermissionEnum:
    """Tests for AIPermission enum completeness and string values."""

    def test_enum_has_8_values(self):
        """AIPermission enum must have exactly 8 defined values after feat-cmdb-ai-handoff."""
        members = list(AIPermission)
        assert len(members) == 8, f"Expected 8 AIPermission values, got {len(members)}: {members}"

    def test_ai_run_diagnostic_value(self):
        """AI_RUN_DIAGNOSTIC must be defined and have the correct string value."""
        assert hasattr(AIPermission, "AI_RUN_DIAGNOSTIC")
        assert AIPermission.AI_RUN_DIAGNOSTIC.value == "AI_RUN_DIAGNOSTIC"

    def test_ai_view_all_value(self):
        """AI_VIEW_ALL must be defined and have the correct string value."""
        assert hasattr(AIPermission, "AI_VIEW_ALL")
        assert AIPermission.AI_VIEW_ALL.value == "AI_VIEW_ALL"

    def test_ai_event_ack_value(self):
        """AI_EVENT_ACK must be defined and have the correct string value."""
        assert hasattr(AIPermission, "AI_EVENT_ACK")
        assert AIPermission.AI_EVENT_ACK.value == "AI_EVENT_ACK"

    def test_ai_event_comment_value(self):
        """AI_EVENT_COMMENT must be defined and have the correct string value."""
        assert hasattr(AIPermission, "AI_EVENT_COMMENT")
        assert AIPermission.AI_EVENT_COMMENT.value == "AI_EVENT_COMMENT"

    def test_ai_ci_update_metadata_value(self):
        """AI_CI_UPDATE_METADATA must be defined and have the correct string value."""
        assert hasattr(AIPermission, "AI_CI_UPDATE_METADATA")
        assert AIPermission.AI_CI_UPDATE_METADATA.value == "AI_CI_UPDATE_METADATA"

    def test_ai_event_close_value(self):
        """AI_EVENT_CLOSE must be defined and have the correct string value."""
        assert hasattr(AIPermission, "AI_EVENT_CLOSE")
        assert AIPermission.AI_EVENT_CLOSE.value == "AI_EVENT_CLOSE"

    def test_ai_dictionary_preview_value(self):
        """AI_DICTIONARY_PREVIEW must be defined and have the correct string value."""
        assert hasattr(AIPermission, "AI_DICTIONARY_PREVIEW")
        assert AIPermission.AI_DICTIONARY_PREVIEW.value == "AI_DICTIONARY_PREVIEW"

    # feat-cmdb-ai-handoff — REQ-CMAP-004
    def test_ai_propose_ci_enum_member(self):
        """AI_PROPOSE_CI must be defined and have the correct string value (REQ-CMAP-004)."""
        assert hasattr(
            AIPermission, "AI_PROPOSE_CI"
        ), "AI_PROPOSE_CI is required by feat-cmdb-ai-handoff to gate POST /api/cmdb/proposals"
        assert AIPermission.AI_PROPOSE_CI.value == "AI_PROPOSE_CI"


class TestUserPermissionEnum:
    """Tests for UserPermission additions for feat-cmdb-ai-handoff (REQ-CMAP-005)."""

    def test_ci_approve_proposal_enum_member(self):
        """CI_APPROVE_PROPOSAL must be defined and have the correct string value (REQ-CMAP-005)."""
        assert hasattr(
            UserPermission, "CI_APPROVE_PROPOSAL"
        ), "CI_APPROVE_PROPOSAL is required to gate POST /api/cmdb/proposals/{id}/approve|revoke"
        assert UserPermission.CI_APPROVE_PROPOSAL.value == "CI_APPROVE_PROPOSAL"

    def test_all_values_are_strings(self):
        """All AIPermission values must be strings (str enum)."""
        for member in AIPermission:
            assert isinstance(member, str), f"{member} is not a string enum"

    def test_all_values_match_expected_format(self):
        """All AIPermission values must start with 'AI_' prefix."""
        for member in AIPermission:
            assert member.value.startswith("AI_"), f"{member.value} does not start with 'AI_'"
