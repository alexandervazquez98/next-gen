from fastapi import APIRouter, Depends, HTTPException
from typing import List, Dict, Any
from models.core import Link
import services.link_service as link_service

router = APIRouter(
    prefix="/api",
    tags=["Topology"],
    responses={404: {"description": "Not found"}},
)

@router.get("/links", response_model=List[Dict[str, Any]])
async def get_links():
    """
    Fetch all active relationship links between CIs and Metrics.
    """
    return link_service.get_links()

@router.post("/links")
async def create_link(link: Link):
    """
    Create a new relationship (edge) between two nodes.
    """
    return link_service.create_link(link)

@router.delete("/links")
async def delete_link(link: Link):
    """
    Delete a relationship between two nodes.
    """
    return link_service.delete_link(link)

@router.get("/graph/full")
async def get_full_graph(layer: str = None, location: str = None, owner: str = None):
    """
    Fetch the COMPLETE graph topology.
    Supports filtering by metadata (layer, location, owner).
    """
    return link_service.get_full_graph(layer=layer, location=location, owner=owner)
