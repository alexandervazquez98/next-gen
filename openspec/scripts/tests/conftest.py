"""Conftest for openspec/scripts/tests/.

REQ-010 guard: any string in a captured fixture that looks like a CI ID must
match the synthetic pattern ``ci-test-ap-orphan-NNN`` or a UUID-shaped opaque
string. Real names, IPs, sites, or anything else that looks CI-ID-shaped are
rejected at test teardown so a fixture leak cannot reach CI.
"""

import re

import pytest

SYNTHETIC_ID_RE = re.compile(r"^ci-test-ap-orphan-\d{3,}$")
UUID_SHAPE_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

_SUSPICIOUS_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")
_SUSPICIOUS_IPV4_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")


def is_valid_opaque_ci_id(value):
    """Return True iff ``value`` is a synthetic or UUID-shaped opaque CI ID."""
    if not isinstance(value, str):
        return False
    return bool(SYNTHETIC_ID_RE.match(value) or UUID_SHAPE_RE.match(value))


@pytest.fixture(autouse=True)
def validate_fixture_ids(request):
    """Reject fixture values that look like real customer identifiers."""
    yield
    # Snapshot captured fixtures before teardown — re-requesting after the
    # fixture has been torn down raises AssertionError, which we don't want
    # masking the test's actual outcome.
    captured = {}
    for fixture_name in getattr(request, "fixturenames", []):
        cached = getattr(request, "_fixture_values", None)
        if cached is None or fixture_name not in cached:
            continue
        captured[fixture_name] = cached[fixture_name]
    for fixture_name, value in captured.items():
        _walk_and_check(fixture_name, value)


def _walk_and_check(label, value):
    if isinstance(value, str):
        _check_string(label, value)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _walk_and_check(f"{label}[{key!r}]", item)
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for idx, item in enumerate(value):
            _walk_and_check(f"{label}[{idx}]", item)


def _check_string(label, value):
    if not value:
        return
    if is_valid_opaque_ci_id(value):
        return
    if _SUSPICIOUS_NAME_RE.match(value):
        raise AssertionError(
            f"fixture {label!r} contains suspicious uppercase token: {value!r}"
        )
    if _SUSPICIOUS_IPV4_RE.match(value):
        raise AssertionError(
            f"fixture {label!r} contains IPv4-shaped value: {value!r}"
        )
