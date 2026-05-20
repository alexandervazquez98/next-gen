"""
CLI Router — handles CLI query testing endpoint.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, Literal
import os

from services.auth_service import get_current_active_user
from models.user import User, UserPermission

router = APIRouter(
    prefix="/cli",
    tags=["CLI"],
    responses={404: {"description": "Not found"}},
)


class CLITestRequest(BaseModel):
    """Request model for testing a CLI query against a network device."""

    ip: str
    cli_protocol: Literal["SSH", "Telnet"] = "SSH"
    username: str
    password: str
    escalation_script: Optional[str] = None
    cli_command: str
    cli_value_extractor: str
    cli_timeout: int = 30


class CLITestResponse(BaseModel):
    """Response model for CLI test query results."""

    success: bool
    raw_output: Optional[str] = None
    extracted_value: Optional[str] = None
    numeric_value: Optional[float] = None
    status: str


@router.post("/test", response_model=CLITestResponse)
async def test_cli_query(
    req: CLITestRequest,
    current_user: User = Depends(get_current_active_user),
):
    """
    Execute a CLI command via SSH/Telnet on a target device and return
    raw output along with regex extraction results.

    Requires CI_EDIT permission.
    """
    if not check_permission(UserPermission.CI_EDIT, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to test CLI queries")

    # Import CLI engine functions at request time to avoid import-time side effects
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'engines'))

    try:
        from cli_worker import fetch_cli_value, extract_regex_value
    except ImportError:
        return CLITestResponse(
            success=False,
            raw_output=None,
            extracted_value=None,
            numeric_value=None,
            status="CLI_ENGINE_NOT_AVAILABLE — paramiko may not be installed",
        )

    node_dict = {'ip': req.ip, 'label': req.ip}

    metric_def = {
        'cli_command': req.cli_command,
        'cli_target': '',
        'cli_credential_ref': None,
        'cli_escalation_script': req.escalation_script,
        'cli_protocol': req.cli_protocol,
        'cli_timeout': req.cli_timeout,
    }

    # Inject credentials via env vars for resolve_credential()
    had_old_user = 'CLI_TEST_USER' in os.environ
    had_old_pass = 'CLI_TEST_PASS' in os.environ
    old_user = os.environ.get('CLI_TEST_USER')
    old_pass = os.environ.get('CLI_TEST_PASS')
    os.environ['CLI_TEST_USER'] = req.username
    os.environ['CLI_TEST_PASS'] = req.password

    try:
        raw_output, error = fetch_cli_value(metric_def, node_dict)
    finally:
        # Restore env
        if had_old_user:
            os.environ['CLI_TEST_USER'] = old_user if old_user is not None else ''
        else:
            os.environ.pop('CLI_TEST_USER', None)
        if had_old_pass:
            os.environ['CLI_TEST_PASS'] = old_pass if old_pass is not None else ''
        else:
            os.environ.pop('CLI_TEST_PASS', None)

    if error:
        return CLITestResponse(
            success=False,
            raw_output=None,
            extracted_value=None,
            numeric_value=None,
            status=f"CONNECTION_ERROR: {error}",
        )

    if not raw_output:
        return CLITestResponse(
            success=False,
            raw_output=None,
            extracted_value=None,
            numeric_value=None,
            status="EMPTY_OUTPUT",
        )

    # Apply regex extractor
    extractor = req.cli_value_extractor or 'regex:(.*)'
    extracted_value, numeric_value = extract_regex_value(raw_output, extractor)

    # NaN check for numeric_value display
    import math
    display_numeric = None
    if numeric_value is not None and not (isinstance(numeric_value, float) and math.isnan(numeric_value)):
        display_numeric = numeric_value

    return CLITestResponse(
        success=True,
        raw_output=raw_output,
        extracted_value=extracted_value,
        numeric_value=display_numeric,
        status="SUCCESS",
    )


def check_permission(permission: UserPermission, user: User) -> bool:
    """Check if user has the required permission."""
    return permission in user.permissions or user.role == "ADMIN"