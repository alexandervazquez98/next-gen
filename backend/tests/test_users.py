"""User lifecycle + per-user advisory lock tests (PR 3 — WU3)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from repositories import user_repo
from repositories.user_repo import UserRepository
from services.user_lock import acquire_user_lock, acquire_user_locks_in_order


# ---------------------------------------------------------------------------
# UserRepository.get_by_username
# ---------------------------------------------------------------------------


def test_get_by_username_returns_none_for_missing():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    assert UserRepository.get_by_username(db, "ghost") is None


def test_get_by_username_returns_row_when_present():
    db = MagicMock()
    row = MagicMock(username="op1", is_active=True)
    db.query.return_value.filter.return_value.first.return_value = row
    assert UserRepository.get_by_username(db, "op1") is row


# ---------------------------------------------------------------------------
# UserRepository.deactivate (logical, no destructive delete)
# ---------------------------------------------------------------------------


def test_deactivate_flips_is_active_and_does_not_delete():
    db = MagicMock()
    row = MagicMock(username="op1", is_active=True)
    db.query.return_value.filter.return_value.first.return_value = row

    result = UserRepository.deactivate(db, "op1", actor="admin")

    assert result is row
    assert row.is_active is False
    db.commit.assert_called_once()
    db.delete.assert_not_called()


def test_deactivate_returns_none_for_missing_user():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    assert UserRepository.deactivate(db, "ghost", actor="admin") is None
    db.commit.assert_not_called()


def test_deactivate_already_inactive_is_idempotent():
    db = MagicMock()
    row = MagicMock(username="op1", is_active=False)
    db.query.return_value.filter.return_value.first.return_value = row

    result = UserRepository.deactivate(db, "op1", actor="admin")

    assert result is row
    db.commit.assert_not_called()
    db.delete.assert_not_called()


def test_deactivate_does_not_touch_ticket_rows():
    """deactivate MUST NOT write to TicketFolio — historical snapshots stay valid."""
    from repositories import ticket_folio_repo

    with pytest.raises(AttributeError):
        ticket_folio_repo.TicketFolioRepository.deactivate

    db = MagicMock()
    row = MagicMock(username="op1", is_active=True)
    db.query.return_value.filter.return_value.first.return_value = row
    UserRepository.deactivate(db, "op1", actor="admin")
    assert row.is_active is False


# ---------------------------------------------------------------------------
# acquire_user_lock — single
# ---------------------------------------------------------------------------


def test_acquire_user_lock_uses_lowercased_key_and_xact_lock():
    session = MagicMock()
    acquire_user_lock(session, "Op1")

    assert session.execute.call_count == 1
    params = session.execute.call_args.kwargs
    assert params.get("key") == "user:op1"
    stmt = session.execute.call_args.args[0]
    assert "pg_advisory_xact_lock" in str(stmt)
    assert "hashtext" in str(stmt)


# ---------------------------------------------------------------------------
# acquire_user_locks_in_order — sorted, normalized, deduped
# ---------------------------------------------------------------------------


def test_in_order_returns_empty_for_blank_inputs():
    session = MagicMock()
    assert acquire_user_locks_in_order(session, ["", None, "   "]) == []
    session.execute.assert_not_called()


def test_in_order_locks_sorted_deduped_normalized():
    session = MagicMock()
    result = acquire_user_locks_in_order(session, ["Charlie", "alice", "BOB", "Bob", "ALICE"])

    assert result == ["alice", "bob", "charlie"]
    keys = [
        (c.kwargs.get("params") or (c.args[1] if len(c.args) > 1 else {})).get("key", "")
        for c in session.execute.call_args_list
    ]
    assert keys == ["user:alice", "user:bob", "user:charlie"]
