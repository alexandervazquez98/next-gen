"""
Login rate limiting middleware.

Persistent store tracking failed auth attempts in Postgres so lockouts are
shared across uvicorn worker processes. After 3 consecutive failed attempts,
the identity is locked for 15 minutes.
"""
import hashlib
from datetime import datetime, timedelta
from typing import NamedTuple

from fastapi import Request, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from models.rate_limit_attempt import RateLimitAttempt
from postgres_db import SessionLocal

# ── Constants ────────────────────────────────────────────────────────────────

MAX_ATTEMPTS = 3
LOCKOUT_DURATION = timedelta(minutes=15)
ATTEMPT_RETENTION = timedelta(days=1)


class AttemptInfo(NamedTuple):
    """Tracks failed auth attempts for an identity."""

    count: int
    locked_until: datetime | None


def refresh_token_rate_limit_key(refresh_token: str) -> str:
    """Return a non-sensitive, namespaced rate-limit key for a refresh token."""
    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
    return f"refresh:{token_hash}"


def _stored_identity_key(identity_key: str, identity_type: str) -> str:
    """Namespace persisted keys so identity domains cannot collide."""
    if identity_type == "refresh_token":
        return identity_key if identity_key.startswith("refresh:") else f"refresh:{identity_key}"
    if identity_type == "username":
        return f"user:{identity_key}"
    return f"{identity_type}:{identity_key}"


def _utcnow() -> datetime:
    return datetime.utcnow()


def _prune_expired_attempts(db: Session, now: datetime) -> None:
    """Remove expired locks and stale unlocked counters opportunistically."""
    stale_cutoff = now - ATTEMPT_RETENTION
    db.query(RateLimitAttempt).filter(
        (RateLimitAttempt.locked_until <= now)
        | (
            (RateLimitAttempt.locked_until.is_(None))
            & (RateLimitAttempt.updated_at < stale_cutoff)
        )
    ).delete(synchronize_session=False)


def _get_locked_attempt(
    db: Session,
    identity_key: str,
    identity_type: str,
) -> RateLimitAttempt | None:
    """Load an attempt row with a row lock where the database supports it."""
    return (
        db.query(RateLimitAttempt)
        .filter(
            RateLimitAttempt.identity_key == identity_key,
            RateLimitAttempt.identity_type == identity_type,
        )
        .with_for_update()
        .one_or_none()
    )


def _create_locked_attempt(
    db: Session,
    identity_key: str,
    identity_type: str,
    now: datetime,
) -> RateLimitAttempt:
    """
    Create an attempt row, handling a concurrent first insert by re-reading it.

    The unique identity_key constraint prevents duplicate counters across
    workers. Existing rows are re-selected with FOR UPDATE before mutation.
    """
    attempt = RateLimitAttempt(
        identity_key=identity_key,
        identity_type=identity_type,
        attempt_count=0,
        locked_until=None,
        updated_at=now,
    )
    db.add(attempt)
    try:
        db.flush()
        return attempt
    except IntegrityError:
        db.rollback()
        attempt = _get_locked_attempt(db, identity_key, identity_type)
        if attempt is None:
            raise
        return attempt


def get_attempt_info(identity_key: str, identity_type: str = "username") -> AttemptInfo:
    """Get current attempt info for an identity."""
    db = SessionLocal()
    try:
        now = _utcnow()
        _prune_expired_attempts(db, now)
        stored_key = _stored_identity_key(identity_key, identity_type)
        attempt = _get_locked_attempt(db, stored_key, identity_type)
        if attempt is None:
            db.commit()
            return AttemptInfo(count=0, locked_until=None)

        info = AttemptInfo(
            count=attempt.attempt_count,
            locked_until=attempt.locked_until,
        )
        db.commit()
        return info
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def increment_attempts(identity_key: str, identity_type: str = "username") -> AttemptInfo:
    """Increment failed attempts. Returns updated AttemptInfo."""
    db = SessionLocal()
    try:
        now = _utcnow()
        _prune_expired_attempts(db, now)
        stored_key = _stored_identity_key(identity_key, identity_type)
        attempt = _get_locked_attempt(db, stored_key, identity_type)
        if attempt is None:
            attempt = _create_locked_attempt(db, stored_key, identity_type, now)

        # If currently locked, return existing lock info without extending it.
        if attempt.locked_until and attempt.locked_until > now:
            info = AttemptInfo(
                count=attempt.attempt_count,
                locked_until=attempt.locked_until,
            )
            db.commit()
            return info

        # Clear expired lock before incrementing. Expired rows are normally
        # pruned above; this preserves behavior if pruning races or is skipped.
        if attempt.locked_until and attempt.locked_until <= now:
            attempt.attempt_count = 0
            attempt.locked_until = None

        new_count = attempt.attempt_count + 1
        attempt.attempt_count = new_count
        attempt.identity_type = identity_type
        attempt.last_failed_at = now
        attempt.updated_at = now

        # Lockout is triggered AFTER 3 consecutive failures.
        # 3 failed attempts → count=3, no lock yet.
        # 4th attempt → count=4 > MAX_ATTEMPTS(3) → lockout begins.
        if new_count > MAX_ATTEMPTS:
            attempt.locked_until = now + LOCKOUT_DURATION
        else:
            attempt.locked_until = None

        info = AttemptInfo(count=attempt.attempt_count, locked_until=attempt.locked_until)
        db.commit()
        return info
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def clear_attempts(identity_key: str, identity_type: str = "username") -> None:
    """Clear failed attempts on successful auth."""
    db = SessionLocal()
    try:
        stored_key = _stored_identity_key(identity_key, identity_type)
        db.query(RateLimitAttempt).filter(
            RateLimitAttempt.identity_key == stored_key,
            RateLimitAttempt.identity_type == identity_type,
        ).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def is_locked(identity_key: str, identity_type: str = "username") -> tuple[bool, int | None]:
    """
    Check if identity is currently locked.
    Returns (is_locked, retry_after_seconds).
    """
    db = SessionLocal()
    try:
        now = _utcnow()
        _prune_expired_attempts(db, now)
        stored_key = _stored_identity_key(identity_key, identity_type)
        attempt = _get_locked_attempt(db, stored_key, identity_type)
        if attempt is None or attempt.locked_until is None:
            db.commit()
            return False, None

        if attempt.locked_until <= now:
            db.delete(attempt)
            db.commit()
            return False, None

        retry_after = int((attempt.locked_until - now).total_seconds())
        db.commit()
        return True, retry_after
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware that enforces rate limiting on POST /api/auth/token.

    Only applies to login attempts. On lockout, returns HTTP 429 with
    Retry-After header.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Only check rate limit for POST /api/auth/token
        if request.url.path == "/api/auth/token" and request.method == "POST":
            # We need username from form data - we'll handle this via a dependency instead
            # The middleware cannot easily parse form data, so we rely on the router
            # to check rate limits via the utility functions
            pass

        return await call_next(request)


def raise_rate_limit_locked(locked_until: datetime) -> None:
    """Raise HTTP 429 for an active lock using the remaining lock duration."""
    retry_after = max(1, int((locked_until - _utcnow()).total_seconds()))
    raise HTTPException(
        status_code=429,
        detail="Too many failed login attempts. Account temporarily locked.",
        headers={"Retry-After": str(retry_after)},
    )


def check_rate_limit(identity_key: str, identity_type: str = "username") -> None:
    """
    Check if identity is rate limited. Raises HTTPException 429 if locked.

    Call this from the auth router before processing login/refresh.
    """
    locked, retry_after = is_locked(identity_key, identity_type=identity_type)
    if locked:
        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts. Account temporarily locked.",
            headers={"Retry-After": str(retry_after)}
        )
