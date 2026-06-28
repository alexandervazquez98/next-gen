from typing import List, Dict, Any, Optional
from fastapi import HTTPException
from models.core import Link
from models.user import User
from repositories import topology_repo

# Slice 1 (feat-324): the three allowed tunnel mediums. Anything else is
# rejected before persistence. Centralized so both the model validator and
# the service-level guard agree.
ALLOWED_TUNNEL_MEDIUMS = frozenset({"vpn", "sd_wan", "satellite"})
VPN_HUB_LAYER = "vpn_hub"


def get_links(current_user: Optional[User] = None) -> List[Dict[str, Any]]:
    """
    Fetch all active relationship links.
    Enforces data scoping based on user allowed locations.
    """
    # Unauthenticated graph consumers (Geo View) should receive the global topology.
    # Scoped filtering only applies when an authenticated non-admin user is present.
    is_admin = current_user.role == "ADMIN" if current_user else True
    allowed_locations = current_user.allowed_locations if current_user else None
    return topology_repo.get_links(allowed_locations, is_admin)


def validate_tunnel_endpoint_hub(
    source_id: str,
    target_id: str,
    source_type: Optional[str] = None,
    target_type: Optional[str] = None,
    medium: Optional[str] = None,
) -> None:
    """Hub-obligatorio validator for tunnel relations.

    Rules (Slice 1 / VPN-Rel R3):
    - When ``medium`` is one of the allowed tunnel mediums, exactly two
      endpoints must be present and at least one must have layer ``vpn_hub``.
    - When ``medium`` is None, the function is a no-op (legacy non-tunnel
      relation type — no hub rule applies).
    - Unknown medium values raise ``HTTPException(400)`` before persistence.
    - When endpoint types are not provided to the validator, they are
      fetched from the repository so callers do not need a separate lookup.

    Raises ``HTTPException(400)`` for any rule violation. Persistence must
    not happen on this failure path — callers must call this BEFORE
    ``topology_repo.create_link``.
    """
    if medium is None or medium == "":
        return

    if medium not in ALLOWED_TUNNEL_MEDIUMS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"medium must be one of {sorted(ALLOWED_TUNNEL_MEDIUMS)}; got {medium!r}"
            ),
        )

    if source_type is None or target_type is None:
        endpoint_types = topology_repo.get_endpoint_types(source_id, target_id)
        source_type = source_type or endpoint_types.get("source_type")
        target_type = target_type or endpoint_types.get("target_type")

    if source_type == VPN_HUB_LAYER or target_type == VPN_HUB_LAYER:
        return

    raise HTTPException(
        status_code=400,
        detail=(
            "tunnel relation must have at least one vpn_hub endpoint; "
            f"got source_type={source_type!r}, target_type={target_type!r}"
        ),
    )


def create_link(link: Link) -> Dict[str, str]:
    """
    Create a new relationship (edge) between two nodes.

    Slice 1 (feat-324): enforces the hub-obligatorio rule for tunnel
    relations BEFORE persistence so a validation failure never produces
    a partial write.
    """
    validate_tunnel_endpoint_hub(
        source_id=link.source,
        target_id=link.target,
        medium=link.medium,
    )
    topology_repo.create_link(link.source, link.target, link.relationship, medium=link.medium)
    return {"message": "Link created"}


def update_link(link: Link) -> Dict[str, str]:
    """Update an existing relationship, optionally changing its medium.

    Slice 1 (feat-324): when medium is set, validates the hub rule
    against the existing endpoints before any write.
    """
    validate_tunnel_endpoint_hub(
        source_id=link.source,
        target_id=link.target,
        medium=link.medium,
    )
    topology_repo.update_link(link.source, link.target, link.relationship, medium=link.medium)
    return {"message": "Link updated"}


def delete_link(link: Link) -> Dict[str, str]:
    """
    Delete a relationship between two nodes.
    """
    topology_repo.delete_link(link.source, link.target, link.relationship)
    return {"message": "Link deleted"}

def get_cis_relationships(ci_ids: list[str], current_user: User) -> dict:
    """
    Batch-fetch scoped CI relationship summaries for Admin relationship UI.
    """
    is_admin = current_user.role == "ADMIN"
    return topology_repo.get_cis_relationship_summary(
        ci_ids,
        allowed_locations=current_user.allowed_locations,
        is_admin=is_admin,
    )

def get_full_graph(current_user: Optional[User] = None, layer: Optional[str] = None, location: Optional[str] = None, owner: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    """
    Fetch the COMPLETE graph topology for visualization.
    Supports filtering by metadata and data scoping.
    """
    is_admin = current_user.role == "ADMIN" if current_user else False
    allowed_locations = current_user.allowed_locations if current_user else None
    raw_nodes, raw_links = topology_repo.get_filtered_graph_data(
        layer=layer, location=location, owner=owner, 
        allowed_locations=allowed_locations, is_admin=is_admin
    )

    nodes = []
    for node_props in raw_nodes:
        labels = node_props.get("_labels", [])
        
        # Determine primary type/label
        primary_type = "CI" if not labels or "CI" in labels else "Unknown"
        if "Category" in labels: primary_type = "Category"
        elif "OwnerGroup" in labels: primary_type = "Owner"
        elif "MetricDef" in labels: primary_type = "Metric"
        elif "HardwareModel" in labels: primary_type = "Hardware"
        elif "User" in labels: primary_type = "User"
        
        # If it's a CI, prefer the 'layer' property for the type display
        display_type = primary_type
        if primary_type == "CI" and node_props.get("layer"):
            display_type = node_props.get("layer")

        fallback_id = (
            node_props.get("id")
            or node_props.get("name")
            or node_props.get("label")
            or " ".join(
                str(part)
                for part in [node_props.get("brand"), node_props.get("model")]
                if part
            )
        )

        nodes.append({
            "id": fallback_id,
            "label": node_props.get("name") or node_props.get("label") or fallback_id,
            "type": display_type,
            "status": node_props.get("status", "ACTIVE"),
            "location": node_props.get("location"),
            "location_name": node_props.get("location_name"),
            "ip": node_props.get("ip"),
            "metrics": node_props.get("metrics", []),
            "metadata": {k: v for k, v in node_props.items() if not k.startswith("_")}
        })

    links = []
    for link_data in raw_links:
        source_id = link_data["source_node"].get("id")
        target_id = link_data["target_node"].get("id")

        if source_id and target_id:
            # Slice 1 (feat-324): tunnel medium is part of the payload when
            # the underlying relationship carries it. Legacy links (medium
            # unset) keep the original shape so existing consumers do not
            # see a key that does not apply.
            link_payload = {
                "source": source_id,
                "target": target_id,
                "relationship": link_data["type"],
            }
            medium = link_data.get("medium")
            if medium:
                link_payload["medium"] = medium
            links.append(link_payload)

    return {"nodes": nodes, "links": links}

def simulate_bulk_links(current_user: User, source_filter: dict, target_filter: dict) -> Dict[str, Any]:
    """
    Simulates a bulk link operation and returns the potential impact.
    Enforces data scoping.
    """
    is_admin = current_user.role == "ADMIN"

    if not is_admin:
        if source_filter.get("location") and source_filter["location"] not in current_user.allowed_locations:
             raise ValueError(f"Unauthorized location in source filter: {source_filter['location']}")
        if target_filter.get("location") and target_filter["location"] not in current_user.allowed_locations:
             raise ValueError(f"Unauthorized location in target filter: {target_filter['location']}")

    data = topology_repo.count_potential_links(
        source_filter, target_filter,
        allowed_locations=current_user.allowed_locations,
        is_admin=is_admin
    )

    count = data["total"]

    # T8: Enrich with existing relationship info for the simulate response
    src_ids, tgt_ids = _get_filtered_node_ids(source_filter, target_filter, is_admin, current_user.allowed_locations)
    all_ids = list(set(src_ids + tgt_ids))
    existing_rels = topology_repo.get_cis_relationship_summary(
        all_ids,
        allowed_locations=current_user.allowed_locations,
        is_admin=is_admin,
    )

    sources_with_rels = [sid for sid in src_ids if existing_rels.get(sid, {}).get("asSource")]
    targets_with_rels = [tid for tid in tgt_ids if existing_rels.get(tid, {}).get("asTarget")]

    return {
        "potential_links": count,
        "source_samples": data["source_samples"],
        "target_samples": data["target_samples"],
        "is_safe": count <= 500,
        "message": "Ready to execute" if count <= 500 else "Too many potential links (> 500). Please refine filters.",
        "has_existing_relationships": {
            "source": sources_with_rels,
            "target": targets_with_rels,
        }
    }

def _get_filtered_node_ids(source_filter: dict, target_filter: dict, is_admin: bool, allowed_locations: Optional[list]) -> tuple[list[str], list[str]]:
    """Extract unique node ids from source and target filters."""
    from repositories import topology_repo
    src_nodes = topology_repo._get_nodes_by_filter(source_filter, is_admin, allowed_locations)
    tgt_nodes = topology_repo._get_nodes_by_filter(target_filter, is_admin, allowed_locations)
    src_ids = list(set(n["id"] for n in src_nodes))
    tgt_ids = list(set(n["id"] for n in tgt_nodes))
    return src_ids, tgt_ids


def execute_bulk_links(current_user: User, source_filter: dict, target_filter: dict, relationship: str) -> Dict[str, Any]:
    """
    Executes a mass relationship creation after validation.
    """
    sim = simulate_bulk_links(current_user, source_filter, target_filter)
    if not sim["is_safe"]:
        affected_sources = sim.get("has_existing_relationships", {}).get("source", [])
        result = {"success": False, "message": sim["message"]}
        if affected_sources:
            result["existing_relationships_warning"] = (
                f"Some source CIs already have outgoing {relationship} relationships: "
                + ", ".join(affected_sources[:10])
                + (f" and {len(affected_sources) - 10} more" if len(affected_sources) > 10 else "")
            )
        return result

    is_admin = current_user.role == "ADMIN"
    allowed_locations = current_user.allowed_locations

    src_ids, tgt_ids = _get_filtered_node_ids(source_filter, target_filter, is_admin, allowed_locations)
    all_ids = list(set(src_ids + tgt_ids))
    existing_rels = topology_repo.get_cis_relationship_summary(
        all_ids,
        allowed_locations=allowed_locations,
        is_admin=is_admin,
    )

    affected_sources = [
        sid for sid in src_ids
        if any(r["type"] == relationship for r in existing_rels.get(sid, {}).get("asSource", []))
    ]

    report = topology_repo.execute_mass_links(
        source_filter, target_filter, relationship,
        allowed_locations=allowed_locations,
        is_admin=is_admin
    )

    result = {
        "success": True,
        "message": f"Operation complete: {report['created']} new links created, {report['verified']} links verified.",
        "created_count": report['created'],
        "verified_count": report['verified'],
        "total": report['total'],
    }

    if affected_sources:
        result["existing_relationships_warning"] = (
            f"Some source CIs already have outgoing {relationship} relationships: "
            + ", ".join(affected_sources[:10])
            + (f" and {len(affected_sources) - 10} more" if len(affected_sources) > 10 else "")
        )

    return result

def execute_bulk_delete(current_user: User, source_filter: dict, target_filter: dict, relationship: str) -> Dict[str, Any]:
    """
    Executes a mass relationship deletion based on filters.
    """
    is_admin = current_user.role == "ADMIN"
    report = topology_repo.execute_mass_delete(
        source_filter, target_filter, relationship,
        allowed_locations=current_user.allowed_locations,
        is_admin=is_admin
    )
    
    return {
        "success": True, 
        "message": f"Operation complete: {report['deleted']} links deleted.",
        "deleted_count": report['deleted']
    }

def execute_bulk_update(current_user: User, source_filter: dict, target_filter: dict, old_relationship: str, new_relationship: str) -> Dict[str, Any]:
    """
    Executes a mass relationship update (type change) based on filters.
    """
    is_admin = current_user.role == "ADMIN"
    report = topology_repo.execute_mass_update(
        source_filter, target_filter, old_relationship, new_relationship,
        allowed_locations=current_user.allowed_locations,
        is_admin=is_admin
    )
    
    return {
        "success": True, 
        "message": f"Operation complete: {report['updated']} links updated to {new_relationship}.",
        "updated_count": report['updated']
    }
