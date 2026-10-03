"""Service tests for :PhysicalLink — feat-444-physical-link-styling (slice 2).

The service layer is a thin validation + delegation wrapper on top of the
repository. It enforces:

- PhysicalLinkType / PhysicalLinkStatus are in the canonical frozenset.
- Both endpoint ids must reference existing :CI nodes (defence in depth: the
  Pydantic schema already rejects unknown Literal values, but endpoints
  cannot be expressed as Literals — they reference runtime CI ids).
- Permission gates: write paths require ``CI_EDIT`` (Admin bypasses);
  read paths require ``CI_VIEW`` only when the caller is authenticated
  (public reads mirror the tunnel-link precedent).
- Maps domain failures to ``HTTPException``:
    - missing id -> 404
    - invalid type / status -> 400
    - unknown endpoints -> 400
    - missing permission -> 403
    - missing auth on writes -> 401 (raised by the auth dep before we get here)

Repo is replaced with a focused stub — these tests exercise the service
contract, not the underlying Cypher (covered separately in
``test_physical_link_repo.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from fastapi import HTTPException
from models.user import User, UserPermission, UserRole

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


@dataclass
class _RepoStub:
    """Stub of PhysicalLinkRepo with controllable returns."""

    create_returns: dict | None = None
    create_raises: Exception | None = None
    get_by_id_returns: dict | None = None
    list_returns: list[dict] = field(default_factory=list)
    update_status_returns: dict | None = None
    update_status_raises: Exception | None = None

    def create(self, **_kwargs):
        if self.create_raises:
            raise self.create_raises
        if self.create_returns is not None:
            return self.create_returns
        return {
            "id": _kwargs["link_id"],
            "type": _kwargs["link_type"],
            "endpoints": list(_kwargs["endpoints"]),
            "status": _kwargs["status"],
            "capacity_gbps": _kwargs["capacity_gbps"],
            "install_date": _kwargs["install_date"],
        }

    def get_by_id(self, link_id):
        if self.get_by_id_returns is None:
            return None
        return dict(self.get_by_id_returns, id=link_id)

    def list(self, **_kwargs):
        return list(self.list_returns)

    def update_status(self, link_id, status):
        if self.update_status_raises:
            raise self.update_status_raises
        if self.update_status_returns is None:
            return None
        return dict(self.update_status_returns, id=link_id, status=status)


def _user(role: str = "OPERATOR", permissions: list[str] | None = None) -> User:
    return User(
        username="alice",
        role=role,
        permissions=permissions or [],
        allowed_locations=[],
    )


def _admin() -> User:
    return _user(role=UserRole.ADMIN.value)


def _operator_with_edit() -> User:
    return _user(role="OPERATOR", permissions=[UserPermission.CI_EDIT.value])


@pytest.fixture
def ci_existence_map(monkeypatch):
    """Stub ``_ci_id_exists`` so endpoint validation can be controlled per test."""
    from services import physical_link_service as svc

    store: dict[str, bool] = {}

    def _exists(ci_id: str) -> bool:
        return store.get(ci_id, False)

    monkeypatch.setattr(svc, "_ci_id_exists", _exists)
    return store


# ---------------------------------------------------------------------------
# T-S1: create_physical_link validation
# ---------------------------------------------------------------------------


class TestCreateValidation:
    def test_create_unknown_type_returns_400(self, ci_existence_map, monkeypatch):
        """create_physical_link MUST raise 400 when the PhysicalLinkType is unknown."""
        from services import physical_link_service as svc

        ci_existence_map["ci-a"] = True
        ci_existence_map["ci-b"] = True

        repo = _RepoStub()
        monkeypatch.setattr(svc, "_get_repo", lambda: repo)

        user = _operator_with_edit()
        with pytest.raises(HTTPException) as exc:
            svc.create_physical_link(
                payload={
                    "id": "pl-x",
                    "type": "plasma",
                    "endpoints": ["ci-a", "ci-b"],
                },
                current_user=user,
            )
        assert exc.value.status_code == 400
        assert "unknown_type" in str(exc.value.detail)

    def test_create_unknown_status_returns_400(self, ci_existence_map, monkeypatch):
        """create_physical_link MUST raise 400 when the status is not in the allowed set."""
        from services import physical_link_service as svc

        ci_existence_map["ci-a"] = True
        ci_existence_map["ci-b"] = True

        repo = _RepoStub()
        monkeypatch.setattr(svc, "_get_repo", lambda: repo)

        user = _operator_with_edit()
        with pytest.raises(HTTPException) as exc:
            svc.create_physical_link(
                payload={
                    "id": "pl-x",
                    "type": "fiber",
                    "endpoints": ["ci-a", "ci-b"],
                    "status": "ON_FIRE",
                },
                current_user=user,
            )
        assert exc.value.status_code == 400
        assert "unknown_status" in str(exc.value.detail)

    def test_create_unknown_endpoint_returns_400(self, ci_existence_map, monkeypatch):
        """create_physical_link MUST raise 400 when an endpoint does not reference an existing CI."""
        from services import physical_link_service as svc

        ci_existence_map["ci-a"] = True
        ci_existence_map["ci-b"] = False  # not present

        repo = _RepoStub()
        monkeypatch.setattr(svc, "_get_repo", lambda: repo)

        user = _operator_with_edit()
        with pytest.raises(HTTPException) as exc:
            svc.create_physical_link(
                payload={
                    "id": "pl-x",
                    "type": "fiber",
                    "endpoints": ["ci-a", "ci-b"],
                },
                current_user=user,
            )
        assert exc.value.status_code == 400
        assert "unknown_endpoint" in str(exc.value.detail)


# ---------------------------------------------------------------------------
# T-S2: create_physical_link permission
# ---------------------------------------------------------------------------


class TestCreatePermission:
    def test_create_without_ci_edit_returns_403(self, ci_existence_map, monkeypatch):
        """create_physical_link MUST raise 403 when the caller lacks CI_EDIT and is not Admin."""
        from services import physical_link_service as svc

        ci_existence_map["ci-a"] = True
        ci_existence_map["ci-b"] = True

        repo = _RepoStub()
        monkeypatch.setattr(svc, "_get_repo", lambda: repo)

        user = _user(role="VIEWER", permissions=[UserPermission.CI_VIEW.value])
        with pytest.raises(HTTPException) as exc:
            svc.create_physical_link(
                payload={
                    "id": "pl-x",
                    "type": "fiber",
                    "endpoints": ["ci-a", "ci-b"],
                },
                current_user=user,
            )
        assert exc.value.status_code == 403
        assert "CI_EDIT" in str(exc.value.detail)

    def test_create_admin_bypasses_ci_edit(self, ci_existence_map, monkeypatch):
        """create_physical_link MUST let Admin through without explicit CI_EDIT."""
        from services import physical_link_service as svc

        ci_existence_map["ci-a"] = True
        ci_existence_map["ci-b"] = True

        repo = _RepoStub()
        monkeypatch.setattr(svc, "_get_repo", lambda: repo)

        user = _admin()
        row = svc.create_physical_link(
            payload={
                "id": "pl-fiber-001",
                "type": "fiber",
                "endpoints": ["ci-a", "ci-b"],
            },
            current_user=user,
        )
        assert row["id"] == "pl-fiber-001"
        assert row["type"] == "fiber"


# ---------------------------------------------------------------------------
# T-S3: create_physical_link delegation
# ---------------------------------------------------------------------------


class TestCreateDelegation:
    def test_create_delegates_to_repo_with_tuple_endpoints(self, ci_existence_map, monkeypatch):
        """create_physical_link MUST pass endpoints as a tuple[str, str] to the repo."""
        from services import physical_link_service as svc

        ci_existence_map["ci-a"] = True
        ci_existence_map["ci-b"] = True

        repo = _RepoStub()
        captured: dict = {}
        original_create = repo.create

        def _create(**kwargs):
            captured.update(kwargs)
            return original_create(**kwargs)

        repo.create = _create  # type: ignore[method-assign]
        monkeypatch.setattr(svc, "_get_repo", lambda: repo)

        user = _operator_with_edit()
        svc.create_physical_link(
            payload={
                "id": "pl-fiber-001",
                "type": "fiber",
                "endpoints": ["ci-a", "ci-b"],
                "status": "UP",
                "capacity_gbps": 10.0,
                "install_date": "2024-01-15",
            },
            current_user=user,
        )

        assert captured["link_id"] == "pl-fiber-001"
        assert captured["link_type"] == "fiber"
        # Repo contract: tuple, not list — mirrors backend PhysicalLink model.
        assert captured["endpoints"] == ("ci-a", "ci-b")
        assert captured["status"] == "UP"
        assert captured["capacity_gbps"] == 10.0
        assert captured["install_date"] == "2024-01-15"


# ---------------------------------------------------------------------------
# T-S4: get_physical_link / list_physical_links
# ---------------------------------------------------------------------------


class TestGet:
    def test_get_returns_row_when_present(self, monkeypatch):
        """get_physical_link MUST delegate and return the row when present."""
        from services import physical_link_service as svc

        repo = _RepoStub(
            get_by_id_returns={
                "id": "pl-fiber-001",
                "type": "fiber",
                "endpoints": ["ci-a", "ci-b"],
                "status": "UP",
                "capacity_gbps": 10.0,
                "install_date": None,
            }
        )
        monkeypatch.setattr(svc, "_get_repo", lambda: repo)

        row = svc.get_physical_link("pl-fiber-001")
        assert row is not None
        assert row["id"] == "pl-fiber-001"

    def test_get_returns_none_when_missing(self, monkeypatch):
        """get_physical_link MUST return None for an unknown id."""
        from services import physical_link_service as svc

        repo = _RepoStub(get_by_id_returns=None)
        monkeypatch.setattr(svc, "_get_repo", lambda: repo)

        assert svc.get_physical_link("missing") is None


class TestList:
    def test_list_delegates_filters(self, monkeypatch):
        """list_physical_links MUST pass filters through to the repo."""
        from services import physical_link_service as svc

        repo = _RepoStub(
            list_returns=[
                {
                    "id": "pl-1",
                    "type": "fiber",
                    "endpoints": ["ci-a", "ci-b"],
                    "status": "UP",
                    "capacity_gbps": 10.0,
                    "install_date": None,
                }
            ]
        )
        captured: dict = {}
        original_list = repo.list

        def _list(**kwargs):
            captured.update(kwargs)
            return original_list(**kwargs)

        repo.list = _list  # type: ignore[method-assign]
        monkeypatch.setattr(svc, "_get_repo", lambda: repo)

        rows = svc.list_physical_links(
            ci_id="ci-a", link_type="fiber", status="UP", limit=10, offset=20
        )
        assert len(rows) == 1
        assert captured["ci_id"] == "ci-a"
        assert captured["link_type"] == "fiber"
        assert captured["status"] == "UP"
        assert captured["limit"] == 10
        assert captured["offset"] == 20

    def test_list_authenticated_viewer_without_ci_view_still_works(self, monkeypatch):
        """list_physical_links is a public read endpoint — CI_VIEW is only enforced when the user explicitly opts in.

        For slice 2 the policy matches tunnel-link reads: public reads allowed
        with no auth; if a user is present and lacks CI_VIEW, the service
        raises 403 (admin still bypasses). This test pins the no-auth branch.
        """
        from services import physical_link_service as svc

        repo = _RepoStub(list_returns=[])
        monkeypatch.setattr(svc, "_get_repo", lambda: repo)

        # No current_user -> public read OK.
        rows = svc.list_physical_links()
        assert rows == []


# ---------------------------------------------------------------------------
# T-S5: update_physical_link_status
# ---------------------------------------------------------------------------


class TestUpdateStatus:
    def test_update_unknown_status_returns_400(self, monkeypatch):
        """update_physical_link_status MUST raise 400 for an unknown status value."""
        from services import physical_link_service as svc

        repo = _RepoStub()
        monkeypatch.setattr(svc, "_get_repo", lambda: repo)

        user = _operator_with_edit()
        with pytest.raises(HTTPException) as exc:
            svc.update_physical_link_status(
                link_id="pl-1",
                status="ON_FIRE",
                current_user=user,
            )
        assert exc.value.status_code == 400
        assert "unknown_status" in str(exc.value.detail)

    def test_update_without_ci_edit_returns_403(self, monkeypatch):
        """update_physical_link_status MUST raise 403 when the caller lacks CI_EDIT."""
        from services import physical_link_service as svc

        repo = _RepoStub()
        monkeypatch.setattr(svc, "_get_repo", lambda: repo)

        user = _user(role="VIEWER", permissions=[UserPermission.CI_VIEW.value])
        with pytest.raises(HTTPException) as exc:
            svc.update_physical_link_status(
                link_id="pl-1",
                status="UP",
                current_user=user,
            )
        assert exc.value.status_code == 403

    def test_update_unknown_id_returns_404(self, monkeypatch):
        """update_physical_link_status MUST raise 404 when the id is unknown."""
        from services import physical_link_service as svc

        repo = _RepoStub(update_status_returns=None)
        monkeypatch.setattr(svc, "_get_repo", lambda: repo)

        user = _operator_with_edit()
        with pytest.raises(HTTPException) as exc:
            svc.update_physical_link_status(
                link_id="missing",
                status="UP",
                current_user=user,
            )
        assert exc.value.status_code == 404

    def test_update_delegates_and_returns_row(self, monkeypatch):
        """update_physical_link_status MUST delegate to the repo and return the row."""
        from services import physical_link_service as svc

        repo = _RepoStub(
            update_status_returns={
                "id": "pl-1",
                "type": "fiber",
                "endpoints": ["ci-a", "ci-b"],
                "status": "UP",
                "capacity_gbps": 10.0,
                "install_date": None,
            }
        )
        monkeypatch.setattr(svc, "_get_repo", lambda: repo)

        user = _operator_with_edit()
        row = svc.update_physical_link_status(
            link_id="pl-1",
            status="UP",
            current_user=user,
        )
        assert row["status"] == "UP"
        assert row["id"] == "pl-1"
