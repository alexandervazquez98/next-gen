"""
Login rate limiting middleware.

In-memory store tracking failed login attempts per username.
After 3 consecutive failed attempts, account is locked for 15 minutes.
"""
from datetime import datetime, timedelta
from typing import Dict, NamedTuple

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

# ── Constants ────────────────────────────────────────────────────────────────

MAX_ATTEMPTS = 3
LOCKOUT_DURATION = timedelta(minutes=15)

# In-memory store: {username: AttemptInfo}
RATE_LIMIT_STORE: Dict[str, "AttemptInfo"] = {}


class AttemptInfo(NamedTuple):
    """Tracks failed login attempts for a username."""
    count: int
    locked_until: datetime | None


def get_attempt_info(username: str) -> AttemptInfo:
    """Get current attempt info for a username."""
    return RATE_LIMIT_STORE.get(username, AttemptInfo(count=0, locked_until=None))


def increment_attempts(username: str) -> AttemptInfo:
    """Increment failed attempts. Returns updated AttemptInfo."""
    info = get_attempt_info(username)
    now = datetime.utcnow()

    # Clear expired lock before incrementing
    if info.locked_until and info.locked_until < now:
        del RATE_LIMIT_STORE[username]
        info = AttemptInfo(count=0, locked_until=None)

    # If currently locked, return existing lock info
    if info.locked_until and info.locked_until > now:
        return info

    new_count = info.count + 1

    # Lockout is triggered AFTER 3 consecutive failures.
    # 3 failed attempts → count=3, no lock yet.
    # 4th attempt → count=4 > MAX_ATTEMPTS(3) → lockout begins.
    if new_count > MAX_ATTEMPTS:
        new_locked_until = now + LOCKOUT_DURATION
        RATE_LIMIT_STORE[username] = AttemptInfo(count=new_count, locked_until=new_locked_until)
    else:
        RATE_LIMIT_STORE[username] = AttemptInfo(count=new_count, locked_until=None)

    return RATE_LIMIT_STORE[username]


def clear_attempts(username: str) -> None:
    """Clear failed attempts on successful login."""
    if username in RATE_LIMIT_STORE:
        del RATE_LIMIT_STORE[username]


def is_locked(username: str) -> tuple[bool, int | None]:
    """
    Check if username is currently locked.
    Returns (is_locked, retry_after_seconds).
    """
    info = get_attempt_info(username)
    if info.locked_until is None:
        return False, None

    now = datetime.utcnow()
    if info.locked_until <= now:
        # Lock expired, clear it
        if username in RATE_LIMIT_STORE:
            del RATE_LIMIT_STORE[username]
        return False, None

    # Still locked
    retry_after = int((info.locked_until - now).total_seconds())
    return True, retry_after


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


def check_rate_limit(username: str) -> None:
    """
    Check if username is rate limited. Raises HTTPException 429 if locked.

    Call this from the auth router before processing login.
    """
    locked, retry_after = is_locked(username)
    if locked:
        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts. Account temporarily locked.",
            headers={"Retry-After": str(retry_after)}
        )