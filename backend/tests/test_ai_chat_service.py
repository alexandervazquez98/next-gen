import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from models.user import User


def _operator_user() -> User:
    return User(username="operator", role="OPERATOR", permissions=["CI_VIEW"], allowed_locations=[])


def _diagnostic_user() -> User:
    return User(
        username="diagnostic-operator",
        role="OPERATOR",
        permissions=["CI_VIEW", "RUN_DIAGNOSTICS"],
        allowed_locations=[],
    )


def _ai_cmdb_diagnostic_user() -> User:
    return User(
        username="ai-cmdb-diagnostic-operator",
        role="OPERATOR",
        permissions=["CI_VIEW", "RUN_DIAGNOSTICS", "AI_VIEW_ALL"],
        allowed_locations=[],
    )


class _FakeDb:
    def __init__(self):
        self.added = []
        self.committed = False
        self.refreshed = []

    def add(self, model):
        self.added.append(model)

    def commit(self):
        self.committed = True

    def refresh(self, model):
        model.id = 42
        self.refreshed.append(model)


def _make_client(db=None, user=None):
    from routers.ai import router, get_pg_db, get_current_active_user, get_db

    app = FastAPI()
    app.include_router(router, prefix="/api")
    fake_db = db or _FakeDb()

    def override_pg_db():
        yield fake_db

    app.dependency_overrides[get_pg_db] = override_pg_db
    app.dependency_overrides[get_current_active_user] = lambda: user or _operator_user()
    app.dependency_overrides[get_db] = lambda: MagicMock()
    return TestClient(app), fake_db


def test_ai_chat_requires_authentication():
    from routers.ai import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    client = TestClient(app)

    response = client.post("/api/ai/chat", json={"query": "hello"})

    assert response.status_code == 401


def test_ai_chat_success_uses_server_config_and_persists_history(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")

    client, db = _make_client()

    captured_payloads = []

    def fake_completion(payload, settings):
        captured_payloads.append(payload)
        return {"content": "Use the incident timeline first.", "model": settings.model}

    with patch("services.ai_chat_service._post_lm_studio_chat_completion", side_effect=fake_completion):
        response = client.post(
            "/api/ai/chat",
            json={"query": "What should I check?", "context": "Two Redis alerts"},
        )

    assert response.status_code == 200
    assert response.json()["answer"] == "Use the incident timeline first."
    assert response.json()["model"] == "local-model"
    assert captured_payloads[0]["model"] == "local-model"
    assert "http://lmstudio.local" not in json.dumps(captured_payloads[0])
    assert db.committed is True
    assert db.added[0].username == "operator"
    assert db.added[0].user_message == "What should I check?"
    assert db.added[0].assistant_response == "Use the incident timeline first."


def test_payload_system_prompt_uses_backend_identity_sources(tmp_path, monkeypatch):
    from config import LMStudioSettings
    from services import ai_chat_service

    identity_dir = tmp_path / "identity"
    identity_dir.mkdir()
    (identity_dir / "Soul.md").write_text("# Custom identity\n\nUnique runtime identity.", encoding="utf-8")
    (identity_dir / "scope.md").write_text("# Scope\n\nRead-only diagnostics.", encoding="utf-8")
    (identity_dir / "context-policy.md").write_text("# Context\n\nUse compact context.", encoding="utf-8")
    monkeypatch.setattr(ai_chat_service, "AI_IDENTITY_DIR", identity_dir)

    payload = ai_chat_service.build_lm_studio_payload(
        "What changed?",
        None,
        None,
        LMStudioSettings(enabled=True, model="local-model"),
    )

    system_prompt = payload["messages"][0]["content"]
    assert "Unique runtime identity." in system_prompt
    assert "Read-only diagnostics." in system_prompt
    assert "Use compact context." in system_prompt


def test_payload_places_user_question_before_operational_context():
    from config import LMStudioSettings
    from services import ai_chat_service

    payload = ai_chat_service.build_lm_studio_payload(
        "What changed?",
        "Router-01 alert context",
        None,
        LMStudioSettings(enabled=True, model="local-model"),
    )

    user_content = payload["messages"][1]["content"]
    assert user_content.startswith("User question:\nWhat changed?")
    assert user_content.index("User question:") < user_content.index("Operational context:")


def test_payload_system_prompt_falls_back_when_identity_source_missing(tmp_path, monkeypatch):
    from config import LMStudioSettings
    from services import ai_chat_service

    identity_dir = tmp_path / "identity"
    identity_dir.mkdir()
    (identity_dir / "Soul.md").write_text("# Custom identity\n\nUnique runtime identity.", encoding="utf-8")
    monkeypatch.setattr(ai_chat_service, "AI_IDENTITY_DIR", identity_dir)

    payload = ai_chat_service.build_lm_studio_payload(
        "What changed?",
        None,
        None,
        LMStudioSettings(enabled=True, model="local-model"),
    )

    system_prompt = payload["messages"][0]["content"]
    assert system_prompt == ai_chat_service.FALLBACK_SYSTEM_PROMPT


def test_ai_chat_rejects_request_supplied_url_and_model(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "safe-model")
    client, _ = _make_client()

    response = client.post(
        "/api/ai/chat",
        json={
            "query": "hello",
            "base_url": "http://attacker.example/v1",
            "model": "attacker-model",
        },
    )

    assert response.status_code == 422


def test_ai_chat_maps_lm_studio_timeout(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    client, _ = _make_client()

    from services.ai_chat_service import LMStudioTimeoutError

    with patch("services.ai_chat_service._post_lm_studio_chat_completion", side_effect=LMStudioTimeoutError("timeout")):
        response = client.post("/api/ai/chat", json={"query": "hello"})

    assert response.status_code == 504
    assert response.json()["detail"] == "LM Studio request timed out"


def test_ai_chat_maps_lm_studio_error_without_traceback(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    client, _ = _make_client()

    from services.ai_chat_service import LMStudioError

    with patch("services.ai_chat_service._post_lm_studio_chat_completion", side_effect=LMStudioError("Connection refused: stack")):
        response = client.post("/api/ai/chat", json={"query": "hello"})

    assert response.status_code == 502
    assert response.json()["detail"] == "LM Studio is unavailable"


def test_availability_check_resolves_ci_and_persists_ping_metadata(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    client, db = _make_client(user=_ai_cmdb_diagnostic_user())

    ci = {"id": "ci-1", "name": "Router-01", "ip": "192.168.1.10"}
    from services.ai_chat_service import PingResult

    ping_result = PingResult(
        status="reachable",
        target="192.168.1.10",
        latency_ms=12.3,
        detail="1 packet received",
    )

    with patch("services.ai_chat_service.resolve_ci_for_harness", return_value=ci), \
         patch("services.ai_chat_service.run_bounded_ping", return_value=ping_result), \
         patch("services.ai_chat_service._post_lm_studio_chat_completion", return_value={"content": "Router-01 is reachable.", "model": "local-model"}):
        response = client.post(
            "/api/ai/chat",
            json={
                "query": "Check Router-01 availability",
                "intent": {"type": "availability_check", "ci_ref": "Router-01"},
            },
        )

    assert response.status_code == 200
    assert response.json()["harness_result"]["status"] == "reachable"
    assert db.added[0].harness_result["ci_id"] == "ci-1"
    assert db.added[0].harness_result["target"] == "192.168.1.10"


def test_availability_check_requires_diagnostic_permission(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    client, _ = _make_client()

    with patch("services.ai_chat_service.resolve_ci_for_harness") as resolve_ci, \
         patch("services.ai_chat_service.run_bounded_ping") as run_ping, \
         patch("services.ai_chat_service._post_lm_studio_chat_completion") as complete:
        response = client.post(
            "/api/ai/chat",
            json={
                "query": "Check Router-01 availability",
                "intent": {"type": "availability_check", "ci_ref": "Router-01"},
            },
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "Not authorized to run diagnostics"
    resolve_ci.assert_not_called()
    run_ping.assert_not_called()
    complete.assert_not_called()


def test_availability_check_requires_ai_view_all_before_ci_resolution(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    client, _ = _make_client(user=_diagnostic_user())

    with patch("services.ai_chat_service.resolve_ci_for_harness") as resolve_ci, \
         patch("services.ai_chat_service.run_bounded_ping") as run_ping, \
         patch("services.ai_chat_service._post_lm_studio_chat_completion") as complete:
        response = client.post(
            "/api/ai/chat",
            json={
                "query": "Check Router-01 availability",
                "intent": {"type": "availability_check", "ci_ref": "Router-01"},
            },
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "Not authorized to run diagnostics"
    resolve_ci.assert_not_called()
    run_ping.assert_not_called()
    complete.assert_not_called()


def test_disabled_lm_studio_blocks_harness_side_effects(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "false")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    client, _ = _make_client(user=_diagnostic_user())

    with patch("services.ai_chat_service.resolve_ci_for_harness") as resolve_ci, \
         patch("services.ai_chat_service.run_bounded_ping") as run_ping, \
         patch("services.ai_chat_service._post_lm_studio_chat_completion") as complete:
        response = client.post(
            "/api/ai/chat",
            json={
                "query": "Check Router-01 availability",
                "intent": {"type": "availability_check", "ci_ref": "Router-01"},
            },
        )

    assert response.status_code == 502
    assert response.json()["detail"] == "LM Studio is unavailable"
    resolve_ci.assert_not_called()
    run_ping.assert_not_called()
    complete.assert_not_called()


def test_ping_harness_rejects_invalid_stored_target():
    from services.ai_chat_service import resolve_ping_target

    with pytest.raises(ValueError, match="unsafe"):
        resolve_ping_target({"id": "ci-1", "name": "Router", "ip": "8.8.8.8; rm -rf /"})


def test_bounded_ping_maps_command_timeout():
    from services.ai_chat_service import run_bounded_ping

    with patch("services.ai_chat_service.subprocess.run", side_effect=subprocess.TimeoutExpired(["ping"], 3)):
        result = run_bounded_ping("192.168.1.10")

    assert result.status == "error"
    assert result.target == "192.168.1.10"
    assert result.latency_ms is None
    assert result.detail == "ping command timed out"


def test_bounded_ping_invokes_exact_bounded_subprocess_command():
    from services.ai_chat_service import run_bounded_ping

    completed = subprocess.CompletedProcess(
        ["ping", "-c", "1", "-W", "2", "router-01.example"],
        0,
        stdout="64 bytes from router-01.example: icmp_seq=1 ttl=64 time=7.42 ms\n",
        stderr="",
    )

    with patch("services.ai_chat_service.subprocess.run", return_value=completed) as run:
        result = run_bounded_ping("router-01.example")

    run.assert_called_once_with(
        ["ping", "-c", "1", "-W", "2", "router-01.example"],
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
    )
    assert result.status == "reachable"
    assert result.target == "router-01.example"
    assert result.latency_ms == 7.42
    assert result.detail == "1 packet received"


def test_bounded_ping_parses_success_without_latency():
    from services.ai_chat_service import run_bounded_ping

    completed = subprocess.CompletedProcess(
        ["ping", "-c", "1", "-W", "2", "192.168.1.10"],
        0,
        stdout="1 packets transmitted, 1 received, 0% packet loss\n",
        stderr="",
    )

    with patch("services.ai_chat_service.subprocess.run", return_value=completed):
        result = run_bounded_ping("192.168.1.10")

    assert result.status == "reachable"
    assert result.latency_ms is None
    assert result.detail == "1 packet received"


def test_bounded_ping_maps_missing_command():
    from services.ai_chat_service import run_bounded_ping

    with patch("services.ai_chat_service.subprocess.run", side_effect=FileNotFoundError()):
        result = run_bounded_ping("192.168.1.10")

    assert result.status == "error"
    assert result.target == "192.168.1.10"
    assert result.latency_ms is None
    assert result.detail == "ping command not found"


def test_bounded_ping_maps_execution_failure_without_exception_details():
    from services.ai_chat_service import run_bounded_ping

    with patch("services.ai_chat_service.subprocess.run", side_effect=PermissionError("secret path")):
        result = run_bounded_ping("192.168.1.10")

    assert result.status == "error"
    assert result.target == "192.168.1.10"
    assert result.latency_ms is None
    assert result.detail == "ping command failed"
    assert "secret path" not in result.detail


def test_bounded_ping_maps_subprocess_failure_without_exception_details():
    from services.ai_chat_service import run_bounded_ping

    with patch("services.ai_chat_service.subprocess.run", side_effect=subprocess.SubprocessError("secret detail")):
        result = run_bounded_ping("192.168.1.10")

    assert result.status == "error"
    assert result.target == "192.168.1.10"
    assert result.latency_ms is None
    assert result.detail == "ping command failed"
    assert "secret detail" not in result.detail
