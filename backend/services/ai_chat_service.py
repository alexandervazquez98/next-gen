from __future__ import annotations

import ipaddress
import json
import logging
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import LMStudioSettings, get_ai_prompts_settings, get_lm_studio_settings
from models.ai_chat import AIChatMessage
from models.user import AIPermission, User
from services import event_service

logger = logging.getLogger(__name__)


FALLBACK_SYSTEM_PROMPT = (
    "You are NEX-GEN Assistant, a concise and technical assistant for CMDB, "
    "monitoring, ITSM, and AIOps operations. Use only provided operational "
    "context. Do not invent tool results."
)
AI_DIR = Path(__file__).resolve().parents[1] / "ai"
# User override root. ``None`` means "feature off" -> loaders read AI_DIR in
# place (legacy behavior). Tests monkeypatch this directly; production resolves
# it lazily from AI_PROMPTS_DIR via _user_dir().
AI_USER_DIR: Path | None = None
REQUIRED_PROMPT_SOURCE_FILES = (
    "identity/Soul.md",
    "identity/scope.md",
    "identity/context-policy.md",
)
OPTIONAL_PROMPT_SOURCE_FILES = (
    "tools/README.md",
    "tools/availability_check.md",
    "tools/event-list.md",
    "tools/network-basic.md",
    "tools/visualization.md",
)
MAX_SYSTEM_PROMPT_CHARS = 10_000
MAX_AI_MARKDOWN_CHARS = 20_000
DETERMINISTIC_MODEL_LABEL = "deterministic-template"
DETERMINISTIC_HARNESS_TYPES = {"event_list", "availability_check", "availability_check_batch"}

MAX_QUERY_CHARS = 2_000
MAX_CONTEXT_CHARS = 4_000
MAX_HISTORY_TURNS = 6
MAX_HISTORY_CHARS = 8_000
MAX_BATCH_AVAILABILITY_CHECKS = 5
_SAFE_HOST_RE = re.compile(r"^[A-Za-z0-9.-]{1,253}$")


def _estimate_tokens(text: str) -> int:
    """Approximate token count for chat text.

    Uses a conservative ``len(text) // 4`` rule of thumb. This is
    intentionally NOT a real BPE tokenizer: tiktoken is OpenAI-specific and
    misleads on Qwen / local models. The approximation is good enough for
    sliding-window compaction against an input context window.
    """
    return len(text) // 4


def _compact_history(
    messages: list[dict[str, str]], settings: LMStudioSettings
) -> list[dict[str, str]]:
    """Drop oldest non-system messages until estimated tokens fit the budget.

    The first message with ``role == "system"`` is RESERVED: it is never
    trimmed and does not count toward the compaction budget that drives
    eviction. The system prompt is bounded separately by
    ``MAX_SYSTEM_PROMPT_CHARS``.

    Setting ``compaction_threshold >= 1.0`` disables compaction entirely
    (operator kill switch).

    Returns a NEW list; the input is not mutated.
    """
    if not messages:
        return []
    if settings.compaction_threshold >= 1.0:
        return list(messages)

    has_system = messages[0].get("role") == "system"
    system_msg = messages[0] if has_system else None
    rest = list(messages[1:] if has_system else messages)

    budget = int(settings.context_limit_tokens * settings.compaction_threshold)

    total = sum(_estimate_tokens(str(m.get("content", ""))) for m in rest)
    dropped = 0
    while total > budget and len(rest) > 1:
        removed = rest.pop(0)
        total -= _estimate_tokens(str(removed.get("content", "")))
        dropped += 1

    if dropped > 0:
        logger.info(
            "Compacted AI chat history: dropped %d oldest non-system messages "
            "(context_limit_tokens=%d, compaction_threshold=%.2f, budget_tokens=%d)",
            dropped,
            settings.context_limit_tokens,
            settings.compaction_threshold,
            budget,
        )

    result: list[dict[str, str]] = []
    if system_msg is not None:
        result.append(system_msg)
    result.extend(rest)
    return result


class LMStudioError(Exception):
    """LM Studio returned an unusable response or could not be reached."""


class LMStudioTimeoutError(LMStudioError):
    """LM Studio did not answer within the configured timeout."""


class LMStudioRequestRejected(LMStudioError):  # noqa: N818
    """LM Studio returned a 4xx/5xx HTTP response (not a network failure).

    Carries the upstream status code, a bounded body excerpt (≤512 bytes), and
    the upstream ``reason`` string so the route can surface actionable detail
    to operators instead of the generic "LM Studio is unavailable".
    """

    def __init__(
        self,
        message: str,
        *,
        status: int,
        body_preview: str = "",
        reason: str = "",
    ) -> None:
        super().__init__(message)
        self.status = status
        self.body_preview = body_preview
        self.reason = reason


_BODY_PREVIEW_MAX_BYTES = 512


def _user_dir() -> Path | None:
    """Resolve the user override root, caching the env lookup in AI_USER_DIR."""
    global AI_USER_DIR
    if AI_USER_DIR is None:
        configured = get_ai_prompts_settings().prompts_dir
        if configured:
            AI_USER_DIR = Path(configured)
    return AI_USER_DIR


def _resolve_prompt(rel: str) -> Path:
    """Return the user override file when present, else the bundled default.

    ``rel`` is relative to the prompts root (e.g. ``identity/Soul.md``).
    The bundled tree is the invisible fallback so a missing user file never
    breaks the runtime.
    """
    user_root = _user_dir()
    if user_root is not None:
        candidate = user_root / rel
        if candidate.is_file():
            return candidate
    return AI_DIR / rel


def _has_user_prompt_files(user_dir: Path) -> bool:
    """Return true once the operator folder contains any prompt markdown file."""
    return any(path.is_file() and path.suffix == ".md" for path in user_dir.rglob("*"))


def ensure_ai_prompts_seeded() -> None:
    """Seed the user prompts folder once from the bundled defaults (frozen).

    No-op when AI_PROMPTS_DIR is unset. When the folder is empty or missing it
    is populated with a full copy of the bundled ``ai/`` tree. Once any file is
    present the folder is treated as a frozen snapshot: we never overwrite or
    add files, honoring operator ownership.
    """
    prompts_dir = get_ai_prompts_settings().prompts_dir
    if not prompts_dir:
        return
    user_dir = Path(prompts_dir)
    if user_dir.exists() and _has_user_prompt_files(user_dir):
        return
    user_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(AI_DIR, user_dir, dirs_exist_ok=True)
    logger.info("Seeded AI prompts folder at %s from bundled defaults", user_dir)


def load_system_prompt() -> str:
    """Compose the bounded runtime system prompt from backend-owned sources."""
    sections: list[str] = []
    try:
        for rel in REQUIRED_PROMPT_SOURCE_FILES:
            source = _resolve_prompt(rel)
            text = source.read_text(encoding="utf-8").strip()
            if not text:
                return FALLBACK_SYSTEM_PROMPT
            sections.append(f"## {rel}\n{text}")
    except OSError:
        return FALLBACK_SYSTEM_PROMPT

    for rel in OPTIONAL_PROMPT_SOURCE_FILES:
        source = _resolve_prompt(rel)
        try:
            text = source.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text:
            sections.append(f"## {rel}\n{text}")

    prompt = "\n\n".join(sections)
    if len(prompt) > MAX_SYSTEM_PROMPT_CHARS:
        return prompt[:MAX_SYSTEM_PROMPT_CHARS].rstrip()
    return prompt


@dataclass(frozen=True)
class PingResult:
    status: str
    target: str
    latency_ms: float | None
    detail: str

    def to_metadata(self, ci: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "availability_check",
            "ci_id": ci.get("id"),
            "ci_name": ci.get("name"),
            "target": self.target,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "detail": self.detail,
        }


def build_lm_studio_payload(
    query: str,
    context: str | None,
    harness_result: dict[str, Any] | None,
    settings: LMStudioSettings,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Build a bounded OpenAI-compatible chat completion payload."""
    trimmed_query = query[:MAX_QUERY_CHARS]
    trimmed_context = (context or "")[:MAX_CONTEXT_CHARS]
    user_content = f"User question:\n{trimmed_query}"
    if trimmed_context:
        user_content = f"{user_content}\n\nOperational context:\n{trimmed_context}"
    if harness_result:
        user_content += "\n\nHarness result:\n" + json.dumps(harness_result, sort_keys=True)
    else:
        user_content += (
            "\n\nNo backend harness result is present for this request. "
            "Do not claim that event lookups, diagnostics, availability checks, "
            "ping, or tool execution were performed."
        )

    messages = [{"role": "system", "content": load_system_prompt()}]
    messages.extend(history or [])
    messages.append({"role": "user", "content": user_content})

    messages = _compact_history(messages, settings)

    return {
        "model": settings.model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": settings.max_tokens,
        "stream": False,
    }


def _post_lm_studio_chat_completion(
    payload: dict[str, Any], settings: LMStudioSettings
) -> dict[str, str]:
    url = f"{settings.base_url}/chat/completions"
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
    except TimeoutError as exc:
        logger.exception("LM Studio request timed out (url=%s)", url)
        raise LMStudioTimeoutError("LM Studio request timed out") from exc
    except urllib.error.HTTPError as exc:
        body_preview = ""
        if exc.fp is not None:
            try:
                raw = exc.read()
                body_preview = raw[:_BODY_PREVIEW_MAX_BYTES].decode("utf-8", errors="replace")
            except OSError:
                body_preview = ""
        upstream_reason = str(getattr(exc, "reason", "") or "")
        logger.warning(
            "LM Studio rejected the request (url=%s, status=%s, body_preview=%s)",
            url,
            exc.code,
            body_preview,
        )
        raise LMStudioRequestRejected(
            f"LM Studio rejected the request (status={exc.code}): "
            f"{body_preview or upstream_reason}",
            status=int(exc.code or 0),
            body_preview=body_preview,
            reason=upstream_reason,
        ) from exc
    except urllib.error.URLError as exc:
        if isinstance(getattr(exc, "reason", None), TimeoutError):
            logger.exception("LM Studio request timed out (url=%s)", url)
            raise LMStudioTimeoutError("LM Studio request timed out") from exc
        logger.exception("LM Studio unavailable (url=%s)", url)
        raise LMStudioError("LM Studio is unavailable") from exc
    except Exception as exc:
        logger.exception("LM Studio response parse error (url=%s)", url)
        raise LMStudioError("LM Studio response could not be parsed") from exc

    try:
        message = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        logger.exception("LM Studio response missing chat message (url=%s)", url)
        raise LMStudioError("LM Studio response did not contain a chat message") from exc
    return {"content": str(message), "model": str(data.get("model") or settings.model)}


def resolve_ci_for_harness(neo4j_driver, ci_ref: str) -> dict[str, Any] | None:
    """Resolve a CI by id or name using stored CMDB data only."""
    with neo4j_driver.session() as session:
        record = session.run(
            """
            MATCH (ci:CI)
            WHERE ci.id = $ci_ref OR toLower(ci.name) = toLower($ci_ref)
            RETURN ci { .id, .name, .ip, .hostname } AS ci
            LIMIT 1
            """,
            ci_ref=ci_ref,
        ).single()
    return record["ci"] if record else None


def resolve_ping_target(ci: dict[str, Any]) -> str:
    """Return a safe stored IP/hostname target for a bounded ping."""
    target = str(ci.get("ip") or ci.get("hostname") or "").strip()
    if not target:
        raise ValueError("CI has no stored IP or hostname")
    try:
        ipaddress.ip_address(target)
        return target
    except ValueError:
        if _SAFE_HOST_RE.fullmatch(target) and ".." not in target and not target.startswith("-"):
            return target
    raise ValueError("CI has an unsafe ping target")


def run_bounded_ping(target: str) -> PingResult:
    """Run one Linux-focused ping with bounded count and timeout."""
    try:
        completed = subprocess.run(
            ["ping", "-c", "1", "-W", "2", target],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return PingResult(
            status="error",
            target=target,
            latency_ms=None,
            detail="ping command timed out",
        )
    except FileNotFoundError:
        return PingResult(
            status="error",
            target=target,
            latency_ms=None,
            detail="ping command not found",
        )
    except (PermissionError, OSError, subprocess.SubprocessError):
        return PingResult(
            status="error",
            target=target,
            latency_ms=None,
            detail="ping command failed",
        )
    output = f"{completed.stdout}\n{completed.stderr}".strip()
    latency_match = re.search(r"time=([0-9.]+)\s*ms", output)
    latency_ms = float(latency_match.group(1)) if latency_match else None
    status = "reachable" if completed.returncode == 0 else "unreachable"
    detail = "1 packet received" if status == "reachable" else "no response to one bounded ping"
    return PingResult(status=status, target=target, latency_ms=latency_ms, detail=detail)


def _safe_ci_field(ci: Any, field: str) -> Any:
    if isinstance(ci, dict):
        return ci.get(field)
    getter = getattr(ci, "get", None)
    if callable(getter):
        try:
            return getter(field)
        except TypeError:
            return None
    return getattr(ci, field, None)


_PRIVATE_INTENT_MISSING = object()


def _private_intent_value(intent: Any, key: str) -> Any:
    try:
        intent_vars = vars(intent)
        if key in intent_vars:
            return intent_vars[key]
    except TypeError:
        return _PRIVATE_INTENT_MISSING
    try:
        class_vars = vars(type(intent))
    except TypeError:
        return _PRIVATE_INTENT_MISSING
    return class_vars.get(key, _PRIVATE_INTENT_MISSING)


def _run_availability_harness(intent: Any, neo4j_driver) -> dict[str, Any]:
    ci_ref = str(getattr(intent, "ci_ref", "")).strip()
    ci = _private_intent_value(intent, "_resolved_ci")
    if ci is _PRIVATE_INTENT_MISSING:
        ci = resolve_ci_for_harness(neo4j_driver, ci_ref)
    if ci is None:
        return {"type": "availability_check", "ci_ref": ci_ref, "status": "ci_not_found"}

    try:
        target = resolve_ping_target(ci)
        return run_bounded_ping(target).to_metadata(ci)
    except ValueError as exc:
        return {
            "type": "availability_check",
            "ci_id": _safe_ci_field(ci, "id"),
            "ci_name": _safe_ci_field(ci, "name"),
            "status": "invalid_target",
            "detail": str(exc),
        }


def _compact_event_summary(event: dict[str, Any]) -> dict[str, Any]:
    """Return a provider-neutral event summary safe for chat context."""
    fields = (
        "id",
        "ci_id",
        "ci_name",
        "ci_hostname",
        "ci_location_name",
        "metric_id",
        "metric_name",
        "metric_protocol",
        "status",
        "severity",
        "message",
        "event_type",
        "source_protocol",
        "correlation_type",
        "root_cause_ci_id",
        "created_at",
        "last_seen",
    )
    return {key: event.get(key) for key in fields if event.get(key) is not None}


def _event_scope_for_user(user: User | None) -> tuple[bool, list[str] | None, list[str] | None]:
    if user is None or user.role == "ADMIN" or AIPermission.AI_VIEW_ALL.value in user.permissions:
        return True, None, None
    allowed_locations = list(user.allowed_locations or [])
    allowed_ci_types = list(user.allowed_ci_types or []) if user.allowed_ci_types else None
    return False, allowed_locations, allowed_ci_types


def list_events_for_harness(
    neo4j_driver,
    status_filter: str,
    limit: int,
    severity_filter: str | None = None,
    user: User | None = None,
    include_children: bool = True,
) -> list[dict[str, Any]]:
    """Fetch at most limit + 1 scoped event summaries for bounded chat context.

    P2 REQ-009: AI chat context historically needs the raw N+1 set so the
    agent can reason about every state. The new public `get_events`
    defaults to root-only via `include_children=False`. The harness
    boundary preserves the prior behaviour by passing `include_children=True`
    explicitly so the P2 default flip is transparent to the AI consumer.
    """
    is_unscoped, allowed_locations, allowed_ci_types = _event_scope_for_user(user)
    if not is_unscoped and not allowed_locations:
        return []

    query_limit = limit + 1
    with neo4j_driver.session() as session:
        result = session.run(
            """
            MATCH (e:Event)<-[:HAS_EVENT]-(ci:CI)
            WITH e, ci
            WHERE (
                $status IS NULL
                OR ($status = 'ACTIVE' AND e.status IN ['OPEN', 'ACK'])
                OR ($status = 'CONSOLE' AND e.status IN ['OPEN', 'ACK', 'RECOVERED'])
                OR ($status <> 'ACTIVE' AND $status <> 'CONSOLE' AND e.status = $status)
            )
            AND ($severity IS NULL OR e.severity = $severity)
            AND ($is_unscoped OR ci.location_name IN $allowed_locations)
            AND ($allowed_ci_types IS NULL OR ci.layer IN $allowed_ci_types)
            AND (
                $include_children
                OR coalesce(e.correlation_type, 'ROOT') = 'ROOT'
            )
            OPTIONAL MATCH (e)-[:TRIGGERED_BY]->(m:MetricDef)
            RETURN e, ci, m
            ORDER BY e.created_at DESC
            LIMIT $limit
            """,
            status=status_filter,
            severity=severity_filter,
            is_unscoped=is_unscoped,
            allowed_locations=allowed_locations or [],
            allowed_ci_types=allowed_ci_types,
            include_children=include_children,
            limit=query_limit,
        )
        return [
            event_service._public_event_summary(
                event_service._build_event_summary(
                    event_service._node_to_dict(record["e"]),
                    event_service._node_to_dict(record["ci"]),
                    event_service._node_to_dict(record["m"]),
                )
            )
            for record in result
        ]


def _run_event_list_harness(intent: Any, neo4j_driver, user: User | None = None) -> dict[str, Any]:
    status_filter = str(getattr(intent, "status", "ACTIVE") or "ACTIVE").upper()
    limit = int(getattr(intent, "limit", 10) or 10)
    severity_filter = getattr(intent, "severity", None)
    severity_filter = str(severity_filter).upper() if severity_filter else None
    events = list_events_for_harness(neo4j_driver, status_filter, limit, severity_filter, user=user)
    truncated = len(events) > limit
    visible_events = [_compact_event_summary(event) for event in events[:limit]]
    return {
        "type": "event_list",
        "status": status_filter,
        "limit": limit,
        "severity": severity_filter,
        "count": len(visible_events),
        "truncated": truncated,
        "events": visible_events,
    }


def _run_availability_batch_harness(intent: Any, neo4j_driver) -> dict[str, Any]:
    ci_refs = list(getattr(intent, "ci_refs", []) or [])[:MAX_BATCH_AVAILABILITY_CHECKS]
    resolved_by_ref = _private_intent_value(intent, "_resolved_ci_targets")
    results = []
    for ci_ref in ci_refs:
        normalized_ref = str(ci_ref).strip()
        child_ci = (
            resolved_by_ref.get(normalized_ref) if isinstance(resolved_by_ref, dict) else None
        )
        if isinstance(resolved_by_ref, dict) and normalized_ref in resolved_by_ref:
            child_intent = type(
                "AvailabilityIntent",
                (),
                {"ci_ref": normalized_ref, "_resolved_ci": child_ci},
            )()
        else:
            child_intent = type("AvailabilityIntent", (), {"ci_ref": normalized_ref})()
        results.append(_run_availability_harness(child_intent, neo4j_driver))
    return {
        "type": "availability_check_batch",
        "count": len(results),
        "results": results,
    }


HARNESS_EXECUTORS = {
    "availability_check": _run_availability_harness,
    "availability_check_batch": _run_availability_batch_harness,
    "active_events": _run_event_list_harness,
    "event_list": _run_event_list_harness,
}


def maybe_run_harness(intent: Any, neo4j_driver, user: User | None = None) -> dict[str, Any] | None:
    if not intent:
        return None
    executor = HARNESS_EXECUTORS.get(str(getattr(intent, "type", "")))
    if executor is None:
        return None
    if str(getattr(intent, "type", "")) in {"event_list", "active_events"}:
        return executor(intent, neo4j_driver, user)
    return executor(intent, neo4j_driver)


def load_chat_history(db, username: str, limit: int = MAX_HISTORY_TURNS) -> list[dict[str, str]]:
    """Load a bounded per-user chat history for provider-neutral replay."""
    try:
        rows = (
            db.query(AIChatMessage)
            .filter(AIChatMessage.username == username)
            .order_by(AIChatMessage.created_at.desc())
            .limit(limit)
            .all()
        )
    except Exception:
        return []

    messages: list[dict[str, str]] = []
    remaining_chars = MAX_HISTORY_CHARS
    for row in reversed(rows):
        pairs = (
            ("user", str(getattr(row, "user_message", ""))[:MAX_QUERY_CHARS]),
            ("assistant", str(getattr(row, "assistant_response", ""))[:MAX_CONTEXT_CHARS]),
        )
        for role, content in pairs:
            if not content or remaining_chars <= 0:
                continue
            trimmed = content[:remaining_chars]
            messages.append({"role": role, "content": trimmed})
            remaining_chars -= len(trimmed)
    return messages


def _normalized_terms(text: str) -> list[str]:
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return [term for term in normalized.split() if len(term) >= 4]


def _event_matches_query(event: dict[str, Any], query_terms: list[str]) -> bool:
    if not query_terms:
        return True
    haystack = (
        " ".join(
            str(event.get(field) or "")
            for field in ("ci_name", "ci_id", "ci_hostname", "ci_location_name", "message")
        )
        .lower()
        .replace("_", " ")
        .replace("-", " ")
    )
    return all(term in haystack for term in query_terms)


def latest_event_list_ci_refs(
    db,
    username: str,
    limit: int = MAX_BATCH_AVAILABILITY_CHECKS,
    query: str | None = None,
) -> list[str]:
    """Return CI refs from the latest event_list harness result for follow-up checks."""
    try:
        rows = (
            db.query(AIChatMessage)
            .filter(AIChatMessage.username == username)
            .order_by(AIChatMessage.created_at.desc())
            .limit(MAX_HISTORY_TURNS)
            .all()
        )
    except Exception:
        return []

    query_terms = [
        term
        for term in _normalized_terms(query or "")
        if term
        not in {
            "estatus",
            "estado",
            "siguen",
            "sigue",
            "actual",
            "sitio",
            "disponibilidad",
            "analisis",
            "análisis",
            "chequeo",
            "verifica",
            "verificar",
            "revisa",
            "revisar",
            "equipos",
            "funcionando",
            "dame",
            "como",
        }
    ]
    for row in rows:
        harness_result = getattr(row, "harness_result", None) or {}
        if harness_result.get("type") != "event_list":
            continue
        refs: list[str] = []
        events = list(harness_result.get("events", []) or [])
        matching_events = [event for event in events if _event_matches_query(event, query_terms)]
        selected_events = matching_events or events
        for event in selected_events:
            ci_ref = event.get("ci_name") or event.get("ci_id")
            if ci_ref and ci_ref not in refs:
                refs.append(str(ci_ref))
            if len(refs) >= limit:
                return refs
        return refs
    return []


def save_chat_exchange(
    db,
    *,
    username: str,
    user_message: str,
    assistant_response: str,
    context: str | None,
    harness_result: dict[str, Any] | None,
    model: str | None,
) -> AIChatMessage:
    row = AIChatMessage(
        username=username,
        user_message=user_message[:MAX_QUERY_CHARS],
        assistant_response=assistant_response,
        context=(context or "")[:MAX_CONTEXT_CHARS] or None,
        harness_result=harness_result,
        model=model,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def load_ai_markdown_contract(section: str, filename: str) -> str:
    """Load a bounded known AI policy/template markdown file."""
    if section not in {"policies", "templates"} or "/" in filename or ".." in filename:
        return ""
    try:
        path = _resolve_prompt(f"{section}/{filename}")
        return path.read_text(encoding="utf-8")[:MAX_AI_MARKDOWN_CHARS]
    except OSError:
        return ""


def _fmt(value: Any, fallback: str = "n/a") -> str:
    if value is None or value == "":
        return fallback
    return str(value)


def _fmt_latency(value: Any) -> str:
    return "n/a" if value is None or value == "" else f"{value} ms"


def _event_symptom(event: dict[str, Any], spanish: bool) -> str:
    text = " ".join(
        str(event.get(key) or "") for key in ("message", "metric_name", "metric_id", "event_type")
    ).lower()
    ci = event.get("ci_name") or event.get("ci_id") or "CI desconocido"
    severity = event.get("severity") or "UNKNOWN"
    if any(marker in text for marker in ("latency", "threshold", "umbral", "icmp_latency")):
        return (
            f"- {ci}: presenta una alerta de latencia/umbral {severity} observada en el evento."
            if spanish
            else f"- {ci}: shows an observed latency/threshold {severity} event symptom."
        )
    if any(marker in text for marker in ("ping", "down", "availability", "host")):
        return (
            f"- {ci}: presenta un síntoma de disponibilidad/ping-check reportado por el evento."
            if spanish
            else f"- {ci}: shows an observed availability/ping-check event symptom."
        )
    return (
        f"- {ci}: mantiene estado {event.get('status') or 'UNKNOWN'} con severidad {severity}."
        if spanish
        else f"- {ci}: has status {event.get('status') or 'UNKNOWN'} with severity {severity}."
    )


def _render_event_list_response(query: str, harness_result: dict[str, Any]) -> str:
    spanish = _prefers_spanish(query)
    events = list(harness_result.get("events", []) or [])
    status = harness_result.get("status") or "ACTIVE"
    severity = harness_result.get("severity")
    filter_text = f"status={status}" + (f", severity={severity}" if severity else "")
    if not events:
        if spanish:
            return f"No hay eventos para {filter_text}.\n\nLímites:\n- No hay hechos de eventos para diagnosticar."
        return f"There are no events for {filter_text}.\n\nLimitations:\n- No event facts are available for diagnosis."

    lines = [
        (
            f"Hay {len(events)} eventos para {filter_text}."
            if spanish
            else f"There are {len(events)} events for {filter_text}."
        ),
        "",
        "Eventos observados:" if spanish else "Observed events:",
    ]
    for event in events:
        ci = event.get("ci_name") or event.get("ci_id") or "CI desconocido"
        message = event.get("message") or event.get("metric_name") or "sin detalle"
        last_seen = f"; last_seen={event.get('last_seen')}" if event.get("last_seen") else ""
        lines.append(
            f"- [{event.get('severity') or 'UNKNOWN'} / {event.get('status') or status}] {ci}: {message}{last_seen}"
        )
    lines.extend(
        [
            "",
            "Diagnóstico observado:" if spanish else "Observed diagnosis:",
            *[_event_symptom(event, spanish) for event in events],
            "",
            "Límites:" if spanish else "Limitations:",
        ]
    )
    if spanish:
        lines.extend(
            [
                "- No confirma causa raíz ni cierre del evento.",
                "- No confirma congestión, energía, cableado, firewall, salud completa del servicio ni estado estable/óptimo.",
                "",
                "Siguiente chequeo sugerido:",
                "- Ejecutar availability_check para CIs con síntomas de disponibilidad y revisar métricas históricas para latencia.",
            ]
        )
    else:
        lines.extend(
            [
                "- Does not confirm root cause or event closure.",
                "- Does not confirm congestion, power, cabling, firewall, complete service health, or stable/optimal state.",
                "",
                "Suggested next checks:",
                "- Run availability_check for CIs with availability symptoms and review historical metrics for latency.",
            ]
        )
    if harness_result.get("truncated"):
        lines.append(
            "- Resultado truncado por seguridad; pedí más detalle si necesitás ampliar."
            if spanish
            else "- Result truncated for safety; ask for more detail if needed."
        )
    return "\n".join(lines)


def _render_availability_check_response(query: str, result: dict[str, Any]) -> str:
    spanish = _prefers_spanish(query)
    ci = result.get("ci_name") or result.get("ci_ref") or result.get("ci_id") or "CI desconocido"
    lines = [
        (
            f"Resultado de disponibilidad para {ci}:"
            if spanish
            else f"Availability result for {ci}:"
        ),
        f"- status: {_fmt(result.get('status'))}",
        f"- target: {_fmt(result.get('target'))}",
        f"- latency: {_fmt_latency(result.get('latency_ms'))}",
        f"- detail: {_fmt(result.get('detail'))}",
        "",
    ]
    if spanish:
        lines.extend(
            [
                "Interpretación permitida:",
                "- Este resultado describe solo un ping acotado actual ejecutado por el backend.",
                "",
                "Límites:",
                "- No confirma salud completa del servicio, causa raíz ni cierre automático de eventos.",
            ]
        )
    else:
        lines.extend(
            [
                "Interpretation:",
                "- This result describes only a current bounded ping executed by the backend.",
                "",
                "Limitations:",
                "- It does not confirm complete service health, root cause, or automatic event closure.",
            ]
        )
    return "\n".join(lines)


def _render_availability_batch_response(query: str, harness_result: dict[str, Any]) -> str:
    spanish = _prefers_spanish(query)
    results = list(harness_result.get("results", []) or [])[:MAX_BATCH_AVAILABILITY_CHECKS]
    lines = [
        (
            f"Chequeo de disponibilidad ejecutado sobre {len(results)} CIs:"
            if spanish
            else f"Availability check executed for {len(results)} CIs:"
        ),
    ]
    for result in results:
        ci = (
            result.get("ci_name") or result.get("ci_ref") or result.get("ci_id") or "CI desconocido"
        )
        lines.append(
            f"- {ci}: {result.get('status') or 'unknown'}, target={_fmt(result.get('target'))}, "
            f"latency={_fmt_latency(result.get('latency_ms'))}, detail={_fmt(result.get('detail'))}"
        )
    lines.append("")
    if spanish:
        lines.extend(
            [
                "Interpretación permitida:",
                "- Los resultados describen ping acotado actual; máximo 5 CIs por lote.",
                "",
                "Límites:",
                "- La respuesta a ping no confirma salud completa del servicio, causa raíz ni cierre automático de eventos.",
            ]
        )
    else:
        lines.extend(
            [
                "Interpretation:",
                "- Results describe current bounded ping checks only; maximum 5 CIs per batch.",
                "",
                "Limitations:",
                "- Ping reachability does not confirm complete service health, root cause, or automatic event closure.",
            ]
        )
    return "\n".join(lines)


def render_harness_response(query: str, harness_result: dict[str, Any] | None) -> str | None:
    if not harness_result:
        return None
    if harness_result.get("status") == "denied":
        return _render_harness_denial_response(query, harness_result)
    harness_type = harness_result.get("type")
    if harness_type == "event_list":
        load_ai_markdown_contract("templates", "event_list.md")
        return _render_event_list_response(query, harness_result)
    if harness_type == "availability_check":
        load_ai_markdown_contract("templates", "availability_check.md")
        return _render_availability_check_response(query, harness_result)
    if harness_type == "availability_check_batch":
        load_ai_markdown_contract("templates", "availability_check_batch.md")
        return _render_availability_batch_response(query, harness_result)
    return None


def _prefers_spanish(query: str) -> bool:
    lowered = query.lower()
    return any(
        marker in lowered
        for marker in (
            " que ",
            "eventos",
            "abiertos",
            "crític",
            "funcionando",
            "verifica",
            "dime",
            "dame",
            "estatus",
        )
    )


def _fallback_event_list_response(harness_result: dict[str, Any], spanish: bool) -> str:
    events = list(harness_result.get("events", []) or [])
    status = harness_result.get("status") or "ACTIVE"
    severity = harness_result.get("severity")
    if not events:
        if spanish:
            qualifier = f" {severity}" if severity else ""
            return f"No hay eventos{qualifier} con estado {status} en este momento."
        qualifier = f" {severity}" if severity else ""
        return f"There are no{qualifier} events with status {status} right now."

    severity_order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
    events.sort(
        key=lambda event: (
            severity_order.get(str(event.get("severity")), 9),
            str(event.get("ci_name") or ""),
        )
    )
    lines = []
    if spanish:
        lines.append(f"Hay {len(events)} eventos abiertos en este momento:")
    else:
        lines.append(f"There are {len(events)} open events right now:")
    for event in events[:10]:
        ci_name = event.get("ci_name") or event.get("ci_id") or "CI desconocido"
        event_severity = event.get("severity") or "UNKNOWN"
        event_status = event.get("status") or status
        message = event.get("message") or event.get("metric_name") or "sin detalle"
        lines.append(f"- [{event_severity} / {event_status}] {ci_name}: {message}")
    if harness_result.get("truncated"):
        lines.append(
            "- Resultado truncado por seguridad; pedí más detalle si necesitás ampliar."
            if spanish
            else "- Result truncated for safety; ask for more detail if needed."
        )
    return "\n".join(lines)


def _fallback_availability_batch_response(harness_result: dict[str, Any], spanish: bool) -> str:
    results = list(harness_result.get("results", []) or [])
    if not results:
        return (
            "No se ejecutaron verificaciones de disponibilidad."
            if spanish
            else "No availability checks were executed."
        )
    lines = ["Resultado de disponibilidad:" if spanish else "Availability results:"]
    for result in results[:MAX_BATCH_AVAILABILITY_CHECKS]:
        ci_name = (
            result.get("ci_name") or result.get("ci_ref") or result.get("ci_id") or "CI desconocido"
        )
        status = result.get("status") or "unknown"
        detail = result.get("detail") or ""
        lines.append(f"- {ci_name}: {status}{f' ({detail})' if detail else ''}")
    return "\n".join(lines)


def _infer_guard_denial_reason_code(
    reason: str | None,
    escalation_required: bool,
) -> str:
    if escalation_required:
        return "escalation_required"
    reason_text = (reason or "").lower()
    if "cooldown" in reason_text:
        return "cooldown_active"
    if "bulk" in reason_text:
        return "bulk_operation_too_large"
    if "behavior" in reason_text or "flood" in reason_text:
        return "behavioral_guard_denied"
    return "guard_denied"


def build_guard_denial_harness_result(
    *,
    intent_type: str,
    reason: str | None,
    target_type: str,
    target_ids: list[str],
    request_context: dict[str, Any] | None = None,
    escalation_required: bool = False,
    escalation_id: str | None = None,
    cooldown_remaining_seconds: int | None = None,
    reason_code: str | None = None,
) -> dict[str, Any]:
    normalized_reason = reason or "AI guardrail denied execution for safety"
    normalized_code = reason_code or _infer_guard_denial_reason_code(
        normalized_reason,
        escalation_required=escalation_required,
    )
    return {
        "type": intent_type,
        "status": "denied",
        "denied": True,
        "reason": normalized_reason,
        "reason_code": normalized_code,
        "cooldown_remaining_seconds": cooldown_remaining_seconds,
        "escalation_required": escalation_required,
        "escalation_id": escalation_id,
        "operation": "diagnose",
        "target_type": target_type,
        "target_ids": list(target_ids),
        "request_context": request_context or {},
        "source": "ai_guard_service",
    }


def _render_harness_denial_response(query: str, harness_result: dict[str, Any]) -> str:
    spanish = _prefers_spanish(query)
    reason = str(harness_result.get("reason") or "").strip()
    reason_code = harness_result.get("reason_code")
    if reason_code == "guard_unavailable":
        if spanish:
            return (
                "No puedo ejecutar esta verificación operativa ahora porque el sistema de guardrails de IA "
                "no pudo verificar que fuera seguro. No se ejecutó ningún diagnóstico ni consulta de eventos."
            )
        return (
            "I cannot run that operational check right now because the AI guardrail system "
            "could not verify it was safe. No diagnostic or event lookup was executed."
        )

    if not reason:
        reason = "an AI guardrail check blocked this harness execution"
    if spanish:
        return (
            f"No puedo ejecutar esa verificación operativa ahora: {reason}. "
            "No se ejecutó ningún diagnóstico ni consulta de eventos."
        )
    return (
        f"I cannot run that operational check right now because a guardrail blocked it: {reason}. "
        "No diagnostic or event lookup was executed."
    )


def synthesize_harness_fallback_response(
    query: str, harness_result: dict[str, Any] | None
) -> str | None:
    """Return deterministic text when the model produces no assistant content."""
    if not harness_result:
        return None
    spanish = _prefers_spanish(query)
    if harness_result.get("status") == "denied":
        return _render_harness_denial_response(query, harness_result)
    harness_type = harness_result.get("type")
    if harness_type in DETERMINISTIC_HARNESS_TYPES:
        return render_harness_response(query, harness_result)
    if harness_type == "availability_check":
        ci_name = (
            harness_result.get("ci_name")
            or harness_result.get("ci_ref")
            or harness_result.get("ci_id")
            or "CI desconocido"
        )
        status = harness_result.get("status") or "unknown"
        detail = harness_result.get("detail") or ""
        if spanish:
            return f"Resultado de disponibilidad para {ci_name}: {status}{f' ({detail})' if detail else ''}."
        return f"Availability result for {ci_name}: {status}{f' ({detail})' if detail else ''}."
    return None


def complete_chat(
    query: str,
    context: str | None,
    harness_result: dict[str, Any] | None,
    history: list[dict[str, str]] | None = None,
) -> dict[str, str]:
    settings = get_lm_studio_settings()
    if not settings.enabled:
        raise LMStudioError("LM Studio chat is disabled")
    if harness_result and (
        harness_result.get("status") == "denied"
        or harness_result.get("type") in DETERMINISTIC_HARNESS_TYPES
    ):
        deterministic_response = render_harness_response(query, harness_result)
        if deterministic_response:
            return {"content": deterministic_response, "model": DETERMINISTIC_MODEL_LABEL}
    payload = build_lm_studio_payload(query, context, harness_result, settings, history)
    response = _post_lm_studio_chat_completion(payload, settings)
    if not response.get("content", "").strip():
        fallback = synthesize_harness_fallback_response(query, harness_result)
        if fallback:
            return {"content": fallback, "model": response.get("model") or settings.model}
    return response
