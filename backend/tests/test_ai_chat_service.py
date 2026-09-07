import inspect
import io
import json
import logging
import socket
import subprocess
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from models.ai_guard_models import GuardResult
from models.user import User
from routers.ai import chat_with_ai, get_current_active_user, get_db, get_pg_db, router


def _operator_user() -> User:
    return User(username="operator", role="OPERATOR", permissions=["CI_VIEW"], allowed_locations=[])


def _diagnostic_user() -> User:
    return User(
        username="diagnostic-operator",
        role="OPERATOR",
        permissions=["CI_VIEW", "RUN_DIAGNOSTICS"],
        allowed_locations=[],
    )


def _event_view_user() -> User:
    return User(
        username="event-viewer",
        role="OPERATOR",
        permissions=["CI_VIEW", "EVENT_VIEW"],
        allowed_locations=[],
    )


def _scoped_event_view_user() -> User:
    return User(
        username="scoped-event-viewer",
        role="OPERATOR",
        permissions=["CI_VIEW", "EVENT_VIEW"],
        allowed_locations=["Site A"],
        allowed_ci_types=["Switch"],
    )


def _admin_user() -> User:
    return User(
        username="admin-operator",
        role="ADMIN",
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


class _FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def all(self):
        return self.rows


class _FakeHistoryDb(_FakeDb):
    def __init__(self, rows):
        super().__init__()
        self.rows = rows

    def query(self, *_args, **_kwargs):
        return _FakeQuery(self.rows)


@pytest.fixture(autouse=True)
def _default_ai_chat_guard(monkeypatch):
    monkeypatch.setattr(
        "routers.ai.check_all_guards", lambda *args, **kwargs: GuardResult(allowed=True)
    )
    monkeypatch.setattr("routers.ai.record_operation", lambda *args, **kwargs: None)


def _make_client(db=None, user=None):
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

    with patch(
        "services.ai_chat_service._post_lm_studio_chat_completion", side_effect=fake_completion
    ):
        response = client.post(
            "/api/ai/chat",
            json={"query": "What should I check?", "context": "Two Redis alerts"},
        )

    assert response.status_code == 200
    assert response.json()["answer"] == "Use the incident timeline first."
    assert response.json()["model"] == "local-model"
    assert captured_payloads[0]["model"] == "local-model"
    assert captured_payloads[0]["max_tokens"] == 800
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
    (identity_dir / "Soul.md").write_text(
        "# Custom identity\n\nUnique runtime identity.", encoding="utf-8"
    )
    (identity_dir / "scope.md").write_text("# Scope\n\nRead-only diagnostics.", encoding="utf-8")
    (identity_dir / "context-policy.md").write_text(
        "# Context\n\nUse compact context.", encoding="utf-8"
    )
    # User override folder is the parent of identity/; resolver reads identity/<file>.
    monkeypatch.setattr(ai_chat_service, "AI_USER_DIR", tmp_path)

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


def test_payload_system_prompt_loads_optional_tool_catalog(tmp_path, monkeypatch):
    from config import LMStudioSettings
    from services import ai_chat_service

    identity_dir = tmp_path / "identity"
    tools_dir = tmp_path / "tools"
    identity_dir.mkdir()
    tools_dir.mkdir()
    (identity_dir / "Soul.md").write_text(
        "# Custom identity\n\nUnique runtime identity.", encoding="utf-8"
    )
    (identity_dir / "scope.md").write_text("# Scope\n\nRead-only diagnostics.", encoding="utf-8")
    (identity_dir / "context-policy.md").write_text(
        "# Context\n\nUse compact context.", encoding="utf-8"
    )
    (tools_dir / "README.md").write_text(
        "# AI tool system\n\nBackend-owned tool catalog.", encoding="utf-8"
    )
    (tools_dir / "event-list.md").write_text(
        "# Event list\n\nProvider-neutral event listing.", encoding="utf-8"
    )
    (tools_dir / "network-basic.md").write_text(
        "# Network basic tools\n\n`availability_check` and planned traceroute.", encoding="utf-8"
    )
    monkeypatch.setattr(ai_chat_service, "AI_USER_DIR", tmp_path)

    payload = ai_chat_service.build_lm_studio_payload(
        "What tools are available?",
        None,
        None,
        LMStudioSettings(enabled=True, model="local-model"),
    )

    system_prompt = payload["messages"][0]["content"]
    assert "Unique runtime identity." in system_prompt
    assert "Backend-owned tool catalog." in system_prompt
    assert "Provider-neutral event listing." in system_prompt
    assert "planned traceroute" in system_prompt


def test_payload_replays_bounded_history_before_current_question():
    from config import LMStudioSettings
    from services import ai_chat_service

    payload = ai_chat_service.build_lm_studio_payload(
        "What now?",
        None,
        None,
        LMStudioSettings(enabled=True, model="local-model"),
        history=[
            {"role": "user", "content": "List active events"},
            {"role": "assistant", "content": "Two events are active."},
        ],
    )

    assert [message["role"] for message in payload["messages"]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert payload["messages"][1]["content"] == "List active events"
    assert payload["messages"][-1]["content"].startswith("User question:\nWhat now?")


# ---------------------------------------------------------------------------
# Context-window compaction (issue #415)
# ---------------------------------------------------------------------------


def _long_content(marker: str, length: int = 800) -> str:
    """Return a long, marker-bearing string used to assert drop order."""
    body = "x" * (length - len(marker))
    return f"{marker}{body}"


def test_compactor_trims_oldest_non_system_messages_when_over_threshold():
    from config import LMStudioSettings
    from services import ai_chat_service

    # context_limit_tokens=200, threshold=0.5 -> budget=100 tokens (~400 chars).
    # Each history message is 800 chars (~200 tokens). Four history turns
    # already exceed the budget by ~4x, forcing eviction.
    settings = LMStudioSettings(
        enabled=True,
        model="local-model",
        context_limit_tokens=200,
        compaction_threshold=0.5,
    )
    history = [
        {"role": "user", "content": _long_content("turn-1-")},
        {"role": "assistant", "content": _long_content("turn-2-")},
        {"role": "user", "content": _long_content("turn-3-")},
        {"role": "assistant", "content": _long_content("turn-4-")},
    ]
    messages = (
        [{"role": "system", "content": "SYSTEM_PROMPT_MARKER"}]
        + history
        + [{"role": "user", "content": "current question"}]
    )

    compacted = ai_chat_service._compact_history(list(messages), settings)

    # System message preserved byte-identical and at index 0.
    assert compacted[0] == {"role": "system", "content": "SYSTEM_PROMPT_MARKER"}

    # The current question must remain (most-recent user turn is kept).
    roles = [m["role"] for m in compacted]
    assert roles[-1] == "user"
    assert compacted[-1]["content"] == "current question"

    # At least one of the oldest history turns must have been dropped.
    dropped_markers = {"turn-1-", "turn-2-", "turn-3-", "turn-4-"}
    surviving_markers = {m["content"][:7] for m in compacted[1:-1]}
    assert dropped_markers - surviving_markers, "expected at least one history marker to be evicted"

    # Total estimated non-system tokens must fit the budget.
    budget = int(settings.context_limit_tokens * settings.compaction_threshold)
    total = sum(ai_chat_service._estimate_tokens(m["content"]) for m in compacted[1:])
    assert total <= budget, f"total={total} budget={budget}"


def test_compactor_is_noop_when_under_threshold():
    from config import LMStudioSettings
    from services import ai_chat_service

    # Default settings: 32768 tokens * 0.8 budget. Two short history turns
    # (~tens of chars) are far below the budget.
    settings = LMStudioSettings(enabled=True, model="local-model")
    messages = [
        {"role": "system", "content": "SYSTEM"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "world"},
        {"role": "user", "content": "current?"},
    ]

    compacted = ai_chat_service._compact_history(list(messages), settings)

    # Content-equal: the compactor must not mutate or drop messages here.
    assert compacted == messages


def test_compactor_threshold_one_is_kill_switch():
    from config import LMStudioSettings
    from services import ai_chat_service

    # Even with a tiny absolute limit, threshold=1.0 must disable compaction.
    settings = LMStudioSettings(
        enabled=True,
        model="local-model",
        context_limit_tokens=10,  # absurdly small
        compaction_threshold=1.0,
    )
    messages = [
        {"role": "system", "content": "SYSTEM"},
        {"role": "user", "content": _long_content("turn-1-", 400)},
        {"role": "assistant", "content": _long_content("turn-2-", 400)},
        {"role": "user", "content": _long_content("turn-3-", 400)},
    ]

    compacted = ai_chat_service._compact_history(list(messages), settings)

    # Kill switch: the entire input list is returned unchanged.
    assert compacted == messages


def test_compactor_reserves_system_message_byte_identical():
    from config import LMStudioSettings
    from services import ai_chat_service

    system_payload = {
        "role": "system",
        "content": "SENTINEL_SYSTEM_PROMPT_v1\nwith-newlines\nand-binary\x00bytes",
    }
    settings = LMStudioSettings(
        enabled=True,
        model="local-model",
        context_limit_tokens=40,
        compaction_threshold=0.5,
    )
    messages = [
        system_payload,
        {"role": "user", "content": "x" * 400},
        {"role": "assistant", "content": "y" * 400},
        {"role": "user", "content": "z" * 400},
        {"role": "assistant", "content": "w" * 400},
        {"role": "user", "content": "current question"},
    ]

    compacted = ai_chat_service._compact_history(list(messages), settings)

    # Byte-identical: same dict object content, not just equal by string.
    assert compacted[0] == system_payload
    assert compacted[0]["content"] == system_payload["content"]
    assert len(compacted[0]["content"]) == len(system_payload["content"])


def test_ai_chat_router_compacts_history_when_env_limit_low(monkeypatch):
    """End-to-end: a low LM_STUDIO_CONTEXT_LIMIT_TOKENS trims the captured
    payload's history before it reaches the upstream LM Studio call."""
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    # 512 tokens * 0.5 threshold = 256 tokens (~1024 chars). The seed row
    # contributes ~2000 + ~2000 chars (~1000 tokens), forcing eviction.
    monkeypatch.setenv("LM_STUDIO_CONTEXT_LIMIT_TOKENS", "512")
    monkeypatch.setenv("LM_STUDIO_COMPACTION_THRESHOLD", "0.5")

    previous_row = type(
        "Row",
        (),
        {
            "username": "operator",
            "user_message": "u" * 2000,
            "assistant_response": "a" * 2000,
            "harness_result": None,
        },
    )()
    client, _db = _make_client(db=_FakeHistoryDb([previous_row]))

    captured_payloads = []

    def fake_completion(payload, settings):
        captured_payloads.append(payload)
        return {"content": "ok", "model": settings.model}

    with patch(
        "services.ai_chat_service._post_lm_studio_chat_completion",
        side_effect=fake_completion,
    ):
        response = client.post(
            "/api/ai/chat",
            json={"query": "follow-up question"},
        )

    assert response.status_code == 200
    assert captured_payloads, "expected the LM Studio call to be captured"

    messages = captured_payloads[0]["messages"]
    # Sanity: the system + current-question turn must survive.
    assert messages[0]["role"] == "system"
    assert messages[-1]["role"] == "user"
    assert "follow-up question" in messages[-1]["content"]

    # Without compaction, the captured messages would be:
    #   [system, user-history("u"*2000), assistant-history("a"*2000), current-user]
    # i.e. 4 entries. Compaction must reduce that count.
    assert len(messages) < 4, (
        f"expected compaction to drop history entries; "
        f"got {len(messages)} messages (system+history+current)"
    )

    # The OLDEST history entry (the user turn) must be evicted first —
    # sliding-window preserves the most recent conversational context.
    surviving_contents = "".join(m["content"] for m in messages[1:-1])
    assert (
        "u" * 2000 not in surviving_contents
    ), "oldest user turn should be evicted before newer assistant turn"


def test_complete_chat_falls_back_when_model_returns_empty_event_list(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    from services import ai_chat_service

    harness_result = {
        "type": "event_list",
        "status": "OPEN",
        "severity": None,
        "count": 2,
        "truncated": False,
        "events": [
            {
                "ci_name": "Router A",
                "severity": "CRITICAL",
                "status": "OPEN",
                "message": "Service down",
            },
            {
                "ci_name": "Switch B",
                "severity": "INFO",
                "status": "OPEN",
                "message": "Ping warning",
            },
        ],
    }

    with patch(
        "services.ai_chat_service._post_lm_studio_chat_completion",
        return_value={"content": "", "model": "local-model"},
    ):
        response = ai_chat_service.complete_chat(
            "dime que eventos hay abiertos en estos momentos?",
            None,
            harness_result,
            [],
        )

    assert response["model"] == "deterministic-template"
    assert "Hay 2 eventos" in response["content"]
    assert "Router A" in response["content"]
    assert "Switch B" in response["content"]


def test_complete_chat_preserves_non_empty_model_response(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    from services import ai_chat_service

    with patch(
        "services.ai_chat_service._post_lm_studio_chat_completion",
        return_value={"content": "Model answer", "model": "local-model"},
    ):
        response = ai_chat_service.complete_chat("hello", None, None, [])

    assert response["content"] == "Model answer"


def test_ai_policy_and_template_markdown_contracts_exist():
    root = Path(__file__).resolve().parents[1]
    required_fragments = {
        "ai/policies/response-boundaries.md": [
            "harness result exists",
            "reachable means",
            "unreachable means",
            "root cause",
            "Raven",
            "Postgres",
        ],
        "ai/policies/lmstudio-runtime.md": [
            "/v1/chat/completions",
            "backend-owned history",
            "reasoning_content",
            "LM_STUDIO_MAX_TOKENS",
            "LM_STUDIO_TIMEOUT_SECONDS",
        ],
        "ai/policies/followup-intents.md": [
            "event-list triggers",
            "availability follow-up triggers",
            "named-area",
            "availability_check_batch",
            "5 CIs",
        ],
        "ai/templates/event_list.md": [
            "Eventos observados",
            "Diagnóstico observado",
            "Límites",
            "Siguiente chequeo sugerido",
            "truncated",
        ],
        "ai/templates/availability_check.md": [
            "CI",
            "target",
            "latency",
            "bounded ping",
            "does not confirm",
        ],
        "ai/templates/availability_check_batch.md": [
            "count",
            "per-CI",
            "bounded ping",
            "5 CIs",
            "does not confirm",
        ],
    }

    for relative_path, fragments in required_fragments.items():
        text = (root / relative_path).read_text(encoding="utf-8")
        lowered = text.lower()
        for fragment in fragments:
            assert fragment.lower() in lowered, relative_path


def test_ai_markdown_loader_is_bounded_and_safe(tmp_path, monkeypatch):
    from services import ai_chat_service

    base = tmp_path / "ai"
    (base / "templates").mkdir(parents=True)
    (base / "templates" / "event_list.md").write_text("x" * 25, encoding="utf-8")
    monkeypatch.setattr(ai_chat_service, "AI_USER_DIR", base)
    monkeypatch.setattr(ai_chat_service, "MAX_AI_MARKDOWN_CHARS", 10)

    assert ai_chat_service.load_ai_markdown_contract("templates", "event_list.md") == "x" * 10
    assert ai_chat_service.load_ai_markdown_contract("templates", "missing.md") == ""
    assert ai_chat_service.load_ai_markdown_contract("../identity", "Soul.md") == ""


def test_user_override_wins_over_bundled(tmp_path, monkeypatch):
    from services import ai_chat_service

    user_dir = tmp_path / "user"
    (user_dir / "templates").mkdir(parents=True)
    (user_dir / "templates" / "event_list.md").write_text("USER-OVERRIDE-MARKER", encoding="utf-8")
    monkeypatch.setattr(ai_chat_service, "AI_USER_DIR", user_dir)

    assert (
        ai_chat_service.load_ai_markdown_contract("templates", "event_list.md")
        == "USER-OVERRIDE-MARKER"
    )


def test_bundled_fallback_when_user_file_missing(tmp_path, monkeypatch):
    from services import ai_chat_service

    # User override folder exists but has no templates/event_list.md -> loader
    # must fall back to the bundled default (real backend/ai tree).
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    monkeypatch.setattr(ai_chat_service, "AI_USER_DIR", user_dir)

    bundled = (ai_chat_service.AI_DIR / "templates" / "event_list.md").read_text(encoding="utf-8")
    assert ai_chat_service.load_ai_markdown_contract("templates", "event_list.md") == bundled


def test_bundled_fallback_when_user_path_is_directory(tmp_path, monkeypatch):
    from services import ai_chat_service

    user_dir = tmp_path / "user"
    (user_dir / "templates" / "event_list.md").mkdir(parents=True)
    monkeypatch.setattr(ai_chat_service, "AI_USER_DIR", user_dir)

    bundled = (ai_chat_service.AI_DIR / "templates" / "event_list.md").read_text(encoding="utf-8")
    assert ai_chat_service.load_ai_markdown_contract("templates", "event_list.md") == bundled


def test_system_prompt_user_override_wins(tmp_path, monkeypatch):
    from config import LMStudioSettings
    from services import ai_chat_service

    user_dir = tmp_path / "user"
    (user_dir / "identity").mkdir(parents=True)
    (user_dir / "identity" / "Soul.md").write_text("CUSTOM-SOUL-MARKER", encoding="utf-8")
    (user_dir / "identity" / "scope.md").write_text("Read-only diagnostics.", encoding="utf-8")
    (user_dir / "identity" / "context-policy.md").write_text(
        "Use compact context.", encoding="utf-8"
    )
    monkeypatch.setattr(ai_chat_service, "AI_USER_DIR", user_dir)

    payload = ai_chat_service.build_lm_studio_payload(
        "What changed?",
        None,
        None,
        LMStudioSettings(enabled=True, model="local-model"),
    )

    system_prompt = payload["messages"][0]["content"]
    assert "CUSTOM-SOUL-MARKER" in system_prompt


def test_system_prompt_bundled_fallback_when_user_dir_empty(tmp_path, monkeypatch):
    from config import LMStudioSettings
    from services import ai_chat_service

    # Empty user override folder -> every file falls back to bundled defaults.
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    monkeypatch.setattr(ai_chat_service, "AI_USER_DIR", user_dir)

    payload = ai_chat_service.build_lm_studio_payload(
        "What changed?",
        None,
        None,
        LMStudioSettings(enabled=True, model="local-model"),
    )

    system_prompt = payload["messages"][0]["content"]
    assert system_prompt != ai_chat_service.FALLBACK_SYSTEM_PROMPT
    assert "concise technical assistant for CMDB" in system_prompt


def test_seed_copies_bundled_tree_into_empty_dir(tmp_path, monkeypatch):
    from services import ai_chat_service

    target = tmp_path / "prompts"

    class _Settings:
        prompts_dir = str(target)

    monkeypatch.setattr(ai_chat_service, "get_ai_prompts_settings", lambda: _Settings())
    ai_chat_service.ensure_ai_prompts_seeded()

    assert (target / "identity" / "Soul.md").exists()
    assert (target / "identity" / "scope.md").exists()
    assert (target / "templates" / "event_list.md").exists()
    assert (target / "tools" / "README.md").exists()


def test_seed_ignores_empty_dirs_and_dotfiles(tmp_path, monkeypatch):
    from services import ai_chat_service

    target = tmp_path / "prompts"
    (target / "identity").mkdir(parents=True)
    (target / ".keep").write_text("", encoding="utf-8")

    class _Settings:
        prompts_dir = str(target)

    monkeypatch.setattr(ai_chat_service, "get_ai_prompts_settings", lambda: _Settings())
    ai_chat_service.ensure_ai_prompts_seeded()

    assert (target / "identity" / "Soul.md").exists()
    assert (target / "templates" / "event_list.md").exists()


def test_seed_never_overwrites_existing_files(tmp_path, monkeypatch):
    from services import ai_chat_service

    target = tmp_path / "prompts"
    (target / "identity").mkdir(parents=True)
    sentinel = "FROZEN-SENTINEL-DO-NOT-TOUCH"
    (target / "identity" / "Soul.md").write_text(sentinel, encoding="utf-8")

    class _Settings:
        prompts_dir = str(target)

    monkeypatch.setattr(ai_chat_service, "get_ai_prompts_settings", lambda: _Settings())
    ai_chat_service.ensure_ai_prompts_seeded()

    # Frozen snapshot: pre-existing user file is never clobbered.
    assert (target / "identity" / "Soul.md").read_text(encoding="utf-8") == sentinel


def test_seed_noop_when_prompts_dir_unset(tmp_path, monkeypatch):
    from services import ai_chat_service

    target = tmp_path / "prompts"
    target.mkdir()

    class _Settings:
        prompts_dir = ""

    monkeypatch.setattr(ai_chat_service, "get_ai_prompts_settings", lambda: _Settings())
    ai_chat_service.ensure_ai_prompts_seeded()

    # Feature off -> nothing written.
    assert not any(target.iterdir())


def test_render_event_list_response_uses_facts_and_safe_observed_diagnosis():
    from services.ai_chat_service import render_harness_response

    harness_result = {
        "type": "event_list",
        "status": "OPEN",
        "severity": "WARNING",
        "count": 2,
        "truncated": True,
        "events": [
            {
                "ci_name": "CUMBRES_PTP_DIR_PLAYAS_DE_TIJUANA",
                "severity": "WARNING",
                "status": "OPEN",
                "metric_name": "ICMP Latency",
                "message": "Warning Threshold Breached: 128.0 >= 100.0",
                "last_seen": "2026-06-19T21:41:02Z",
            },
            {
                "ci_name": "SWITCH C2",
                "severity": "INFO",
                "status": "OPEN",
                "message": "Service/Host Down: PING-CHECK-CISCO",
                "last_seen": "2026-06-19T21:40:25Z",
            },
        ],
    }

    response = render_harness_response(
        "que eventos tenemos abiertos y cual es el diagnostico?", harness_result
    )

    assert response is not None
    assert "Hay 2 eventos" in response
    assert "status=OPEN" in response
    assert "severity=WARNING" in response
    assert "CUMBRES_PTP_DIR_PLAYAS_DE_TIJUANA" in response
    assert "SWITCH C2" in response
    assert "Warning Threshold Breached: 128.0 >= 100.0" in response
    assert "2026-06-19T21:41:02Z" in response
    assert "latencia" in response.lower()
    assert "disponibilidad" in response.lower()
    assert "Resultado truncado" in response
    assert "No confirma causa raíz" in response
    for unsafe in (
        "congestión severa",
        "falla eléctrica",
        "firewall bloqueando",
        "estado óptimo",
        "resuelto",
    ):
        assert unsafe not in response.lower()


def test_render_empty_event_list_response_has_filters_and_no_invented_facts():
    from services.ai_chat_service import render_harness_response

    response = render_harness_response(
        "list open critical events",
        {"type": "event_list", "status": "OPEN", "severity": "CRITICAL", "count": 0, "events": []},
    )

    assert response is not None
    assert "There are no events" in response
    assert "status=OPEN" in response
    assert "severity=CRITICAL" in response
    assert "root cause is" not in response.lower()
    assert "resolved" not in response.lower()


def test_render_availability_check_response_uses_bounded_ping_semantics():
    from services.ai_chat_service import render_harness_response

    response = render_harness_response(
        "check Router-01 availability",
        {
            "type": "availability_check",
            "ci_name": "Router-01",
            "target": "192.168.1.10",
            "status": "reachable",
            "latency_ms": 7.42,
            "detail": "1 packet received",
        },
    )

    assert response is not None
    assert "Router-01" in response
    assert "reachable" in response
    assert "192.168.1.10" in response
    assert "7.42 ms" in response
    assert "current bounded ping" in response
    assert "does not confirm complete service health" in response
    assert "service is healthy" not in response.lower()


def test_render_availability_check_failure_does_not_claim_reachability():
    from services.ai_chat_service import render_harness_response

    response = render_harness_response(
        "verifica Router-01",
        {"type": "availability_check", "ci_ref": "Router-01", "status": "ci_not_found"},
    )

    assert response is not None
    assert "Router-01" in response
    assert "ci_not_found" in response
    assert "respondió" not in response.lower()
    assert "reachable," not in response.lower()


def test_render_availability_batch_response_lists_results_and_cap():
    from services.ai_chat_service import render_harness_response

    response = render_harness_response(
        "dame el estatus actual de islas agrarias",
        {
            "type": "availability_check_batch",
            "count": 2,
            "results": [
                {
                    "ci_name": "AP01-ISLAS_AGRARIAS-BAJA01",
                    "status": "reachable",
                    "target": "10.53.13.34",
                    "latency_ms": 4.29,
                    "detail": "1 packet received",
                },
                {
                    "ci_name": "AP02-ISLAS_AGRARIAS-BAJA01",
                    "status": "unreachable",
                    "target": "10.53.13.35",
                    "latency_ms": None,
                    "detail": "no response to one bounded ping",
                },
            ],
        },
    )

    assert response is not None
    assert "Chequeo de disponibilidad ejecutado sobre 2 CIs" in response
    assert "AP01-ISLAS_AGRARIAS-BAJA01" in response
    assert "AP02-ISLAS_AGRARIAS-BAJA01" in response
    assert "4.29 ms" in response
    assert "ping acotado" in response.lower()
    assert "máximo 5 CIs" in response
    assert "salud completa" in response
    assert "estables" not in response.lower()


def test_complete_chat_bypasses_lm_studio_for_operational_harnesses(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    from services import ai_chat_service

    with patch("services.ai_chat_service._post_lm_studio_chat_completion") as post:
        response = ai_chat_service.complete_chat(
            "list open events",
            None,
            {"type": "event_list", "status": "OPEN", "count": 0, "events": []},
            [],
        )

    post.assert_not_called()
    assert response["model"] == "deterministic-template"
    assert "There are no events" in response["content"]


def test_complete_chat_preserves_model_response_for_unknown_harness(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    from services import ai_chat_service

    with patch(
        "services.ai_chat_service._post_lm_studio_chat_completion",
        return_value={"content": "Model answer", "model": "local-model"},
    ) as post:
        response = ai_chat_service.complete_chat("hello", None, {"type": "future_harness"}, [])

    post.assert_called_once()
    assert response["content"] == "Model answer"


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

    # Point BOTH the user override and the bundled root at dirs that lack the
    # required scope.md / context-policy.md, so the resolver cannot find them
    # anywhere and the system prompt degrades to FALLBACK_SYSTEM_PROMPT.
    user_dir = tmp_path / "user"
    bundled_dir = tmp_path / "bundled"
    (user_dir / "identity").mkdir(parents=True)
    (bundled_dir / "identity").mkdir(parents=True)
    (user_dir / "identity" / "Soul.md").write_text(
        "# Custom identity\n\nUnique runtime identity.", encoding="utf-8"
    )
    (bundled_dir / "identity" / "Soul.md").write_text(
        "# Custom identity\n\nUnique runtime identity.", encoding="utf-8"
    )
    monkeypatch.setattr(ai_chat_service, "AI_USER_DIR", user_dir)
    monkeypatch.setattr(ai_chat_service, "AI_DIR", bundled_dir)

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

    with patch(
        "services.ai_chat_service._post_lm_studio_chat_completion",
        side_effect=LMStudioTimeoutError("timeout"),
    ):
        response = client.post("/api/ai/chat", json={"query": "hello"})

    assert response.status_code == 504
    assert response.json()["detail"] == "LM Studio request timed out"


def test_ai_chat_maps_lm_studio_error_without_traceback(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    client, _ = _make_client()

    from services.ai_chat_service import LMStudioError

    with patch(
        "services.ai_chat_service._post_lm_studio_chat_completion",
        side_effect=LMStudioError("Connection refused: stack"),
    ):
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

    with (
        patch("services.ai_chat_service.resolve_ci_for_harness", return_value=ci),
        patch("services.ai_chat_service.run_bounded_ping", return_value=ping_result),
        patch(
            "services.ai_chat_service._post_lm_studio_chat_completion",
            return_value={"content": "Router-01 is reachable.", "model": "local-model"},
        ),
    ):
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


def test_availability_batch_rejects_oversized_ci_ref(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    client, _ = _make_client(user=_ai_cmdb_diagnostic_user())

    response = client.post(
        "/api/ai/chat",
        json={
            "query": "check availability",
            "intent": {"type": "availability_check_batch", "ci_refs": ["x" * 121]},
        },
    )

    assert response.status_code == 422


def test_event_list_query_applies_user_scope():
    from services import ai_chat_service

    class Session:
        def __init__(self):
            self.params = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def run(self, _query, **params):
            self.params = params
            return []

    session = Session()
    driver = type("Driver", (), {"session": lambda _self: session})()

    assert (
        ai_chat_service.list_events_for_harness(
            driver,
            "OPEN",
            10,
            None,
            user=_scoped_event_view_user(),
        )
        == []
    )

    assert session.params["is_unscoped"] is False
    assert session.params["allowed_locations"] == ["Site A"]
    assert session.params["allowed_ci_types"] == ["Switch"]


def test_event_list_query_returns_no_rows_without_scope():
    from services import ai_chat_service

    driver = type(
        "Driver",
        (),
        {"session": lambda _self: (_ for _ in ()).throw(AssertionError("should not query"))},
    )()

    assert (
        ai_chat_service.list_events_for_harness(
            driver,
            "OPEN",
            10,
            user=_event_view_user(),
        )
        == []
    )


def test_ai_chat_route_uses_async_offload_for_blocking_work():
    assert inspect.iscoroutinefunction(chat_with_ai)


def test_event_list_harness_persists_bounded_event_metadata(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    client, db = _make_client(user=_event_view_user())

    events = [
        {
            "id": "evt-1",
            "ci_id": "ci-1",
            "ci_name": "Redis Cache",
            "ci_hostname": "redis-01",
            "metric_id": "latency",
            "metric_name": "Latency",
            "status": "OPEN",
            "severity": "CRITICAL",
            "message": "Redis latency above threshold",
            "created_at": "2026-06-19T18:00:00Z",
            "secret_field": "must-not-leak",
        },
        {
            "id": "evt-2",
            "ci_id": "ci-2",
            "ci_name": "Router-01",
            "status": "ACK",
            "severity": "WARNING",
            "message": "Packet loss detected",
        },
    ]

    captured_payloads = []

    def fake_completion(payload, settings):
        captured_payloads.append(payload)
        return {"content": "There are 2 active events.", "model": settings.model}

    with (
        patch(
            "services.ai_chat_service.list_events_for_harness", return_value=events
        ) as list_events,
        patch(
            "services.ai_chat_service._post_lm_studio_chat_completion", side_effect=fake_completion
        ),
    ):
        response = client.post(
            "/api/ai/chat",
            json={
                "query": "List active events",
                "intent": {"type": "event_list", "status": "ACTIVE", "limit": 1},
            },
        )

    assert response.status_code == 200
    list_events.assert_called_once()
    assert list_events.call_args.args[1:] == ("ACTIVE", 1, None)
    harness_result = response.json()["harness_result"]
    assert harness_result["type"] == "event_list"
    assert harness_result["count"] == 1
    assert harness_result["truncated"] is True
    assert harness_result["events"][0]["id"] == "evt-1"
    assert "secret_field" not in harness_result["events"][0]
    assert db.added[0].harness_result == harness_result
    assert captured_payloads == []
    assert response.json()["model"] == "deterministic-template"


def test_event_list_harness_infers_open_critical_filters(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    client, _ = _make_client(user=_event_view_user())

    with (
        patch("services.ai_chat_service.list_events_for_harness", return_value=[]) as list_events,
        patch(
            "services.ai_chat_service._post_lm_studio_chat_completion",
            return_value={"content": "No critical open events.", "model": "local-model"},
        ),
    ):
        response = client.post(
            "/api/ai/chat",
            json={"query": "lista todos los eventos abiertos criticos"},
        )

    assert response.status_code == 200
    list_events.assert_called_once()
    assert list_events.call_args.args[1:] == ("OPEN", 10, "CRITICAL")
    assert response.json()["harness_result"]["severity"] == "CRITICAL"


def test_event_list_harness_accepts_active_events_alias(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    client, _ = _make_client(user=_ai_cmdb_diagnostic_user())

    with (
        patch("services.ai_chat_service.list_events_for_harness", return_value=[]),
        patch(
            "services.ai_chat_service._post_lm_studio_chat_completion",
            return_value={"content": "No active events.", "model": "local-model"},
        ),
    ):
        response = client.post(
            "/api/ai/chat",
            json={
                "query": "List active events",
                "intent": {"type": "active_events", "status": "ACTIVE"},
            },
        )

    assert response.status_code == 200
    assert response.json()["harness_result"]["type"] == "event_list"


def test_event_list_harness_infers_unrecovered_events_from_query(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    client, _ = _make_client(user=_event_view_user())

    with (
        patch("services.ai_chat_service.list_events_for_harness", return_value=[]) as list_events,
        patch(
            "services.ai_chat_service._post_lm_studio_chat_completion",
            return_value={"content": "No unrecovered events.", "model": "local-model"},
        ),
    ):
        response = client.post(
            "/api/ai/chat",
            json={"query": "que eventos no se han recuperado?"},
        )

    assert response.status_code == 200
    list_events.assert_called_once()
    assert list_events.call_args.args[1:] == ("ACTIVE", 10, None)
    assert response.json()["harness_result"]["type"] == "event_list"


def test_followup_availability_batch_uses_latest_event_list_context(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    previous_row = type(
        "Row",
        (),
        {
            "username": "ai-cmdb-diagnostic-operator",
            "user_message": "lista eventos activos",
            "assistant_response": "SWITCH A and SWITCH B are active.",
            "harness_result": {
                "type": "event_list",
                "events": [
                    {"ci_name": "SWITCH A", "ci_id": "ci-a"},
                    {"ci_name": "SWITCH B", "ci_id": "ci-b"},
                ],
            },
        },
    )()
    client, db = _make_client(db=_FakeHistoryDb([previous_row]), user=_ai_cmdb_diagnostic_user())

    from services.ai_chat_service import PingResult

    def resolve_ci(_driver, ci_ref):
        return {"id": ci_ref.lower().replace(" ", "-"), "name": ci_ref, "ip": "192.168.1.10"}

    with (
        patch("services.ai_chat_service.resolve_ci_for_harness", side_effect=resolve_ci),
        patch(
            "services.ai_chat_service.run_bounded_ping",
            return_value=PingResult("reachable", "192.168.1.10", 1.2, "1 packet received"),
        ),
        patch(
            "services.ai_chat_service._post_lm_studio_chat_completion",
            return_value={"content": "Both switches are reachable.", "model": "local-model"},
        ),
    ):
        response = client.post(
            "/api/ai/chat",
            json={"query": "verifica si están funcionando"},
        )

    assert response.status_code == 200
    harness_result = response.json()["harness_result"]
    assert harness_result["type"] == "availability_check_batch"
    assert harness_result["count"] == 2
    assert [item["ci_name"] for item in harness_result["results"]] == ["SWITCH A", "SWITCH B"]
    assert db.added[0].harness_result["type"] == "availability_check_batch"


def test_followup_status_filters_latest_event_list_by_named_area(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    previous_row = type(
        "Row",
        (),
        {
            "username": "ai-cmdb-diagnostic-operator",
            "user_message": "eventos abiertos",
            "assistant_response": "Open events listed.",
            "harness_result": {
                "type": "event_list",
                "events": [
                    {"ci_name": "AP01-ISLAS_AGRARIAS-BAJA01", "ci_id": "ci-ap01"},
                    {"ci_name": "AP02-ISLAS_AGRARIAS-BAJA01", "ci_id": "ci-ap02"},
                    {"ci_name": "CUMBRES_PTP_DIR_PLAYAS_DE_TIJUANA", "ci_id": "ci-cumbres"},
                ],
            },
        },
    )()
    client, _db = _make_client(db=_FakeHistoryDb([previous_row]), user=_ai_cmdb_diagnostic_user())

    from services.ai_chat_service import PingResult

    with (
        patch(
            "services.ai_chat_service.resolve_ci_for_harness",
            side_effect=lambda _driver, ci_ref: {
                "id": ci_ref,
                "name": ci_ref,
                "ip": "192.168.1.10",
            },
        ),
        patch(
            "services.ai_chat_service.run_bounded_ping",
            return_value=PingResult(
                "unreachable", "192.168.1.10", None, "no response to one bounded ping"
            ),
        ),
        patch(
            "services.ai_chat_service._post_lm_studio_chat_completion",
            return_value={"content": "Availability checked.", "model": "local-model"},
        ),
    ):
        response = client.post(
            "/api/ai/chat",
            json={"query": "dame el estatus actual de islas agrarias, como sigue el sitio?"},
        )

    assert response.status_code == 200
    harness_result = response.json()["harness_result"]
    assert harness_result["type"] == "availability_check_batch"
    assert [item["ci_name"] for item in harness_result["results"]] == [
        "AP01-ISLAS_AGRARIAS-BAJA01",
        "AP02-ISLAS_AGRARIAS-BAJA01",
    ]


def test_admin_can_run_followup_availability_without_ai_view_all(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    previous_row = type(
        "Row",
        (),
        {
            "username": "admin-operator",
            "user_message": "eventos abiertos",
            "assistant_response": "Open events listed.",
            "harness_result": {
                "type": "event_list",
                "events": [{"ci_name": "AP01-ISLAS_AGRARIAS-BAJA01"}],
            },
        },
    )()
    client, _db = _make_client(db=_FakeHistoryDb([previous_row]), user=_admin_user())

    from services.ai_chat_service import PingResult

    with (
        patch(
            "services.ai_chat_service.resolve_ci_for_harness",
            return_value={
                "id": "ci-ap01",
                "name": "AP01-ISLAS_AGRARIAS-BAJA01",
                "ip": "192.168.1.10",
            },
        ),
        patch(
            "services.ai_chat_service.run_bounded_ping",
            return_value=PingResult("reachable", "192.168.1.10", 1.0, "1 packet received"),
        ),
        patch(
            "services.ai_chat_service._post_lm_studio_chat_completion",
            return_value={"content": "Done.", "model": "local-model"},
        ),
    ):
        response = client.post(
            "/api/ai/chat",
            json={"query": "dame el estatus actual de islas agrarias, como sigue el sitio?"},
        )

    assert response.status_code == 200
    assert response.json()["harness_result"]["type"] == "availability_check_batch"


def test_followup_confirmation_runs_availability_batch_from_recent_event_list(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    previous_row = type(
        "Row",
        (),
        {
            "username": "ai-cmdb-diagnostic-operator",
            "user_message": "eventos críticos",
            "assistant_response": "Should I check availability?",
            "harness_result": {
                "type": "event_list",
                "events": [
                    {"ci_name": "AP01-ISLAS_AGRARIAS-BAJA01"},
                    {"ci_name": "AP02-ISLAS_AGRARIAS-BAJA01"},
                ],
            },
        },
    )()
    client, _db = _make_client(db=_FakeHistoryDb([previous_row]), user=_ai_cmdb_diagnostic_user())

    from services.ai_chat_service import PingResult

    with (
        patch(
            "services.ai_chat_service.resolve_ci_for_harness",
            side_effect=lambda _driver, ci_ref: {
                "id": ci_ref,
                "name": ci_ref,
                "ip": "192.168.1.10",
            },
        ),
        patch(
            "services.ai_chat_service.run_bounded_ping",
            return_value=PingResult("reachable", "192.168.1.10", 1.0, "1 packet received"),
        ),
        patch(
            "services.ai_chat_service._post_lm_studio_chat_completion",
            return_value={"content": "Done.", "model": "local-model"},
        ),
    ):
        response = client.post(
            "/api/ai/chat",
            json={"query": "sí"},
        )

    assert response.status_code == 200
    assert response.json()["harness_result"]["type"] == "availability_check_batch"


def test_payload_warns_model_when_no_harness_was_executed():
    from config import LMStudioSettings
    from services import ai_chat_service

    payload = ai_chat_service.build_lm_studio_payload(
        "realiza un analisis de disponibilidad",
        None,
        None,
        LMStudioSettings(enabled=True, model="local-model"),
    )

    assert "No backend harness result is present" in payload["messages"][-1]["content"]
    assert "Do not claim" in payload["messages"][-1]["content"]


def test_harness_failure_returns_operational_unavailable(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    client, _ = _make_client(user=_event_view_user())

    with patch(
        "services.ai_chat_service.list_events_for_harness", side_effect=RuntimeError("neo4j down")
    ):
        response = client.post(
            "/api/ai/chat",
            json={"query": "dime que eventos hay abiertos"},
        )

    assert response.status_code == 503
    assert (
        response.json()["detail"]
        == "Operational harness is unavailable; no diagnostic or event result was executed."
    )


def test_event_list_harness_requires_event_permission(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    client, _ = _make_client()

    with (
        patch("services.ai_chat_service.list_events_for_harness") as list_events,
        patch("services.ai_chat_service._post_lm_studio_chat_completion") as complete,
    ):
        response = client.post(
            "/api/ai/chat",
            json={
                "query": "List active events",
                "intent": {"type": "event_list", "status": "ACTIVE"},
            },
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "Not authorized to view events"
    list_events.assert_not_called()
    complete.assert_not_called()


def test_availability_check_requires_diagnostic_permission(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    client, _ = _make_client()

    with (
        patch("services.ai_chat_service.resolve_ci_for_harness") as resolve_ci,
        patch("services.ai_chat_service.run_bounded_ping") as run_ping,
        patch("services.ai_chat_service._post_lm_studio_chat_completion") as complete,
    ):
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

    with (
        patch("services.ai_chat_service.resolve_ci_for_harness") as resolve_ci,
        patch("services.ai_chat_service.run_bounded_ping") as run_ping,
        patch("services.ai_chat_service._post_lm_studio_chat_completion") as complete,
    ):
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


def test_non_harness_chat_does_not_run_ai_guard_checks(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    client, _ = _make_client()

    with (
        patch("routers.ai.check_all_guards") as check_all_guards,
        patch("services.ai_chat_service._post_lm_studio_chat_completion") as complete,
    ):
        complete.return_value = {"content": "Hello there", "model": "local-model"}
        response = client.post("/api/ai/chat", json={"query": "hello"})

    assert response.status_code == 200
    assert response.json()["answer"] == "Hello there"
    check_all_guards.assert_not_called()


def test_event_list_repeatability_no_success_cooldown_record(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    client, _ = _make_client(user=_event_view_user())

    event_list_result = {
        "type": "event_list",
        "status": "ACTIVE",
        "limit": 10,
        "severity": None,
        "count": 0,
        "truncated": False,
        "events": [],
    }

    state = {"success_logged": False}

    def fake_guard(*_args, **_kwargs):
        if state["success_logged"]:
            return GuardResult(
                allowed=False, reason="Cooldown active", cooldown_remaining_seconds=12
            )
        return GuardResult(allowed=True)

    def fake_record_operation(*_args, **_kwargs):
        if _kwargs.get("result") == "success":
            state["success_logged"] = True

    with (
        patch("routers.ai.check_all_guards", side_effect=fake_guard) as check_all_guards,
        patch("routers.ai.record_operation", side_effect=fake_record_operation) as record_operation,
        patch("routers.ai.maybe_run_harness", return_value=event_list_result) as maybe_run_harness,
    ):
        first_response = client.post(
            "/api/ai/chat",
            json={
                "query": "List active events",
                "intent": {"type": "event_list", "status": "ACTIVE", "severity": None, "limit": 10},
            },
        )
        second_response = client.post(
            "/api/ai/chat",
            json={
                "query": "List active events",
                "intent": {"type": "event_list", "status": "ACTIVE", "severity": None, "limit": 10},
            },
        )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json()["harness_result"] == event_list_result
    assert second_response.json()["harness_result"] == event_list_result
    assert check_all_guards.call_count == 2
    assert maybe_run_harness.call_count == 2
    assert not any(
        call.kwargs.get("result") == "success" for call in record_operation.call_args_list
    )
    assert state["success_logged"] is False


def test_event_list_guard_uses_event_query_target(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    client, _ = _make_client(user=_event_view_user())

    with (
        patch(
            "routers.ai.check_all_guards",
            return_value=GuardResult(allowed=False, reason="Cooldown active"),
        ) as check_all,
        patch("routers.ai.maybe_run_harness") as maybe_run,
        patch("services.ai_chat_service._post_lm_studio_chat_completion"),
        patch("routers.ai.record_operation") as record_operation,
    ):
        response = client.post(
            "/api/ai/chat",
            json={
                "query": "List active events",
                "intent": {"type": "event_list", "status": "ACTIVE", "severity": None, "limit": 10},
            },
        )

    assert response.status_code == 200
    assert maybe_run.call_count == 0
    assert response.json()["harness_result"]["status"] == "denied"
    assert response.json()["harness_result"]["target_ids"] == ["event_query:ACTIVE:any"]
    assert response.json()["harness_result"]["reason_code"] == "cooldown_active"
    assert response.json()["harness_result"]["operation"] == "diagnose"
    assert "No diagnostic or event lookup was executed." in response.json()["answer"]
    check_all.assert_called_once()
    assert not any(
        call.kwargs.get("result") == "success" for call in record_operation.call_args_list
    )


def test_availability_check_denied_blocks_execution_and_records_denied_result(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    client, db = _make_client(user=_ai_cmdb_diagnostic_user())

    ci = {"id": "ci-1", "name": "Router-01", "ip": "192.168.1.10"}
    with (
        patch("services.ai_chat_service.resolve_ci_for_harness", return_value=ci) as resolve_ci,
        patch(
            "routers.ai.check_all_guards",
            return_value=GuardResult(
                allowed=False, reason="Cooldown active", cooldown_remaining_seconds=42
            ),
        ),
        patch("routers.ai.record_operation") as record_operation,
        patch("routers.ai.maybe_run_harness") as maybe_run,
        patch("services.ai_chat_service._post_lm_studio_chat_completion"),
    ):
        response = client.post(
            "/api/ai/chat",
            json={
                "query": "Check Router-01 availability",
                "intent": {"type": "availability_check", "ci_ref": "Router-01"},
            },
        )

    assert response.status_code == 200
    assert response.json()["harness_result"]["status"] == "denied"
    assert response.json()["harness_result"]["target_ids"] == ["ci:ci-1"]
    assert response.json()["harness_result"]["reason_code"] == "cooldown_active"
    assert db.added[0].harness_result == response.json()["harness_result"]
    maybe_run.assert_not_called()
    resolve_ci.assert_called_once()
    record_operation.assert_called_once()
    assert any(call.kwargs.get("result") == "blocked" for call in record_operation.call_args_list)


def test_availability_check_canonicalizes_ci_ref_and_evaluates_guard_before_ping(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    client, _ = _make_client(user=_ai_cmdb_diagnostic_user())

    ci = {"id": "CI-ABC", "name": "Router-01", "ip": "192.168.1.10"}
    calls = []

    def fake_ping(*_args, **_kwargs):
        calls.append("ping")
        from services.ai_chat_service import PingResult

        return PingResult(
            status="reachable", target="192.168.1.10", latency_ms=10.2, detail="1 packet received"
        )

    def fake_resolve(_driver, ci_ref):
        calls.append(f"resolve:{ci_ref}")
        return ci

    with (
        patch(
            "services.ai_chat_service.resolve_ci_for_harness", side_effect=fake_resolve
        ) as resolve_ci,
        patch("services.ai_chat_service.run_bounded_ping", side_effect=fake_ping) as run_ping,
        patch("services.ai_chat_service._post_lm_studio_chat_completion") as complete,
        patch("routers.ai.check_all_guards") as check_all,
    ):
        complete.return_value = {"content": "Ready", "model": "local-model"}
        check_all.side_effect = lambda *_args, **_kwargs: GuardResult(allowed=True)
        response = client.post(
            "/api/ai/chat",
            json={
                "query": "Check Router alias-001 availability",
                "intent": {"type": "availability_check", "ci_ref": "Alias-001"},
            },
        )

    assert response.status_code == 200
    assert response.json()["answer"].startswith("Availability result for Router-01")
    assert "status: reachable" in response.json()["answer"]
    assert response.json()["harness_result"]["type"] == "availability_check"
    assert response.json()["harness_result"]["status"] == "reachable"
    assert check_all.call_args.args[2] == ["ci:CI-ABC"]
    assert calls[0].startswith("resolve:")
    assert calls[1] == "ping"
    resolve_ci.assert_called_once()
    run_ping.assert_called_once()


def test_availability_check_resolve_failure_returns_ci_not_found_without_second_resolution_or_ping(
    monkeypatch,
):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    client, _ = _make_client(user=_ai_cmdb_diagnostic_user())

    with (
        patch("services.ai_chat_service.resolve_ci_for_harness", side_effect=[None]) as resolve_ci,
        patch("services.ai_chat_service.run_bounded_ping") as run_ping,
        patch("routers.ai.maybe_run_harness") as maybe_run,
        patch("services.ai_chat_service._post_lm_studio_chat_completion") as complete,
    ):
        complete.return_value = {"content": "No host alias", "model": "local-model"}
        response = client.post(
            "/api/ai/chat",
            json={
                "query": "Check Alias-404 availability",
                "intent": {"type": "availability_check", "ci_ref": "Alias-404"},
            },
        )

    assert response.status_code == 200
    assert response.json()["harness_result"]["status"] == "ci_not_found"
    assert response.json()["harness_result"]["ci_ref"] == "Alias-404"
    assert resolve_ci.call_count == 1
    maybe_run.assert_not_called()
    run_ping.assert_not_called()


def test_availability_check_with_blank_canonical_ci_id_is_non_executable(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    client, _ = _make_client(user=_ai_cmdb_diagnostic_user())

    ci = {"id": "   ", "name": "Broken CI", "ip": "192.168.1.8"}

    with (
        patch("services.ai_chat_service.resolve_ci_for_harness", return_value=ci) as resolve_ci,
        patch("routers.ai.check_all_guards") as check_all,
        patch("services.ai_chat_service.run_bounded_ping") as run_ping,
        patch("routers.ai.maybe_run_harness") as maybe_run,
        patch("services.ai_chat_service._post_lm_studio_chat_completion") as complete,
    ):
        complete.return_value = {"content": "No valid target", "model": "local-model"}
        response = client.post(
            "/api/ai/chat",
            json={
                "query": "Check Alias-blank availability",
                "intent": {"type": "availability_check", "ci_ref": "Alias-blank"},
            },
        )

    assert response.status_code == 200
    assert response.json()["harness_result"]["status"] == "ci_not_found"
    assert response.json()["harness_result"]["ci_ref"] == "Alias-blank"
    assert resolve_ci.call_count == 1
    assert check_all.call_count == 0
    maybe_run.assert_not_called()
    run_ping.assert_not_called()


def test_availability_check_batch_with_canonical_id_missing_no_ping_or_maybe_run_harness(
    monkeypatch,
):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    client, _ = _make_client(user=_ai_cmdb_diagnostic_user())

    def resolve_side_effect(_driver, ci_ref):
        if ci_ref == "alias-no-id":
            return {"id": None, "name": "Broken CI", "ip": "192.168.1.8"}
        if ci_ref == "alias-whitespace":
            return {"id": "   ", "name": "Broken CI", "ip": "192.168.1.9"}
        if ci_ref == "alias-ok":
            return {"id": "ci-ok", "name": "Alias OK", "ip": "192.168.1.10"}
        return {"id": "ci-missing", "name": "Missing", "ip": "192.168.1.11"}

    with (
        patch(
            "services.ai_chat_service.resolve_ci_for_harness", side_effect=resolve_side_effect
        ) as resolve_ci,
        patch("routers.ai.check_all_guards") as check_all,
        patch("services.ai_chat_service.run_bounded_ping") as run_ping,
        patch("routers.ai.maybe_run_harness") as maybe_run,
        patch("routers.ai.record_operation") as record_operation,
        patch("services.ai_chat_service._post_lm_studio_chat_completion") as complete,
    ):
        complete.return_value = {"content": "Unavailable", "model": "local-model"}
        response = client.post(
            "/api/ai/chat",
            json={
                "query": "Batch check",
                "intent": {
                    "type": "availability_check_batch",
                    "ci_refs": ["alias-no-id", "alias-whitespace", "alias-ok"],
                },
            },
        )

    assert response.status_code == 200
    assert response.json()["harness_result"]["status"] == "denied"
    assert response.json()["harness_result"]["reason_code"] == "guard_unavailable"
    maybe_run.assert_not_called()
    check_all.assert_not_called()
    run_ping.assert_not_called()
    assert resolve_ci.call_count == 3
    assert any(call.kwargs.get("result") == "blocked" for call in record_operation.call_args_list)


def test_availability_check_escalation_required_denied(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    client, _ = _make_client(user=_ai_cmdb_diagnostic_user())

    ci = {"id": "ci-2", "name": "Router-02", "ip": "10.0.0.1"}
    with (
        patch("services.ai_chat_service.resolve_ci_for_harness", return_value=ci),
        patch(
            "routers.ai.check_all_guards",
            return_value=GuardResult(
                allowed=True,
                escalation_required=True,
                escalation_id="esc-1",
                reason="Need approval",
            ),
        ) as check_all,
        patch("routers.ai.record_operation") as record_operation,
        patch("routers.ai.maybe_run_harness") as maybe_run,
    ):
        response = client.post(
            "/api/ai/chat",
            json={
                "query": "Check Router-02 availability",
                "intent": {"type": "availability_check", "ci_ref": "Router-02"},
            },
        )

    assert response.status_code == 200
    assert response.json()["harness_result"]["status"] == "denied"
    assert response.json()["harness_result"]["reason_code"] == "escalation_required"
    assert response.json()["harness_result"]["escalation_required"] is True
    assert response.json()["harness_result"]["escalation_id"] == "esc-1"
    maybe_run.assert_not_called()
    check_all.assert_called_once()
    assert any(call.kwargs.get("result") == "escalated" for call in record_operation.call_args_list)


def test_availability_batch_denied_if_any_target_fails_harness_targeting(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    client, _ = _make_client(user=_ai_cmdb_diagnostic_user())

    def resolve_side_effect(_driver, ci_ref):
        return {"id": f"id-{ci_ref}", "name": ci_ref, "ip": "192.168.1.10"}

    guard_calls = 0

    def guard_side_effect(_username, _operation, target_ids):
        nonlocal guard_calls
        guard_calls += 1
        if guard_calls == 1:
            return GuardResult(allowed=True)
        if target_ids[0].endswith("alias2"):
            return GuardResult(
                allowed=False, reason="Cooldown active", cooldown_remaining_seconds=11
            )
        return GuardResult(allowed=True)

    with (
        patch(
            "services.ai_chat_service.resolve_ci_for_harness", side_effect=resolve_side_effect
        ) as resolve_ci,
        patch("routers.ai.check_all_guards", side_effect=guard_side_effect) as check_all,
        patch("routers.ai.maybe_run_harness") as maybe_run,
        patch("routers.ai.record_operation") as record_operation,
    ):
        response = client.post(
            "/api/ai/chat",
            json={
                "query": "Batch check",
                "intent": {"type": "availability_check_batch", "ci_refs": ["alias1", "alias2"]},
            },
        )

    assert response.status_code == 200
    assert response.json()["harness_result"]["status"] == "denied"
    assert set(response.json()["harness_result"]["target_ids"]) == {"ci:id-alias1", "ci:id-alias2"}
    maybe_run.assert_not_called()
    assert check_all.call_count >= 2
    assert any(call.kwargs.get("result") == "blocked" for call in record_operation.call_args_list)
    assert resolve_ci.call_count == 2


def test_availability_check_batch_with_mixed_resolved_and_unresolved_refs_denied_without_ping(
    monkeypatch,
):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    client, _ = _make_client(user=_ai_cmdb_diagnostic_user())

    def resolve_side_effect(_driver, ci_ref):
        if ci_ref == "alias1":
            return {"id": "ci-alias1", "name": "Alias 1", "ip": "192.168.1.10"}
        if ci_ref == "alias3":
            return {"id": "ci-alias3", "name": "Alias 3", "ip": "192.168.1.11"}
        return None

    def guard_side_effect(_username, _operation, target_ids):
        if target_ids == ["ci:ci-alias1", "ci:ci-alias3"]:
            return GuardResult(allowed=True)
        if target_ids == ["ci:ci-alias3"]:
            return GuardResult(
                allowed=False, reason="Cooldown active", cooldown_remaining_seconds=11
            )
        return GuardResult(allowed=True)

    with (
        patch(
            "services.ai_chat_service.resolve_ci_for_harness", side_effect=resolve_side_effect
        ) as resolve_ci,
        patch("routers.ai.check_all_guards", side_effect=guard_side_effect) as check_all,
        patch("services.ai_chat_service.run_bounded_ping") as run_ping,
        patch("routers.ai.maybe_run_harness") as maybe_run,
        patch("routers.ai.record_operation") as record_operation,
    ):
        response = client.post(
            "/api/ai/chat",
            json={
                "query": "Batch check",
                "intent": {
                    "type": "availability_check_batch",
                    "ci_refs": ["alias1", "missing", "alias3"],
                },
            },
        )

    assert response.status_code == 200
    assert response.json()["harness_result"]["status"] == "denied"
    assert response.json()["harness_result"]["reason_code"] == "cooldown_active"
    assert set(response.json()["harness_result"]["target_ids"]) == {"ci:ci-alias1", "ci:ci-alias3"}
    for call in check_all.call_args_list:
        resolved_ids = call.args[2]
        assert all(target_id in {"ci:ci-alias1", "ci:ci-alias3"} for target_id in resolved_ids)
    maybe_run.assert_not_called()
    run_ping.assert_not_called()
    assert resolve_ci.call_count == 3
    assert check_all.call_count >= 2
    assert any(call.kwargs.get("result") == "blocked" for call in record_operation.call_args_list)


def test_availability_check_batch_with_mixed_resolved_and_unresolved_refs_returns_ci_not_found(
    monkeypatch,
):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    client, _ = _make_client(user=_ai_cmdb_diagnostic_user())

    def resolve_side_effect(_driver, ci_ref):
        if ci_ref == "alias-ok":
            return {"id": "ci-ok", "name": "Alias OK", "ip": "192.168.1.10"}
        if ci_ref == "alias-ok-2":
            return {"id": "ci-ok-2", "name": "Alias OK2", "ip": "192.168.1.11"}
        return None

    def fake_ping(*_args, **_kwargs):
        from services.ai_chat_service import PingResult

        return PingResult(
            status="reachable", target="192.168.1.10", latency_ms=5.5, detail="1 packet received"
        )

    with (
        patch(
            "services.ai_chat_service.resolve_ci_for_harness", side_effect=resolve_side_effect
        ) as resolve_ci,
        patch("routers.ai.check_all_guards", return_value=GuardResult(allowed=True)) as check_all,
        patch("services.ai_chat_service.run_bounded_ping", side_effect=fake_ping) as run_ping,
        patch("services.ai_chat_service._post_lm_studio_chat_completion") as complete,
    ):
        complete.return_value = {"content": "ready", "model": "local-model"}
        response = client.post(
            "/api/ai/chat",
            json={
                "query": "Batch",
                "intent": {
                    "type": "availability_check_batch",
                    "ci_refs": ["alias-ok", "missing", "alias-ok-2"],
                },
            },
        )

    assert response.status_code == 200
    batch_results = response.json()["harness_result"]["results"]
    assert response.json()["harness_result"]["type"] == "availability_check_batch"
    assert any(
        item.get("status") == "ci_not_found" and item.get("ci_ref") == "missing"
        for item in batch_results
    )
    assert len(batch_results) == 3
    for call in check_all.call_args_list:
        assert all(target_id in {"ci:ci-ok", "ci:ci-ok-2"} for target_id in call.args[2])
    assert run_ping.call_count == 2
    assert resolve_ci.call_count == 3
    assert check_all.call_count >= 2


def test_availability_check_batch_guard_unavailable_does_not_execute_harness(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    client, db = _make_client(user=_ai_cmdb_diagnostic_user())

    with (
        patch("services.ai_chat_service.resolve_ci_for_harness") as resolve_ci,
        patch(
            "routers.ai.check_all_guards", side_effect=RuntimeError("guard db offline")
        ) as check_all,
        patch("routers.ai.maybe_run_harness") as maybe_run,
        patch("services.ai_chat_service._post_lm_studio_chat_completion") as complete,
    ):
        resolve_ci.side_effect = [
            {"id": "ci-a", "name": "A", "ip": "192.168.1.1"},
            {"id": "ci-b", "name": "B", "ip": "192.168.1.2"},
        ]
        complete.return_value = {"content": "unused", "model": "local-model"}
        response = client.post(
            "/api/ai/chat",
            json={
                "query": "Batch",
                "intent": {"type": "availability_check_batch", "ci_refs": ["alias-a", "alias-b"]},
            },
        )

    assert response.status_code == 200
    assert response.json()["harness_result"]["status"] == "denied"
    assert response.json()["harness_result"]["reason_code"] == "guard_unavailable"
    assert "could not verify it was safe" in response.json()["answer"]
    maybe_run.assert_not_called()
    assert db.added[0].harness_result["status"] == "denied"
    assert check_all.call_count >= 1
    assert resolve_ci.call_count == 2


def test_availability_check_allowed_records_success_result(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    client, _ = _make_client(user=_ai_cmdb_diagnostic_user())

    ci = {"id": "ci-77", "name": "Router-77", "ip": "192.168.1.77"}
    harness = {
        "type": "availability_check",
        "ci_id": "ci-77",
        "ci_name": "Router-77",
        "status": "reachable",
        "target": "192.168.1.77",
        "latency_ms": 4.1,
        "detail": "1 packet received",
    }

    with (
        patch("services.ai_chat_service.resolve_ci_for_harness", return_value=ci),
        patch("routers.ai.record_operation") as record_operation,
        patch("routers.ai.maybe_run_harness", return_value=harness),
    ):
        response = client.post(
            "/api/ai/chat",
            json={
                "query": "Check Router-77 availability",
                "intent": {"type": "availability_check", "ci_ref": "Router-77"},
            },
        )

    assert response.status_code == 200
    assert response.json()["harness_result"]["status"] == "reachable"
    assert response.json()["harness_result"]["ci_id"] == "ci-77"
    assert response.json()["harness_result"].get("denied", False) is False
    assert any(call.kwargs.get("result") == "success" for call in record_operation.call_args_list)
    assert any(
        call.kwargs.get("target_id") == "ci:ci-77" for call in record_operation.call_args_list
    )


def test_disabled_lm_studio_blocks_harness_side_effects(monkeypatch):
    monkeypatch.setenv("LM_STUDIO_ENABLED", "false")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    client, _ = _make_client(user=_diagnostic_user())

    with (
        patch("services.ai_chat_service.resolve_ci_for_harness") as resolve_ci,
        patch("services.ai_chat_service.run_bounded_ping") as run_ping,
        patch("services.ai_chat_service._post_lm_studio_chat_completion") as complete,
    ):
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

    with patch(
        "services.ai_chat_service.subprocess.run",
        side_effect=subprocess.TimeoutExpired(["ping"], 3),
    ):
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

    with patch(
        "services.ai_chat_service.subprocess.run", side_effect=PermissionError("secret path")
    ):
        result = run_bounded_ping("192.168.1.10")

    assert result.status == "error"
    assert result.target == "192.168.1.10"
    assert result.latency_ms is None
    assert result.detail == "ping command failed"
    assert "secret path" not in result.detail


def test_bounded_ping_maps_subprocess_failure_without_exception_details():
    from services.ai_chat_service import run_bounded_ping

    with patch(
        "services.ai_chat_service.subprocess.run",
        side_effect=subprocess.SubprocessError("secret detail"),
    ):
        result = run_bounded_ping("192.168.1.10")

    assert result.status == "error"
    assert result.target == "192.168.1.10"
    assert result.latency_ms is None
    assert result.detail == "ping command failed"
    assert "secret detail" not in result.detail


def test_post_lm_studio_logs_timeout_exception(caplog):
    from config import LMStudioSettings
    from services.ai_chat_service import LMStudioTimeoutError, _post_lm_studio_chat_completion

    settings = LMStudioSettings(
        enabled=True, model="local-model", base_url="http://lmstudio.local:1234/v1"
    )
    payload = {"model": "local-model", "messages": [{"role": "user", "content": "test"}]}
    with (
        patch(
            "services.ai_chat_service.urllib.request.urlopen", side_effect=TimeoutError("timed out")
        ),
        caplog.at_level(logging.ERROR, logger="services.ai_chat_service"),
        pytest.raises(LMStudioTimeoutError),
    ):
        _post_lm_studio_chat_completion(payload, settings)
    assert "LM Studio request timed out" in caplog.text
    assert "lmstudio.local" in caplog.text


def test_post_lm_studio_logs_url_error(caplog):
    from config import LMStudioSettings
    from services.ai_chat_service import LMStudioError, _post_lm_studio_chat_completion

    settings = LMStudioSettings(
        enabled=True, model="local-model", base_url="http://lmstudio.local:1234/v1"
    )
    payload = {"model": "local-model", "messages": [{"role": "user", "content": "test"}]}
    with (
        patch(
            "services.ai_chat_service.urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ),
        caplog.at_level(logging.ERROR, logger="services.ai_chat_service"),
        pytest.raises(LMStudioError, match="unavailable"),
    ):
        _post_lm_studio_chat_completion(payload, settings)
    assert "LM Studio unavailable" in caplog.text
    assert "lmstudio.local" in caplog.text


def test_post_lm_studio_logs_parse_error(caplog):
    from config import LMStudioSettings
    from services.ai_chat_service import LMStudioError, _post_lm_studio_chat_completion

    settings = LMStudioSettings(
        enabled=True, model="local-model", base_url="http://lmstudio.local:1234/v1"
    )
    payload = {"model": "local-model", "messages": [{"role": "user", "content": "test"}]}
    with (
        patch(
            "services.ai_chat_service.urllib.request.urlopen", side_effect=ValueError("bad data")
        ),
        caplog.at_level(logging.ERROR, logger="services.ai_chat_service"),
        pytest.raises(LMStudioError, match="could not be parsed"),
    ):
        _post_lm_studio_chat_completion(payload, settings)
    assert "LM Studio response parse error" in caplog.text
    assert "lmstudio.local" in caplog.text


def test_post_lm_studio_logs_missing_message(caplog):
    from config import LMStudioSettings
    from services.ai_chat_service import LMStudioError, _post_lm_studio_chat_completion

    settings = LMStudioSettings(
        enabled=True, model="local-model", base_url="http://lmstudio.local:1234/v1"
    )
    payload = {"model": "local-model", "messages": [{"role": "user", "content": "test"}]}
    response_body = json.dumps({"choices": []}).encode("utf-8")
    mock_response = MagicMock()
    mock_response.read.return_value = response_body
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)
    with (
        patch("services.ai_chat_service.urllib.request.urlopen", return_value=mock_response),
        caplog.at_level(logging.ERROR, logger="services.ai_chat_service"),
        pytest.raises(LMStudioError, match="did not contain a chat message"),
    ):
        _post_lm_studio_chat_completion(payload, settings)
    assert "LM Studio response missing chat message" in caplog.text
    assert "lmstudio.local" in caplog.text


# ---------------------------------------------------------------------------
# Issue #458 — Spanish verb stems / event-list phrasings in intent inference
# ---------------------------------------------------------------------------


def _previous_event_list_row(username: str = "operator"):
    return type(
        "Row",
        (),
        {
            "username": username,
            "user_message": "lista eventos activos",
            "assistant_response": "Active events listed.",
            "harness_result": {
                "type": "event_list",
                "events": [{"ci_name": "SWITCH A", "ci_id": "ci-a"}],
            },
        },
    )()


@pytest.mark.parametrize(
    "query",
    [
        "verificación de los switches",
        "verificando los equipos",
        "monitoreando la red",
        "chequeando la conectividad",
        "check the connectivity",
    ],
)
def test_infer_followup_availability_recognizes_spanish_stems(query):
    """Issue #458: new Spanish/English stems must trigger infer_followup_intent
    when a prior event_list supplies ci_refs."""
    from routers.ai import infer_followup_intent

    db = _FakeHistoryDb([_previous_event_list_row()])

    with patch("routers.ai.latest_event_list_ci_refs", return_value=["SWITCH A"]):
        result = infer_followup_intent(query, db, "operator")

    assert result is not None, f"Expected availability intent for query={query!r}"
    assert result.type == "availability_check_batch"


@pytest.mark.parametrize("query", ["tengo", "tenemos"])
def test_infer_followup_availability_rejects_event_list_only_phrasings(query):
    """Issue #458: tengo/tenemos alone (no availability verb) must not trigger
    infer_followup_intent — they are event-list phrasings, not availability."""
    from routers.ai import infer_followup_intent

    db = _FakeHistoryDb([])

    with patch("routers.ai.latest_event_list_ci_refs", return_value=[]):
        result = infer_followup_intent(query, db, "operator")

    assert result is None


@pytest.mark.parametrize(
    "query",
    [
        "tengo eventos críticos",
        "tenemos alertas abiertas",
        "cuáles son los eventos",
        "cuales eventos tenemos",
    ],
)
def test_infer_chat_intent_recognizes_event_list_phrasings(query):
    """Issue #458: tengo/tenemos/cuáles combined with an event marker must
    trigger the event-list chat intent."""
    from routers.ai import infer_chat_intent

    result = infer_chat_intent(query)

    assert result is not None, f"Expected event-list intent for query={query!r}"
    assert result.type in {"event_list", "active_events"}


def test_infer_chat_intent_rejects_tengo_without_event_marker():
    """Issue #458: tengo/tenemos alone (no availability verb) must not trigger any
    chat intent."""
    from routers.ai import infer_chat_intent

    result = infer_chat_intent("tengo una pregunta")

    assert result is None


# ---------------------------------------------------------------------------
# Issue #460 — LM Studio HTTP error mapping
# ---------------------------------------------------------------------------


def _http_error(code: int, msg: str, body: bytes | None):
    """Construct a urllib.error.HTTPError with a BytesIO fp (or None).

    ``body=None`` models upstream responses where ``exc.fp is None`` (e.g.,
    connection aborted before headers)."""
    fp = io.BytesIO(body) if body is not None else None
    return urllib.error.HTTPError(
        "http://lmstudio.local:1234/v1/chat/completions", code, msg, {}, fp
    )


# --- Service-level: HTTPError -> LMStudioRequestRejected -------------------


@pytest.mark.parametrize(
    "code, msg, body, expected_status, expected_body_preview",
    [
        (
            400,
            "Bad Request",
            b'{"error":"unknown model"}',
            400,
            '{"error":"unknown model"}',
        ),
        (404, "Not Found", None, 404, ""),
        (500, "Internal Server Error", b"oops", 500, "oops"),
        (503, "Service Unavailable", None, 503, ""),
    ],
)
def test_post_lm_studio_http_error_maps_to_request_rejected(
    code, msg, body, expected_status, expected_body_preview
):
    """Issue #460: HTTPError from urlopen MUST become LMStudioRequestRejected,
    preserving upstream status and a bounded body preview (≤512 bytes).
    Plain URLError MUST keep raising LMStudioError("LM Studio is unavailable").
    """
    from config import LMStudioSettings
    from services.ai_chat_service import (
        LMStudioRequestRejected,
        _post_lm_studio_chat_completion,
    )

    settings = LMStudioSettings(
        enabled=True, model="local-model", base_url="http://lmstudio.local:1234/v1"
    )
    payload = {"model": "local-model", "messages": [{"role": "user", "content": "test"}]}
    http_err = _http_error(code, msg, body)

    with (
        patch("services.ai_chat_service.urllib.request.urlopen", side_effect=http_err),
        pytest.raises(LMStudioRequestRejected) as excinfo,
    ):
        _post_lm_studio_chat_completion(payload, settings)

    assert excinfo.value.status == expected_status
    assert excinfo.value.body_preview == expected_body_preview


def test_post_lm_studio_http_error_truncates_body_to_512_bytes():
    """Issue #460: oversized upstream bodies MUST be bounded to 512 bytes so
    logs/502 detail cannot be flooded by malicious or buggy LM Studio replies."""
    from config import LMStudioSettings
    from services.ai_chat_service import (
        LMStudioRequestRejected,
        _post_lm_studio_chat_completion,
    )

    settings = LMStudioSettings(
        enabled=True, model="local-model", base_url="http://lmstudio.local:1234/v1"
    )
    payload = {"model": "local-model", "messages": [{"role": "user", "content": "test"}]}
    body = b"X" * 5000
    http_err = _http_error(400, "Bad Request", body)

    with (
        patch("services.ai_chat_service.urllib.request.urlopen", side_effect=http_err),
        pytest.raises(LMStudioRequestRejected) as excinfo,
    ):
        _post_lm_studio_chat_completion(payload, settings)

    assert len(excinfo.value.body_preview) == 512
    assert excinfo.value.body_preview == "X" * 512


# --- Service-level: non-HTTP URLError -> LMStudioError / LMStudioTimeoutError ---


def test_post_lm_studio_connection_refused_keeps_unavailable_error():
    """Issue #460: a plain URLError (not HTTPError) MUST keep raising
    LMStudioError("LM Studio is unavailable"). HTTPError branch must NOT
    swallow the network failure."""
    from config import LMStudioSettings
    from services.ai_chat_service import (
        LMStudioError,
        _post_lm_studio_chat_completion,
    )

    settings = LMStudioSettings(
        enabled=True, model="local-model", base_url="http://lmstudio.local:1234/v1"
    )
    payload = {"model": "local-model", "messages": [{"role": "user", "content": "test"}]}

    with (
        patch(
            "services.ai_chat_service.urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ),
        pytest.raises(LMStudioError, match="LM Studio is unavailable"),
    ):
        _post_lm_studio_chat_completion(payload, settings)


def test_post_lm_studio_dns_failure_keeps_unavailable_error():
    """Issue #460: DNS resolution failure (gaierror) is a non-HTTP URLError.
    MUST raise LMStudioError("LM Studio is unavailable"), NOT a rejection."""
    from config import LMStudioSettings
    from services.ai_chat_service import (
        LMStudioError,
        LMStudioRequestRejected,
        _post_lm_studio_chat_completion,
    )

    settings = LMStudioSettings(
        enabled=True, model="local-model", base_url="http://lmstudio.local:1234/v1"
    )
    payload = {"model": "local-model", "messages": [{"role": "user", "content": "test"}]}

    dns_err = urllib.error.URLError("Name or service not known")
    dns_err.reason = socket.gaierror("Name or service not known")

    with (
        patch("services.ai_chat_service.urllib.request.urlopen", side_effect=dns_err),
        pytest.raises(LMStudioError, match="LM Studio is unavailable") as excinfo,
    ):
        _post_lm_studio_chat_completion(payload, settings)

    assert not isinstance(excinfo.value, LMStudioRequestRejected)


def test_post_lm_studio_url_error_wrapping_timeout_stays_timeout():
    """Issue #460: URLError(reason=TimeoutError) MUST raise LMStudioTimeoutError,
    not LMStudioError or LMStudioRequestRejected. The order of the except chain
    (TimeoutError, HTTPError, URLError) must preserve the timeout signal."""
    from config import LMStudioSettings
    from services.ai_chat_service import (
        LMStudioTimeoutError,
        _post_lm_studio_chat_completion,
    )

    settings = LMStudioSettings(
        enabled=True, model="local-model", base_url="http://lmstudio.local:1234/v1"
    )
    payload = {"model": "local-model", "messages": [{"role": "user", "content": "test"}]}

    timeout_wrapped = urllib.error.URLError("timed out")
    timeout_wrapped.reason = TimeoutError("read timed out")

    with (
        patch("services.ai_chat_service.urllib.request.urlopen", side_effect=timeout_wrapped),
        pytest.raises(LMStudioTimeoutError),
    ):
        _post_lm_studio_chat_completion(payload, settings)


# --- Route-level: LMStudioRequestRejected -> 502 with structured detail ----


@pytest.mark.parametrize(
    "status, body_preview, upstream_reason, expected_detail",
    [
        (
            400,
            '{"error":"unknown model"}',
            "Bad Request",
            'LM Studio rejected the request: {"error":"unknown model"}',
        ),
        (404, "", "Not Found", "LM Studio rejected the request: Not Found"),
        (500, "oops", "Internal Server Error", "LM Studio upstream error: 500 oops"),
        (
            503,
            "",
            "Service Unavailable",
            "LM Studio upstream error: 503 Service Unavailable",
        ),
    ],
)
def test_ai_chat_maps_request_rejected_to_502_with_detail(
    monkeypatch, status, body_preview, upstream_reason, expected_detail
):
    """Issue #460: route MUST surface upstream HTTP status + reason in the 502
    detail. 4xx → "LM Studio rejected the request: <reason>"; 5xx →
    "LM Studio upstream error: <status> <reason>". The 502 status code itself
    is preserved (matches the issue's expected behaviour)."""
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    client, _ = _make_client()

    from services.ai_chat_service import LMStudioRequestRejected

    with patch(
        "services.ai_chat_service._post_lm_studio_chat_completion",
        side_effect=LMStudioRequestRejected(
            f"LM Studio rejected the request (status={status}): "
            f"{body_preview or upstream_reason}",
            status=status,
            body_preview=body_preview,
            reason=upstream_reason,
        ),
    ):
        response = client.post("/api/ai/chat", json={"query": "hello"})

    assert response.status_code == 502
    assert response.json()["detail"] == expected_detail


def test_ai_chat_plain_lm_studio_error_still_unavailable(monkeypatch):
    """Issue #460: regression guard — plain LMStudioError MUST still map to
    "LM Studio is unavailable" (the original 502 message)."""
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    client, _ = _make_client()

    from services.ai_chat_service import LMStudioError

    with patch(
        "services.ai_chat_service._post_lm_studio_chat_completion",
        side_effect=LMStudioError("Connection refused: stack"),
    ):
        response = client.post("/api/ai/chat", json={"query": "hello"})

    assert response.status_code == 502
    assert response.json()["detail"] == "LM Studio is unavailable"


def test_ai_chat_timeout_still_504(monkeypatch):
    """Issue #460: regression guard — LMStudioTimeoutError MUST still map to
    504 with detail "LM Studio request timed out"."""
    monkeypatch.setenv("LM_STUDIO_ENABLED", "true")
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://lmstudio.local:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "local-model")
    client, _ = _make_client()

    from services.ai_chat_service import LMStudioTimeoutError

    with patch(
        "services.ai_chat_service._post_lm_studio_chat_completion",
        side_effect=LMStudioTimeoutError("timeout"),
    ):
        response = client.post("/api/ai/chat", json={"query": "hello"})

    assert response.status_code == 504
    assert response.json()["detail"] == "LM Studio request timed out"
