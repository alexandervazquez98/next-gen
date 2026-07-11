from __future__ import annotations

import io
import json
import logging
import uuid
from contextlib import suppress
from typing import Any

import pandas as pd
from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from models.core import Node
from models.user import User, UserPermission, UserRole
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from repositories import topology_repo
from services.auth_service import check_permission
from services.category_icons import resolve_category_icon

logger = logging.getLogger(__name__)


# ── AI Field-Level Validation ─────────────────────────────────────────────────

ALLOWED_AI_METADATA_FIELDS = {"status", "pollingInterval", "owner", "location_name", "metadata"}

BLOCKED_AI_UPDATE_FIELDS = {
    "id",
    "label",
    "type",
    "brand",
    "model",
    "serialNumber",
    "firmwareVersion",
    "ip",
    "snmp",
    "location",
}


class NodeMetadataUpdate(BaseModel):
    """AI-safe subset of node fields for metadata update."""

    model_config = ConfigDict(populate_by_name=True)

    status: str | None = None
    polling_interval: int | None = Field(None, ge=10, le=3600, alias="pollingInterval")
    owner: str | None = None
    location_name: str | None = None
    metadata: dict[str, Any] | None = None


def validate_ai_metadata_update(update_data: dict) -> tuple[bool, list[str]]:
    """Returns (is_valid, blocked_fields)"""
    blocked = []
    for key in update_data:
        if key in BLOCKED_AI_UPDATE_FIELDS:
            blocked.append(key)
    if blocked:
        return False, blocked
    return True, []


def get_nodes(current_user: User) -> list[dict[str, Any]]:
    """
    Fetch all Configuration Items (CIs).
    Parses metadata and SNMP configurations for frontend consumption.
    Enforces Data Scoping based on User Permissions.
    """

    # Apply Scoping (If not Admin)
    is_admin = current_user.role == "ADMIN" or current_user.role == UserRole.ADMIN.value

    raw_nodes = topology_repo.get_nodes(current_user.allowed_locations, is_admin)

    nodes = []
    for record in raw_nodes:
        node = record["node"]
        loc = None
        if node.get("location"):
            with suppress(AttributeError, TypeError):
                if hasattr(node.get("location"), "latitude"):
                    loc = {
                        "lat": node.get("location").latitude,
                        "long": node.get("location").longitude,
                    }

        # Serialize metadata props
        clean_metadata = {}
        for k, v in node.items():
            if k in ["id", "name", "status", "location", "ip", "layer"]:
                continue
            if hasattr(v, "isoformat"):
                clean_metadata[k] = v.isoformat()
            else:
                clean_metadata[k] = v

        # Process Metrics
        metrics = []
        for m in record["metrics"]:
            if m.get("name"):  # Filter out nulls from OPTIONAL MATCH
                m_data = {
                    "name": m["name"],
                    "protocol": m.get("protocol"),
                    "status": m.get("status", "UNKNOWN"),
                    "value": m.get("value"),
                    "last_updated": None,
                }
                if m.get("last_updated"):
                    with suppress(AttributeError, TypeError):
                        m_data["last_updated"] = m["last_updated"].isoformat()
                metrics.append(m_data)

        category = record["category"]
        node_data = {
            "id": node.get("id"),
            "label": node.get("name"),
            "type": category or node.get("layer", "Unknown"),
            "category": category,
            "category_icon_key": resolve_category_icon(category, record.get("category_icon_key")),
            "status": node.get("status", "OK"),
            "ip": node.get("ip"),
            "public_ip": node.get("public_ip"),
            "owner": node.get("owner"),
            "brand": node.get("brand"),
            "model": node.get("model"),
            "serialNumber": node.get("serialNumber"),
            "firmwareVersion": node.get("firmwareVersion"),
            "pollingInterval": node.get("pollingInterval") or 60,
            "snmp": node.get("snmp"),
            "location": loc,
            "location_name": node.get("location_name"),
            "metadata": {**clean_metadata},
            "metrics": metrics,
        }
        # Parse SNMP stored as string if necessary
        if isinstance(node_data["snmp"], str):
            try:
                node_data["snmp"] = json.loads(node_data["snmp"])
            except (json.JSONDecodeError, TypeError):
                node_data["snmp"] = None  # Avoid Pydantic Validation Error
        elif node_data["snmp"] is None:
            node_data["snmp"] = None

        nodes.append(node_data)

    return nodes


def create_update_node(node: Node, current_user: User) -> dict[str, str]:
    """
    Create or Update a Configuration Item (CI).
    Enforces CI_EDIT permission.
    """
    # Permission Check
    if not check_permission(UserPermission.CI_EDIT, current_user):
        raise HTTPException(status_code=403, detail="Permission denied: CI_EDIT required")

    # Slice 1 (feat-324): if the Node was constructed without validation
    # (e.g. via model_construct or by raw dict coercion), surface any
    # Pydantic ValidationError as HTTP 400 BEFORE any repository write.
    # The service-level guard complements the model validator so callers
    # that bypass Pydantic (tests, internal tools) get a 400, not a 500.
    try:
        node = Node.model_validate(node.model_dump())
    except ValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"invalid CI payload: {exc.errors()[0].get('msg', 'validation failed')}",
        ) from exc

    topology_repo.upsert_node(node)

    # Create Default PING Metric
    if node.ip:
        topology_repo.create_default_ping_metric(node.id, node.label)

    # Reconcile Metrics (Add/Remove based on new properties)
    from services.metric_service import reconcile_node_metrics

    try:
        # Convert Pydantic Node to dict for the service or just pass basics
        node_dict = node.dict()
        reconcile_node_metrics(node_dict)
    except Exception as e:
        logger.error(f"Error reconciling metrics for {node.id}: {e}")

    return {"message": "Node created/updated", "id": node.id}


def delete_node(node_id: str, current_user: User) -> dict[str, str]:
    """
    Delete a Configuration Item (CI) by its ID.
    Enforces CI_DELETE permission.
    """
    if not check_permission(UserPermission.CI_DELETE, current_user):
        raise HTTPException(status_code=403, detail="Permission denied: CI_DELETE required")

    topology_repo.delete_node(node_id)
    return {"message": "Node deleted", "id": node_id}


def get_node_usage(node_id: str) -> dict[str, int]:
    """
    Check the usage of a CI (number of relationships).
    """
    count = topology_repo.get_node_usage(node_id)
    return {"count": count}


def update_node_metadata(node_id: str, metadata_update: NodeMetadataUpdate) -> dict[str, str]:
    """Update CI metadata fields (status, pollingInterval, owner, location_name, metadata).

    This is the AI-safe update path — field validation is done by the caller.
    """
    from repositories import topology_repo

    update_data = metadata_update.model_dump(exclude_unset=True, by_alias=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    # Build the metadata dict
    metadata = update_data.get("metadata", {})
    for key in ["status", "pollingInterval", "owner", "location_name"]:
        if key in update_data:
            metadata[key] = update_data[key]

    topology_repo.update_node_metadata(node_id, metadata)
    return {"message": "Node metadata updated", "id": node_id}


async def bulk_upload_nodes(file_contents: bytes, filename: str) -> JSONResponse:
    try:
        # For compatibility with pandas read_excel, we wrap bytes in BytesIO
        df = pd.read_excel(io.BytesIO(file_contents), sheet_name=0)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading Excel file: {str(e)}") from e

    valid_owners, valid_layers = topology_repo.get_valid_owners_and_layers()

    validation_errors = []
    processed_count = 0
    new_nodes = []

    for index, row in df.iterrows():
        row_idx = index + 2

        if pd.isna(row.get("Label")):
            continue

        label = str(row["Label"]).strip()
        raw_id = str(row.get("ID", "")).strip()

        if label == "Sample Router" or raw_id == "(Leave Empty for Auto-ID)":
            continue

        if pd.isna(row.get("ID")) or raw_id == "":
            nid = f"CI-{str(uuid.uuid4())[:8].upper()}"
        else:
            nid = raw_id

        ntype = str(row.get("NetworkLayer", "INFRASTRUCTURE")).strip()
        owner = str(row.get("Owner", "")).strip()
        status = str(row.get("OperationalStatus", "HEALTHY")).strip()

        # Validation Logic
        if owner and owner not in valid_owners:
            validation_errors.append(f"Row {row_idx} (ID: {nid}): Owner '{owner}' not found.")
            continue

        if ntype != "INFRASTRUCTURE" and ntype not in valid_layers:
            validation_errors.append(
                f"Row {row_idx} (ID: {nid}): NetworkLayer '{ntype}' not found."
            )
            continue

        # Normalize Status
        status_upper = status.upper()
        if status_upper in ["HEALTHY", "OK", "ACTIVE"]:
            status = "ACTIVE"
        elif status_upper in ["WARNING", "CRITICAL", "EXCEPTION"]:
            status = "EXCEPTION"
        elif status_upper == "MAINTENANCE":
            status = "MAINTENANCE"
        else:
            validation_errors.append(
                f"Row {row_idx} (ID: {nid}): OperationalStatus '{status}' is not supported."
            )
            continue

        # Params
        brand = str(row.get("Brand", "")).strip()
        model = str(row.get("Model", "")).strip()
        serial = str(row.get("SerialNumber", "")).strip()
        firmware = str(row.get("Firmware", "")).strip()

        snmp = {
            "version": str(row.get("SNMP_Version", "v2c")).strip(),
            "readCommunity": str(row.get("SNMP_Read", "public")).strip(),
            "writeCommunity": str(row.get("SNMP_Write", "private")).strip(),
            "port": 161,
        }
        snmp_str = json.dumps(snmp)

        ip = str(row.get("IP", ""))
        loc_name = str(row.get("Location", ""))

        lat, long = 0.0, 0.0
        if "Latitude" in row and not pd.isna(row["Latitude"]):
            with suppress(TypeError, ValueError):
                lat = float(row["Latitude"])
        if "Longitude" in row and not pd.isna(row["Longitude"]):
            with suppress(TypeError, ValueError):
                long = float(row["Longitude"])

        # Polling Interval from Excel
        polling_val = row.get("PollingInterval")
        try:
            polling_interval = int(polling_val) if not pd.isna(polling_val) else 60
        except (ValueError, TypeError):
            polling_interval = 60

        metadata = {
            "ip": ip,
            "owner": owner,
            "location_name": loc_name,
            "criticality": str(row.get("Criticality", "Low")),
        }

        topology_repo.bulk_insert_node(
            nid,
            label,
            ntype,
            status,
            ip,
            brand,
            model,
            serial,
            firmware,
            lat,
            long,
            polling_interval,
            snmp_str,
            metadata,
            owner,
        )
        # Collect node dict for metric reconciliation after all inserts
        new_nodes.append(
            {
                "id": nid,
                "name": label,
                "brand": brand,
                "model": model,
                "layer": ntype,
            }
        )
        processed_count += 1

    # Reconcile metrics for all newly inserted CIs
    if new_nodes:
        from services.metric_service import reconcile_node_metrics

        for node_dict in new_nodes:
            try:
                reconcile_node_metrics(node_dict)
            except Exception as e:
                logger.error(f"Error reconciling metrics for {node_dict['id']}: {e}")

    if validation_errors:
        return JSONResponse(
            status_code=207,
            content={
                "message": f"Processed {processed_count} CIs. Some rows failed validation.",
                "errors": validation_errors[:10],
            },
        )

    return {"message": f"Successfully processed {processed_count} CIs"}


def search_nodes(current_user: User, term: str) -> list[dict[str, Any]]:
    """
    Search CI nodes by term with permission scoping.

    Admin users see all matching nodes. Non-admin users are scoped to their
    allowed_locations. The term is passed directly to the repo which handles
    metacharacter stripping.
    """
    is_admin = current_user.role == "ADMIN" or current_user.role == UserRole.ADMIN.value
    allowed_locations = None if is_admin else current_user.allowed_locations

    raw_nodes = topology_repo.search_nodes(term, allowed_locations, is_admin)
    return raw_nodes


def get_node_template() -> StreamingResponse:
    owners_list, layers_list = topology_repo.get_template_data()

    template_data = {
        "ID": ["(Leave Empty for Auto-ID)"],
        "Label": ["Sample Router"],
        "NetworkLayer": ["INFRASTRUCTURE"],
        "OperationalStatus": ["ACTIVE"],
        "Brand": ["Cisco"],
        "Model": ["ASR-1000"],
        "SerialNumber": ["SN12345678"],
        "Firmware": ["17.3.1"],
        "IP": ["192.168.1.100"],
        "SNMP_Version": ["v2c"],
        "SNMP_Read": ["public"],
        "SNMP_Write": ["private"],
        "Owner": ["NetOps"],
        "Location": ["Data Center A"],
        "Latitude": [19.4326],
        "Longitude": [-99.1332],
        "Criticality": ["High"],
    }

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(template_data).to_excel(writer, index=False, sheet_name="Data Entry Template")
        pd.DataFrame(owners_list, columns=["Available Owners"]).to_excel(
            writer, index=False, sheet_name="Ref - Owners"
        )
        pd.DataFrame(layers_list, columns=["Available Network Layers"]).to_excel(
            writer, index=False, sheet_name="Ref - Network Layers"
        )

    output.seek(0)
    return StreamingResponse(
        output,
        headers={"Content-Disposition": 'attachment; filename="ci_import_template_v2.xlsx"'},
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
