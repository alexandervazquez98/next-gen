from typing import List, Dict, Any, Optional
from models.core import Link
from repositories import topology_repo

from models.user import User, UserRole

def get_links() -> List[Dict[str, Any]]:
    """
    Fetch all active relationship links between CIs and Metrics.
    """
    return topology_repo.get_links()

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

def get_full_graph(current_user: User, layer: str = None, location: str = None, owner: str = None) -> Dict[str, List[Dict[str, Any]]]:
    """
    Fetch the COMPLETE graph topology for visualization.
    Supports filtering by metadata. Default view is Technical Topology (:CI).
    Enforces Data Scoping.
    """
    is_admin = current_user.role == "ADMIN" or current_user.role == UserRole.ADMIN.value
    allowed_locations = current_user.allowed_locations

    raw_nodes, raw_links = topology_repo.get_filtered_graph_data(
        layer=layer, 
        location=location, 
        owner=owner,
        allowed_locations=allowed_locations,
        is_admin=is_admin
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
        # Determine Label/Name
        label_text = node_props.get("name") or node_props.get("id") or node_props.get("label") or "N/A"
        if not label_text or label_text == "N/A":
            brand = node_props.get("brand")
            model = node_props.get("model")
            if brand and model:
                label_text = f"{brand} {model}"
            elif brand:
                label_text = brand
            elif model:
                label_text = model
        
        nodes.append({
            "id": node_props.get("id") or label_text, # Fallback ID if node has no ID prop
            "label": label_text,
            "type": primary_type,
            "status": node_props.get("status", "ACTIVE") # Default status
        })

    links = []
    for link_data in raw_links:
        source_node = link_data["source_node"]
        target_node = link_data["target_node"]
        
        # Resolve IDs (must match node generation logic above)
        def get_node_id(n):
            lbl = n.get("name") or n.get("id") or n.get("label")
            if not lbl:
                brand = n.get("brand")
                model = n.get("model")
                if brand and model: lbl = f"{brand} {model}"
                elif brand: lbl = brand
                elif model: lbl = model
            return n.get("id") or lbl or "N/A"

        source_id = get_node_id(source_node)
        target_id = get_node_id(target_node)
        
        if source_id and target_id and source_id != "N/A" and target_id != "N/A":
            links.append({
                "source": source_id,
                "target": target_id,
                "relationship": link_data["type"]
            })
            
    return {"nodes": nodes, "links": links}
