"""AI Guard Service — Cooldown tracking, behavioral guards, and operation recording.

This module provides:
- Cooldown tracking (in-memory with TTL cleanup for performance)
- Operation recording to ai_operation_log table
- Behavioral guard checks (close-without-diagnostic, ack-flood, metadata-stampede)
- Bulk operation detection (>10 entities, >50 same-op/hour, >30 different-CIs/hour)
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

from models.ai_guard_models import GuardResult
from models.ai_operation_log import AIOperationLog
from postgres_db import SessionLocal


# ── Cooldown Configuration ───────────────────────────────────────────────────────

# Per-operation, per-target cooldowns in seconds
COOLDOWNS: dict[str, int] = {
    "diagnose": 300,       # 5 minutes
    "ack": 600,             # 10 minutes
    "close": 900,           # 15 minutes
    "ci_metadata_update": 120,  # 2 minutes
}

# ── In-Memory Cooldown Cache ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class CooldownEntry:
    """A single cooldown entry with TTL."""
    agent_id: str
    operation: str
    target_id: str
    expires_at: float  # monotonic seconds


class _CooldownCache:
    """Thread-safe in-memory cooldown cache with TTL cleanup.

    Cooldowns are stored in-memory (not DB) for performance.
    Expired entries are cleaned up lazily on access and during periodic sweep.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: dict[tuple[str, str, str], CooldownEntry] = {}
        self._sweep_period: float = 60.0  # seconds between sweeps
        self._last_sweep: float = time.monotonic()

    def _sweep_expired_unlocked(self) -> None:
        """Remove expired entries. Caller must hold self._lock."""
        now = time.monotonic()
        if now - self._last_sweep < self._sweep_period:
            return
        self._entries = {
            key: entry
            for key, entry in self._entries.items()
            if entry.expires_at > now
        }
        self._last_sweep = now

    def set(self, agent_id: str, operation: str, target_id: str, ttl_seconds: int) -> None:
        """Set a cooldown entry."""
        with self._lock:
            self._sweep_expired_unlocked()
            key = (agent_id, operation, target_id)
            self._entries[key] = CooldownEntry(
                agent_id=agent_id,
                operation=operation,
                target_id=target_id,
                expires_at=time.monotonic() + ttl_seconds,
            )

    def get_remaining(self, agent_id: str, operation: str, target_id: str) -> int:
        """Get remaining cooldown seconds, or 0 if none."""
        with self._lock:
            self._sweep_expired_unlocked()
            key = (agent_id, operation, target_id)
            entry = self._entries.get(key)
            if entry is None:
                return 0
            remaining = entry.expires_at - time.monotonic()
            return max(0, int(remaining))


# Singleton cooldown cache
_cooldown_cache = _CooldownCache()


# ── Cooldown Functions ──────────────────────────────────────────────────────────


def check_cooldown(ai_agent_id: str, operation: str, target_id: str) -> tuple[bool, int]:
    """Check if an operation is in cooldown for the given agent+target.

    Args:
        ai_agent_id: JWT subject of the AI agent
        operation: Operation name (diagnose, ack, close, ci_metadata_update)
        target_id: Target entity ID (e.g., event_id, ci_id)

    Returns:
        Tuple of (is_blocked: bool, cooldown_remaining_seconds: int)
        is_blocked is True when cooldown is active.
    """
    cooldown_seconds = COOLDOWNS.get(operation, 60)
    remaining = _cooldown_cache.get_remaining(ai_agent_id, operation, target_id)
    is_blocked = remaining > 0
    return is_blocked, remaining


def set_cooldown(ai_agent_id: str, operation: str, target_id: str) -> None:
    """Set a cooldown entry after a successful operation.

    Args:
        ai_agent_id: JWT subject of the AI agent
        operation: Operation performed (diagnose, ack, close, ci_metadata_update)
        target_id: Target entity ID
    """
    ttl_seconds = COOLDOWNS.get(operation, 60)
    _cooldown_cache.set(ai_agent_id, operation, target_id, ttl_seconds)


def record_operation(
    ai_persona: str,
    ai_agent_id: str,
    operation: str,
    target_type: str,
    target_id: str,
    target_name: str,
    result: str,
    blocked_reason: Optional[str] = None,
    request_context: Optional[dict] = None,
) -> None:
    """Record an AI operation to the ai_operation_log table.

    Args:
        ai_persona: AI persona (e.g., "AI_DIAGNOSTIC", "AI_OPERATOR")
        ai_agent_id: JWT subject identifying the agent
        operation: Operation performed (diagnose, ack, close, ci_metadata_update)
        target_type: Type of target (event, ci, metric)
        target_id: ID of the target entity
        target_name: Human-readable name of target
        result: Operation result (success, blocked, failed, escalated)
        blocked_reason: Reason if result is blocked
        request_context: Additional context (IP, user agent, etc.)
    """
    db = SessionLocal()
    try:
        entry = AIOperationLog(
            ai_persona=ai_persona,
            ai_agent_id=ai_agent_id,
            operation=operation,
            target_type=target_type,
            target_id=target_id,
            target_name=target_name,
            result=result,
            blocked_reason=blocked_reason,
            request_context=request_context or {},
        )
        db.add(entry)
        if result == "success":
            try:
                set_cooldown(ai_agent_id, operation, target_id)
            except Exception:
                pass  # cooldown is best-effort; don't break the operation
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ── Behavioral Guards ───────────────────────────────────────────────────────────


def check_behavioral_guards(
    ai_agent_id: str, operation: str, target_id: str
) -> GuardResult:
    """Check behavioral guard rules for an AI agent operation.

    Guards checked:
    - Close without diagnostic: >3 closes/hour on CIs with open events → BLOCK
    - Ack flood: >20 acks/10min without any diagnostic → BLOCK
    - Metadata stampede: >5 CI updates/5min → BLOCK

    Args:
        ai_agent_id: JWT subject of the AI agent
        operation: Operation being attempted
        target_id: Target entity ID

    Returns:
        GuardResult with allowed=True if operation is permitted
    """
    now = datetime.now(timezone.utc)
    cutoff_1h = now.replace(second=0, microsecond=0)
    cutoff_10m = datetime.fromtimestamp(now.timestamp() - 600, tz=timezone.utc)
    cutoff_5m = datetime.fromtimestamp(now.timestamp() - 300, tz=timezone.utc)

    db = SessionLocal()
    try:
        # Check close-without-diagnostic guard
        if operation == "close":
            # Count closes by this agent in the last hour
            closes_count = db.execute(
                text("""
                    SELECT COUNT(*) as cnt FROM ai_operation_log
                    WHERE ai_agent_id = :agent_id
                      AND operation = 'close'
                      AND target_id = :target_id
                      AND timestamp > :cutoff
                      AND result = 'success'
                """),
                {"agent_id": ai_agent_id, "target_id": target_id, "cutoff": cutoff_1h},
            ).scalar() or 0

            if closes_count > 3:
                # Check if there are any diagnoses by this agent in the same period
                has_diagnostic = db.execute(
                    text("""
                        SELECT 1 FROM ai_operation_log
                        WHERE ai_agent_id = :agent_id
                          AND operation = 'diagnose'
                          AND timestamp > :cutoff
                        LIMIT 1
                    """),
                    {"agent_id": ai_agent_id, "cutoff": cutoff_1h},
                ).scalar_one_or_none()

                if not has_diagnostic:
                    return GuardResult(
                        allowed=False,
                        reason="Close without diagnostic: >3 closes/hour without any diagnostic",
                    )

        # Check ack flood guard
        if operation == "ack":
            ack_count = db.execute(
                text("""
                    SELECT COUNT(*) as cnt FROM ai_operation_log
                    WHERE ai_agent_id = :agent_id
                      AND operation = 'ack'
                      AND timestamp > :cutoff
                      AND result = 'success'
                """),
                {"agent_id": ai_agent_id, "cutoff": cutoff_10m},
            ).scalar() or 0

            if ack_count > 20:
                # Check for at least one diagnostic in the same window
                has_diagnostic = db.execute(
                    text("""
                        SELECT 1 FROM ai_operation_log
                        WHERE ai_agent_id = :agent_id
                          AND operation = 'diagnose'
                          AND timestamp > :cutoff
                        LIMIT 1
                    """),
                    {"agent_id": ai_agent_id, "cutoff": cutoff_10m},
                ).scalar_one_or_none()

                if not has_diagnostic:
                    return GuardResult(
                        allowed=False,
                        reason="Ack flood: >20 acks/10min without any diagnostic",
                    )

        # Check metadata stampede guard
        if operation == "ci_metadata_update":
            update_count = db.execute(
                text("""
                    SELECT COUNT(*) as cnt FROM ai_operation_log
                    WHERE ai_agent_id = :agent_id
                      AND operation = 'ci_metadata_update'
                      AND timestamp > :cutoff
                      AND result = 'success'
                """),
                {"agent_id": ai_agent_id, "cutoff": cutoff_5m},
            ).scalar() or 0

            if update_count > 5:
                return GuardResult(
                    allowed=False,
                    reason="Metadata stampede: >5 CI updates/5min",
                )

        return GuardResult(allowed=True)

    finally:
        db.close()


def check_bulk_detection(
    ai_agent_id: str, operation: str, target_ids: list[str]
) -> GuardResult:
    """Check for bulk operations that require special handling.

    Guards checked:
    - >10 entities per request → BLOCK
    - >50 same op type/hour → require approval (not blocked, but flagged)
    - >30 different CIs/hour → require approval (not blocked, but flagged)

    Args:
        ai_agent_id: JWT subject of the AI agent
        operation: Operation being attempted
        target_ids: List of target entity IDs in this request

    Returns:
        GuardResult with allowed=True if operation is permitted.
        escalation_required=True indicates need for human approval.
    """
    # Guard: >10 entities per request
    if len(target_ids) > 10:
        return GuardResult(
            allowed=False,
            reason=f"Bulk operation too large: {len(target_ids)} entities (max 10)",
        )

    now = datetime.now(timezone.utc)
    cutoff_1h = now.replace(second=0, microsecond=0)

    db = SessionLocal()
    try:
        # Check >50 same op type/hour
        same_op_count = db.execute(
            text("""
                SELECT COUNT(*) as cnt FROM ai_operation_log
                WHERE ai_agent_id = :agent_id
                  AND operation = :operation
                  AND timestamp > :cutoff
            """),
            {"agent_id": ai_agent_id, "operation": operation, "cutoff": cutoff_1h},
        ).scalar() or 0

        if same_op_count >= 50:
            return GuardResult(
                allowed=True,
                reason=f"High volume: {same_op_count} same operations in the last hour",
                escalation_required=True,
            )

        # Check >30 different CIs/hour
        if len(target_ids) > 0:
            target_type = "ci"  # assume CI for bulk check
            diff_ci_count = db.execute(
                text("""
                    SELECT COUNT(DISTINCT target_id) as cnt FROM ai_operation_log
                    WHERE ai_agent_id = :agent_id
                      AND target_type = :target_type
                      AND timestamp > :cutoff
                """),
                {"agent_id": ai_agent_id, "target_type": target_type, "cutoff": cutoff_1h},
            ).scalar() or 0

            if diff_ci_count >= 30:
                return GuardResult(
                    allowed=True,
                    reason=f"High CI diversity: {diff_ci_count} different CIs in the last hour",
                    escalation_required=True,
                )

        return GuardResult(allowed=True)

    finally:
        db.close()


def check_all_guards(
    ai_agent_id: str,
    operation: str,
    target_ids: list[str],
) -> GuardResult:
    """Unified guard check entry point.

    Calls cooldown, behavioral, and bulk detection guards in sequence.
    Returns aggregate GuardResult. Short-circuits on first blocking result.

    Args:
        ai_agent_id: JWT subject of the AI agent
        operation: Operation being attempted (diagnose, ack, close, ci_metadata_update)
        target_ids: List of target entity IDs (used for cooldown, behavioral, bulk checks)

    Returns:
        GuardResult with allowed=True if all guards pass
    """
    # 1. Cooldown check (use first target_id for single-target operations)
    if not target_ids:
        target_id = ""
    else:
        target_id = target_ids[0]
    is_blocked, remaining = check_cooldown(ai_agent_id, operation, target_id)
    if is_blocked:
        return GuardResult(
            allowed=False,
            reason=f"Cooldown active",
            cooldown_remaining_seconds=remaining,
        )

    # 2. Behavioral guards (single target)
    behavioral_result = check_behavioral_guards(ai_agent_id, operation, target_id)
    if not behavioral_result.allowed:
        return behavioral_result

    # 3. Bulk detection (full list)
    bulk_result = check_bulk_detection(ai_agent_id, operation, target_ids)
    return bulk_result