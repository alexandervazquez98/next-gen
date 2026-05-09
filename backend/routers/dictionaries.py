"""
Dictionary Router — CRUD endpoints for MetricDictionary nodes.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

from models.core import MetricDictionary, AppliedDictionary, DictionaryCreate, DictionaryUpdate
from services import dictionary_service
import services.metric_service as metric_service
from services.auth_service import get_current_active_user, check_permission
from models.user import User, UserPermission

router = APIRouter(
    prefix="/dictionaries",
    tags=["Dictionaries"],
    responses={404: {"description": "Not found"}},
)


def _require_editor(current_user: User):
    if not check_permission(UserPermission.CI_EDIT, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to manage dictionaries")


@router.get("", response_model=List[Dict[str, Any]])
async def get_dictionaries(
    current_user: User = Depends(get_current_active_user),
):
    """
    List all MetricDictionaries.
    """
    return dictionary_service.list_dictionaries()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_dictionary(
    data: DictionaryCreate,
    current_user: User = Depends(get_current_active_user),
):
    """
    Create a new MetricDictionary.
    brand and model are MANDATORY.
    metric_ids must reference existing MetricDef nodes (validated).
    Raises 409 if brand+model pair already exists.
    Raises 422 if any metric_id does not exist.
    """
    _require_editor(current_user)

    # Validate metric_ids exist
    valid, invalid = dictionary_service.validate_metric_ids(data.metric_ids)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid metric_ids: {invalid}",
        )

    try:
        result = dictionary_service.create_dictionary(data.model_dump())
        return {"message": "Dictionary created", "id": result["id"]}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.get("/{dictionary_id}", response_model=Dict[str, Any])
async def get_dictionary(
    dictionary_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """
    Get a single MetricDictionary by id, including its metric_ids.
    """
    result = dictionary_service.get_dictionary(dictionary_id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dictionary not found")
    return result


@router.get("/{dictionary_id}/preview-ci")
async def preview_ci(
    dictionary_id: str,
    ci_id: str = Query(..., description="The CI identifier to preview"),
    current_user: User = Depends(get_current_active_user),
):
    """
    Preview what metrics would apply if a CI is matched to a dictionary.
    Checks if CI's brand+model matches the dictionary's brand+model.
    Returns match result with applicable metrics count.
    """
    # Get dictionary
    dictionary = dictionary_service.get_dictionary(dictionary_id)
    if not dictionary:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dictionary not found")

    # Get CI node (brand, model)
    driver = dictionary_service._get_driver()
    with driver.session() as session:
        result = session.run(
            "MATCH (n:CI {id: $ci_id}) RETURN n.brand AS brand, n.model AS model",
            ci_id=ci_id,
        ).single()

    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CI not found")

    ci_brand = (result["brand"] or "").strip().lower()
    ci_model = (result["model"] or "").strip().lower()
    dict_brand = dictionary["brand"].strip().lower()
    dict_model = dictionary["model"].strip().lower()

    matches = ci_brand == dict_brand and ci_model == dict_model

    applicable_count = 0
    if matches:
        applicable_count = metric_service.get_applicable_metrics(ci_id)
        applicable_count = len(applicable_count)

    return {
        "matches": matches,
        "applicable_metrics_count": applicable_count,
        "ci_brand": result["brand"],
        "ci_model": result["model"],
        "dictionary_brand": dictionary["brand"],
        "dictionary_model": dictionary["model"],
    }


@router.put("/{dictionary_id}")
async def update_dictionary(
    dictionary_id: str,
    data: DictionaryUpdate,
    current_user: User = Depends(get_current_active_user),
):
    """
    Update a MetricDictionary.
    All fields optional — only provided fields are updated.
    metric_ids REPLACE existing (not merge).
    Raises 409 if new brand+model conflicts with another dictionary.
    Raises 422 if any metric_id does not exist.
    """
    _require_editor(current_user)

    existing = dictionary_service.get_dictionary(dictionary_id)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dictionary not found")

    update_data = {k: v for k, v in data.model_dump().items() if v is not None}

    # Validate metric_ids if being updated
    if "metric_ids" in update_data:
        valid, invalid = dictionary_service.validate_metric_ids(update_data["metric_ids"])
        if not valid:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid metric_ids: {invalid}",
            )

    try:
        result = dictionary_service.update_dictionary(dictionary_id, update_data)
        if not result:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dictionary not found")
        return {"message": "Dictionary updated"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


class ApplyRequest(BaseModel):
    ci_ids: List[str] = []
    dry_run: bool = False


class ApplyResponse(BaseModel):
    applied_count: int
    skipped_count: int
    message: str


@router.get("/{dictionary_id}/target-cis", response_model=List[Dict[str, Any]])
async def get_target_cis(
    dictionary_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """
    Return CIs where brand and model exactly match the dictionary's brand+model.
    Case-insensitive comparison. Returns [{id, name, ip, brand, model, location_name}].
    """
    try:
        return dictionary_service.get_target_cis(dictionary_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/{dictionary_id}/apply", response_model=ApplyResponse)
async def apply_dictionary(
    dictionary_id: str,
    body: ApplyRequest,
    current_user: User = Depends(get_current_active_user),
):
    """
    Apply a dictionary to specified CI IDs.
    Creates/updates AppliedDictionary nodes per CI (idempotent).
    If dry_run=true, returns count without persisting.
    Raises 404 if dictionary not found.
    """
    _require_editor(current_user)

    try:
        result = dictionary_service.apply_dictionary(
            dictionary_id,
            body.ci_ids,
            dry_run=body.dry_run,
        )
        return ApplyResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.delete("/{dictionary_id}")
async def delete_dictionary(
    dictionary_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """
    Delete a MetricDictionary and cascade-delete all AppliedDictionary nodes referencing it.
    """
    _require_editor(current_user)

    deleted = dictionary_service.delete_dictionary(dictionary_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dictionary not found")
    return {"message": "Dictionary deleted"}