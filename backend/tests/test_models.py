"""Unit tests for Pydantic models — pure validation logic, no external deps."""

import pytest
from pydantic import ValidationError
from models.user import (
    UserCreate,
    UserUpdate,
    User,
    UserInDB,
    Token,
    TokenData,
    UserRole,
    UserPermission,
    PasswordChangeRequest,
)
from models.core import Node, Link, MetricDef, Category, OwnerGroup


class TestUserCreateModel:
    """Tests for UserCreate Pydantic model validation."""

    def test_valid_user_create(self):
        user = UserCreate(
            username="testuser",
            password="SecureP@ss123",
            role="OPERATOR",
            permissions=[UserPermission.EVENT_VIEW],
        )
        assert user.username == "testuser"
        assert user.role == "OPERATOR"

    def test_default_role_is_viewer(self):
        user = UserCreate(username="newuser", password="pass123")
        assert user.role == "VIEWER"

    def test_default_permissions_empty(self):
        user = UserCreate(username="newuser", password="pass123")
        assert user.permissions == []

    def test_missing_password_raises_error(self):
        with pytest.raises(ValidationError):
            UserCreate(username="newuser")

    def test_missing_username_raises_error(self):
        with pytest.raises(ValidationError):
            UserCreate(password="pass123")


class TestUserModel:
    """Tests for User Pydantic model."""

    def test_default_disabled_is_false(self):
        user = User(username="test", role="VIEWER")
        assert user.disabled is False

    def test_default_force_password_change_is_false(self):
        user = User(username="test", role="VIEWER")
        assert user.force_password_change is False


class TestTokenModel:
    """Tests for Token Pydantic model."""

    def test_valid_token(self):
        token = Token(access_token="abc123", token_type="bearer")
        assert token.access_token == "abc123"
        assert token.token_type == "bearer"

    def test_missing_fields_raises_error(self):
        with pytest.raises(ValidationError):
            Token(access_token="abc123")


class TestPasswordChangeRequest:
    """Tests for PasswordChangeRequest model."""

    def test_valid_request(self):
        req = PasswordChangeRequest(old_password="old123", new_password="new456")
        assert req.old_password == "old123"
        assert req.new_password == "new456"

    def test_missing_old_password_raises_error(self):
        with pytest.raises(ValidationError):
            PasswordChangeRequest(new_password="new456")


class TestNodeModel:
    """Tests for Node (CI) Pydantic model."""

    def test_minimal_node(self):
        node = Node(id="ci-001", label="Router-01", type="router")
        assert node.status == "OK"
        assert node.pollingInterval == 60
        assert node.metadata == {}
        assert node.metrics == []

    def test_node_with_optional_fields(self):
        node = Node(
            id="ci-002",
            label="Switch-01",
            type="switch",
            ip="192.168.1.1",
            brand="Cisco",
            model="Catalyst 9300",
        )
        assert node.ip == "192.168.1.1"
        assert node.brand == "Cisco"

    def test_missing_required_fields_raises_error(self):
        with pytest.raises(ValidationError):
            Node(label="Missing ID")


class TestLinkModel:
    """Tests for Link Pydantic model."""

    def test_minimal_link(self):
        link = Link(source="ci-1", target="ci-2", relationship="DEPENDS_ON")
        assert link.relationship == "DEPENDS_ON"
        assert link.id is None

    def test_missing_required_fields_raises_error(self):
        with pytest.raises(ValidationError):
            Link(source="ci-1")


class TestMetricDefModel:
    """Tests for MetricDef Pydantic model."""

    def test_default_protocol_is_snmp(self):
        metric = MetricDef(id="cpu-load")
        assert metric.protocol == "SNMP"

    def test_default_data_type_is_integer(self):
        metric = MetricDef(id="mem-usage")
        assert metric.dataType == "INTEGER"

    def test_full_metric(self):
        metric = MetricDef(
            id="cpu-load",
            protocol="SNMP",
            oid="1.3.6.1.2.1.25.3.3.1.2",
            warning=80.0,
            critical=95.0,
            unit="%",
            description="CPU Load percentage",
        )
        assert metric.warning == 80.0
        assert metric.critical == 95.0
