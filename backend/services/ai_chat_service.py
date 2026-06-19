from __future__ import annotations

import ipaddress
import json
import re
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import LMStudioSettings, get_lm_studio_settings
from models.ai_chat import AIChatMessage


FALLBACK_SYSTEM_PROMPT = (
    "You are NEX-GEN Assistant, a concise and technical assistant for CMDB, "
    "monitoring, ITSM, and AIOps operations. Use only provided operational "
    "context. Do not invent tool results."
)
AI_IDENTITY_DIR = Path(__file__).resolve().parents[1] / "ai" / "identity"
PROMPT_SOURCE_FILES = ("Soul.md", "scope.md", "context-policy.md")
MAX_SYSTEM_PROMPT_CHARS = 6_000

MAX_QUERY_CHARS = 2_000
MAX_CONTEXT_CHARS = 4_000
_SAFE_HOST_RE = re.compile(r"^[A-Za-z0-9.-]{1,253}$")


class LMStudioError(Exception):
    """LM Studio returned an unusable response or could not be reached."""


class LMStudioTimeoutError(LMStudioError):
    """LM Studio did not answer within the configured timeout."""


def load_system_prompt() -> str:
    """Compose the bounded runtime system prompt from backend-owned sources."""
    sections: list[str] = []
    try:
        for filename in PROMPT_SOURCE_FILES:
            source = AI_IDENTITY_DIR / filename
            text = source.read_text(encoding="utf-8").strip()
            if not text:
                return FALLBACK_SYSTEM_PROMPT
            sections.append(f"## {filename}\n{text}")
    except OSError:
        return FALLBACK_SYSTEM_PROMPT

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
) -> dict[str, Any]:
    """Build a bounded OpenAI-compatible chat completion payload."""
    trimmed_query = query[:MAX_QUERY_CHARS]
    trimmed_context = (context or "")[:MAX_CONTEXT_CHARS]
    user_content = f"User question:\n{trimmed_query}"
    if trimmed_context:
        user_content = f"{user_content}\n\nOperational context:\n{trimmed_context}"
    if harness_result:
        user_content += "\n\nHarness result:\n" + json.dumps(harness_result, sort_keys=True)

    return {
        "model": settings.model,
        "messages": [
            {"role": "system", "content": load_system_prompt()},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.2,
        "stream": False,
    }


def _post_lm_studio_chat_completion(payload: dict[str, Any], settings: LMStudioSettings) -> dict[str, str]:
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
        raise LMStudioTimeoutError("LM Studio request timed out") from exc
    except urllib.error.URLError as exc:
        if isinstance(getattr(exc, "reason", None), TimeoutError):
            raise LMStudioTimeoutError("LM Studio request timed out") from exc
        raise LMStudioError("LM Studio is unavailable") from exc
    except Exception as exc:
        raise LMStudioError("LM Studio response could not be parsed") from exc

    try:
        message = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
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


def maybe_run_harness(intent: Any, neo4j_driver) -> dict[str, Any] | None:
    if not intent or getattr(intent, "type", None) != "availability_check":
        return None

    ci_ref = str(getattr(intent, "ci_ref", "")).strip()
    ci = resolve_ci_for_harness(neo4j_driver, ci_ref)
    if ci is None:
        return {"type": "availability_check", "ci_ref": ci_ref, "status": "ci_not_found"}

    try:
        target = resolve_ping_target(ci)
        return run_bounded_ping(target).to_metadata(ci)
    except ValueError as exc:
        return {
            "type": "availability_check",
            "ci_id": ci.get("id"),
            "ci_name": ci.get("name"),
            "status": "invalid_target",
            "detail": str(exc),
        }


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


def complete_chat(query: str, context: str | None, harness_result: dict[str, Any] | None) -> dict[str, str]:
    settings = get_lm_studio_settings()
    if not settings.enabled:
        raise LMStudioError("LM Studio chat is disabled")
    payload = build_lm_studio_payload(query, context, harness_result, settings)
    return _post_lm_studio_chat_completion(payload, settings)
