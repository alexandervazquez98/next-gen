"""Repository tests for ITSM ticket/folio assignee persistence (PR 3 — WU3)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from models.itsm import TicketFolioCreate
from repositories.ticket_folio_repo import TicketFolioRepository


def _record(**over):
    base = {
        "ticket_id": 1,
        "type": "incident",
        "title": "Router down",
        "description": "down",
        "service_catalog_id": "NET-INC-001",
        "status": "open",
        "archived": False,
        "closed_reason": None,
        "created_at": datetime.now(tz=UTC).replace(microsecond=0).isoformat(),
        "updated_at": datetime.now(tz=UTC).replace(microsecond=0).isoformat(),
        "updated_by": "admin",
        "assignee_username": "op1",
        "assignee_display_name": "Operator One",
        "assignee_active_at_assignment": True,
        "assignee_currently_active": True,
    }
    base.update(over)
    return base


def _wire(repo, row):
    session = MagicMock()
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = False
    driver = MagicMock()
    driver.session.return_value = ctx

    # ``execute_write`` MUST invoke the transactional callable so the
    # repository's post-write logic (``record["assignee_currently_active"]``)
    # actually runs in tests. We expose the synthetic ``tx`` so assertions
    # can inspect the Cypher and bind params via ``tx.run``.
    tx_holder: dict = {}

    def _execute_write(callable_, *args, **kwargs):
        tx = MagicMock()
        tx.run.return_value.single.return_value = row
        tx_holder["tx"] = tx
        return callable_(tx, *args, **kwargs)

    execute_write = MagicMock(side_effect=_execute_write)
    session.execute_write = execute_write
    session.run.return_value.single.return_value = row
    repo._driver = driver
    execute_write._tx_holder = tx_holder  # type: ignore[attr-defined]
    return execute_write


def test_create_persists_assignee_snapshot():
    repo = TicketFolioRepository()
    write = _wire(repo, _record())

    payload = TicketFolioCreate(
        type="incident",
        title="Router down",
        service_catalog_id="NET-INC-001",
        assignee_username="op1",
    )
    result = repo.create_with_generated_id(payload)

    assert result["assignee_username"] == "op1"
    assert result["assignee_display_name"] == "Operator One"
    assert result["assignee_active_at_assignment"] is True
    assert result["assignee_currently_active"] is True
    write.assert_called_once()
    # The Cypher + params are passed to tx.run(...) inside the write tx.
    tx = write._tx_holder["tx"]
    run = tx.run
    assert run.call_count == 1
    cypher = run.call_args.args[0]
    sql_text = getattr(cypher, "text", str(cypher))
    assert "assignee_username" in sql_text
    assert "assignee_display_name" in sql_text
    assert "assignee_active_at_assignment" in sql_text
    assert run.call_args.kwargs.get("assignee_username") == "op1"
    assert run.call_args.kwargs.get("assignee_active_at_assignment") is True


def test_get_returns_snapshot_and_recompute():
    repo = TicketFolioRepository()
    _wire(repo, _record(assignee_currently_active=False))

    result = repo.get(1)

    assert result is not None
    assert result["assignee_username"] == "op1"
    assert result["assignee_display_name"] == "Operator One"
    assert result["assignee_active_at_assignment"] is True
    assert result["assignee_currently_active"] is False


def test_get_missing_returns_none():
    repo = TicketFolioRepository()
    _wire(repo, None)

    assert repo.get(999) is None
