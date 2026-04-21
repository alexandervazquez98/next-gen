import json
import logging
import uuid
import pandas as pd
import io
from typing import List, Dict, Any, Optional
from fastapi import HTTPException
from models.user import User, UserRole, UserPermission
from models.core import Node
from services.auth_service import check_permission
from fastapi.responses import StreamingResponse, JSONResponse
from repositories import topology_repo

logger = logging.getLogger(__name__)


def get_nodes(current_user: User) -> List[Dict[str, Any]]:
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
            try:
                if hasattr(node.get("location"), "latitude"):
                    loc = {
                        "lat": node.get("location").latitude,
                        "long": node.get("location").longitude,
                    }
            except:
                pass

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
                    try:
                        m_data["last_updated"] = m["last_updated"].isoformat()
                    except:
                        pass
                metrics.append(m_data)

        node_data = {
            "id": node.get("id"),
            "label": node.get("name"),
            "type": record["category"] or node.get("layer", "Unknown"),
            "status": node.get("status", "OK"),
            "ip": node.get("ip"),
            "owner": node.get("owner"),
            "brand": node.get("brand"),
            "model": node.get("model"),
            "serialNumber": node.get("serialNumber"),
            "firmwareVersion": node.get("firmwareVersion"),
            "pollingInterval": node.get("pollingInterval") or 60,
            "snmp": node.get("snmp"),
            "location": loc,
            "metadata": {**clean_metadata, "locationName": node.get("location_name")},
            "metrics": metrics,
        }
        # Parse SNMP stored as string if necessary
        if isinstance(node_data["snmp"], str):
            try:
                node_data["snmp"] = json.loads(node_data["snmp"])
            except:
                node_data["snmp"] = None  # Avoid Pydantic Validation Error
        elif node_data["snmp"] is None:
            node_data["snmp"] = None

        nodes.append(node_data)

    return nodes


def create_update_node(node: Node, current_user: User) -> Dict[str, str]:
    """
    Create or Update a Configuration Item (CI).
    Enforces CI_EDIT permission.
    """
    # Permission Check
    if not check_permission(UserPermission.CI_EDIT, current_user):
        raise HTTPException(
            status_code=403, detail="Permission denied: CI_EDIT required"
        )

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


def delete_node(node_id: str, current_user: User) -> Dict[str, str]:
    """
    Delete a Configuration Item (CI) by its ID.
    Enforces CI_DELETE permission.
    """
    if not check_permission(UserPermission.CI_DELETE, current_user):
        raise HTTPException(
            status_code=403, detail="Permission denied: CI_DELETE required"
        )

    topology_repo.delete_node(node_id)
    return {"message": "Node deleted", "id": node_id}


def get_node_usage(node_id: str) -> Dict[str, int]:
    """
    Check the usage of a CI (number of relationships).
    """
    count = topology_repo.get_node_usage(node_id)
    return {"count": count}


async def bulk_upload_nodes(file_contents: bytes, filename: str) -> JSONResponse:
    try:
        # For compatibility with pandas read_excel, we wrap bytes in BytesIO
        df = pd.read_excel(io.BytesIO(file_contents), sheet_name=0)
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Error reading Excel file: {str(e)}"
        )

    valid_owners, valid_layers = topology_repo.get_valid_owners_and_layers()

    validation_errors = []
    processed_count = 0

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
            validation_errors.append(
                f"Row {row_idx} (ID: {nid}): Owner '{owner}' not found."
            )
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
            status = "ACTIVE"

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
            try:
                lat = float(row["Latitude"])
            except:
                pass
        if "Longitude" in row and not pd.isna(row["Longitude"]):
            try:
                long = float(row["Longitude"])
            except:
                pass

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
        processed_count += 1

    if validation_errors:
        return JSONResponse(
            status_code=207,
            content={
                "message": f"Processed {processed_count} CIs. Some rows failed validation.",
                "errors": validation_errors[:10],
            },
        )

    return {"message": f"Successfully processed {processed_count} CIs"}


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
        pd.DataFrame(template_data).to_excel(
            writer, index=False, sheet_name="Data Entry Template"
        )
        pd.DataFrame(owners_list, columns=["Available Owners"]).to_excel(
            writer, index=False, sheet_name="Ref - Owners"
        )
        pd.DataFrame(layers_list, columns=["Available Network Layers"]).to_excel(
            writer, index=False, sheet_name="Ref - Network Layers"
        )

    output.seek(0)
    return StreamingResponse(
        output,
        headers={
            "Content-Disposition": 'attachment; filename="ci_import_template_v2.xlsx"'
        },
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
