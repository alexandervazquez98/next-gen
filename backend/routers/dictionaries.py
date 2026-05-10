"""
Dictionary Router — CRUD endpoints for MetricDictionary nodes.
"""
import csv
import io
from fastapi import APIRouter, Depends, HTTPException, Query, status, UploadFile, Form
from fastapi.responses import StreamingResponse
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


@router.get("/template-csv")
async def get_template_csv(
    current_user: User = Depends(get_current_active_user),
):
    """
    Download a CSV template pre-populated with distinct brand+model pairs
    from existing CI nodes, plus one example row.
    """
    brands_models = dictionary_service.get_template_brands_models()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["brand", "model", "name", "polling_interval", "metric_ids"])

    # One example row (user can remove)
    writer.writerow(["ExampleBrand", "ExampleModel", "My Dictionary Name", "60", "cpu-usage,mem-used"])

    # Pre-populate with existing brand+model pairs
    for brand, model in brands_models:
        writer.writerow([brand, model, "", "60", ""])

    output.seek(0)
    csv_content = output.getvalue()

    return StreamingResponse(
        io.BytesIO(csv_content.encode("utf-8")),
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=dictionary_template.csv",
        },
    )


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


class PreviewRequest(BaseModel):
    ci_ids: List[str] = []


class PreviewMetricResult(BaseModel):
    metric_id: str
    oid: str
    value: Optional[str]
    status: str  # OK | WARNING | CRITICAL | NO_DATA


class CIPreviewResult(BaseModel):
    ci_id: str
    ci_name: str
    ip: Optional[str]
    results: List[PreviewMetricResult]


class PreviewResponse(BaseModel):
    previews: List[CIPreviewResult]


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


@router.post("/{dictionary_id}/preview", response_model=PreviewResponse)
async def preview_dictionary(
    dictionary_id: str,
    body: PreviewRequest,
    current_user: User = Depends(get_current_active_user),
):
    """
    Preview live SNMP readings for a dictionary applied to specified CIs.
    For each CI: polls each dictionary metric and returns current value + status.
    Use this before applying to see which metrics will actually work on target CIs.
    """
    try:
        previews = await dictionary_service.preview_dictionary(
            dictionary_id,
            body.ci_ids,
        )
        return PreviewResponse(previews=previews)
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


# ---------------------------------------------------------------------------
# Bulk CSV Upload Endpoints
# ---------------------------------------------------------------------------

class BulkValidateResponse(BaseModel):
    rows: List[Dict[str, Any]]
    errors: List[Dict[str, Any]]
    valid_count: int
    error_count: int


@router.post("/bulk", response_model=BulkValidateResponse)
async def bulk_upload(
    file: UploadFile,
    current_user: User = Depends(get_current_active_user),
):
    """
    Parse and validate a CSV file for bulk dictionary creation.
    Returns preview of parsed rows + errors. No commit.
    """
    _require_editor(current_user)

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File must be a .csv",
        )

    content = await file.read()
    # Reject files > 10k rows as a safeguard
    lines = content.decode("utf-8", errors="replace").splitlines()
    if len(lines) > 10001:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="CSV exceeds 10,000 row limit",
        )

    try:
        reader = csv.DictReader(lines)
        rows = []
        for i, row in enumerate(reader):
            row["row_index"] = i + 2  # +2 because row 1 is header, csv is 1-indexed
            rows.append(row)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"CSV parse error: {str(e)}",
        )

    valid_rows, errors = dictionary_service.bulk_validate_rows(rows)

    return BulkValidateResponse(
        rows=valid_rows,
        errors=errors,
        valid_count=len(valid_rows),
        error_count=len(errors),
    )


class BulkValidateSampleRequest(BaseModel):
    rows: List[Dict[str, Any]]


@router.post("/bulk/validate-sample")
async def bulk_validate_sample(
    body: BulkValidateSampleRequest,
    current_user: User = Depends(get_current_active_user),
):
    """
    Run SNMP polling validation on a 10% random sample of CIs per brand+model.
    Accepts validated rows from POST /bulk. Returns aggregated SNMP results.
    """
    validated_rows = body.rows
    if not validated_rows:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No rows provided",
        )

    results = dictionary_service.bulk_validate_snmp_sample(validated_rows)
    return results


class BulkConfirmRequest(BaseModel):
    rows: List[Dict[str, Any]]


class BulkConfirmResponse(BaseModel):
    created: List[Dict[str, Any]]
    count: int


@router.post("/bulk/confirm", response_model=BulkConfirmResponse)
async def bulk_confirm(
    body: BulkConfirmRequest,
    current_user: User = Depends(get_current_active_user),
):
    """
    Atomically create all MetricDictionary nodes and HAS_METRIC links
    from previously validated rows. Returns created dictionary summaries.
    """
    _require_editor(current_user)

    validated_rows = body.rows
    if not validated_rows:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No rows provided",
        )

    try:
        validated_rows, errors = dictionary_service.bulk_validate_rows(body.rows)
        if errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"message": "Re-validation failed", "errors": errors},
            )
        created = dictionary_service.bulk_create_dictionaries(validated_rows)
        return BulkConfirmResponse(created=created, count=len(created))
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": str(e)},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Bulk creation failed",
        )
