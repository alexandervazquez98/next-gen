"""
CI Dictionary Exclusion Router — Per-CI exclusion endpoints.
Handles AppliedDictionary customization at CI level.
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from models.user import User
from pydantic import BaseModel
from services import dictionary_service
from services.auth_service import get_current_active_user

router = APIRouter(
    prefix="/cis",
    tags=["CI-Dictionary"],
    responses={404: {"description": "Not found"}},
)


def _require_editor(current_user: User):
    # Block AI agents from dictionary exclusion management
    if current_user.role and str(current_user.role).startswith("AI_"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="AI agents cannot manage CI dictionary exclusions",
        )
    if not current_user.role == "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to manage CI dictionary exclusions",
        )


class ExclusionUpdateRequest(BaseModel):
    excluded_metrics: list[str] | None = None
    extra_metrics: list[str] | None = None


class AppliedDictionaryResponse(BaseModel):
    dictionary_id: str
    dictionary_name: str
    dictionary_brand: str
    dictionary_model: str
    dictionary_metric_ids: list[str]
    excluded_metrics: list[str]
    extra_metrics: list[str]
    applied_at: str | None


@router.get("/{ci_id}/applied-dictionary", response_model=Optional[dict[str, Any]])  # noqa: UP045
async def get_applied_dictionary(
    ci_id: str,
    current_user: User = Depends(get_current_active_user),  # noqa: B008
):
    """
    Get the AppliedDictionary for a CI with full details.
    Returns dictionary_id, dictionary_name, excluded_metrics, extra_metrics, applied_at.
    Returns 404 if no dictionary is applied to this CI.
    C4 fix: requires authentication and non-AI agent to read exclusion data.
    """
    # C4 fix: block AI agents from reading CI exclusion data
    if current_user.role and str(current_user.role).startswith("AI_"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="AI agents cannot read CI dictionary exclusion data",
        )
    result = dictionary_service.get_applied_dictionary(ci_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No dictionary applied to CI '{ci_id}'",
        )
    return result


@router.put("/{ci_id}/dictionary-exclusions", response_model=dict[str, Any])
async def update_dictionary_exclusions(
    ci_id: str,
    body: ExclusionUpdateRequest,
    current_user: User = Depends(get_current_active_user),  # noqa: B008
):
    """
    Update excluded_metrics and/or extra_metrics for a CI's AppliedDictionary.
    Both arrays REPLACE existing values (not merge).
    Raises 404 if no dictionary is applied to this CI.
    Raises 422 if extra_metrics contains non-existent MetricDef ids.
    """
    _require_editor(current_user)

    try:
        result = dictionary_service.update_ci_exclusions(
            ci_id,
            excluded_metrics=body.excluded_metrics,
            extra_metrics=body.extra_metrics,
        )
        return result
    except ValueError as e:
        err_str = str(e)
        if "No AppliedDictionary found" in err_str:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err_str)  # noqa: B904
        if "Invalid extra_metric_ids" in err_str:
            raise HTTPException(  # noqa: B904
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=err_str
            )
        raise HTTPException(status_code=status.HTTP_400, detail=err_str)  # noqa: B904


@router.delete("/{ci_id}/applied-dictionary")
async def remove_applied_dictionary(
    ci_id: str,
    current_user: User = Depends(get_current_active_user),  # noqa: B008
):
    """
    Remove the AppliedDictionary from a CI (un-apply dictionary).
    Does NOT delete the MetricDictionary or MetricDef nodes.
    """
    _require_editor(current_user)

    removed = dictionary_service.remove_applied_dictionary(ci_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No dictionary applied to CI '{ci_id}'",
        )
    return {"message": "Dictionary removed from CI"}
