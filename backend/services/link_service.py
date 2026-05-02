from typing import List, Dict, Any, Optional
from models.core import Link
from models.user import User
from repositories import topology_repo

def get_links(current_user: User = None) -> List[Dict[str, Any]]:
    """
    Fetch all active relationship links.
    Enforces data scoping based on user allowed locations.
    """
    is_admin = current_user.role == "ADMIN" if current_user else False
    allowed_locations = current_user.allowed_locations if current_user else None
    return topology_repo.get_links(allowed_locations, is_admin)

def create_link(link: Link) -> Dict[str, str]:
    """
    Create a new relationship (edge) between two nodes.
    """
    topology_repo.create_link(link.source, link.target, link.relationship)
    return {"message": "Link created"}

def delete_link(link: Link) -> Dict[str, str]:
    """
    Delete a relationship between two nodes.
    """
    topology_repo.delete_link(link.source, link.target, link.relationship)
    return {"message": "Link deleted"}

def get_full_graph(current_user: User = None, layer: str = None, location: str = None, owner: str = None) -> Dict[str, List[Dict[str, Any]]]:
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
        primary_type = "CI" # Default for filtered view
        if "Category" in labels: primary_type = "Category"
        elif "OwnerGroup" in labels: primary_type = "Owner"
        elif "MetricDef" in labels: primary_type = "Metric"
        elif "HardwareModel" in labels: primary_type = "Hardware"
        elif "User" in labels: primary_type = "User"
        
        # If it's a CI, prefer the 'layer' property for the type display
        display_type = primary_type
        if primary_type == "CI" and node_props.get("layer"):
            display_type = node_props.get("layer")

        nodes.append({
            "id": node_props.get("id"),
            "label": node_props.get("name") or node_props.get("label") or node_props.get("id"),
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
            links.append({
                "source": source_id,
                "target": target_id,
                "relationship": link_data["type"]
            })
            
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
    
    return {
        "potential_links": count,
        "source_samples": data["source_samples"],
        "target_samples": data["target_samples"],
        "is_safe": count <= 500,
        "message": "Ready to execute" if count <= 500 else "Too many potential links (> 500). Please refine filters."
    }

def execute_bulk_links(current_user: User, source_filter: dict, target_filter: dict, relationship: str) -> Dict[str, Any]:
    """
    Executes a mass relationship creation after validation.
    """
    sim = simulate_bulk_links(current_user, source_filter, target_filter)
    if not sim["is_safe"]:
        return {"success": False, "message": sim["message"]}
    
    is_admin = current_user.role == "ADMIN"
    report = topology_repo.execute_mass_links(
        source_filter, target_filter, relationship,
        allowed_locations=current_user.allowed_locations,
        is_admin=is_admin
    )
    
    return {
        "success": True, 
        "message": f"Operation complete: {report['created']} new links created, {report['verified']} links verified.",
        "created_count": report['created'],
        "verified_count": report['verified'],
        "total": report['total']
    }

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
