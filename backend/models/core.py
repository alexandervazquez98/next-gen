from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Union

# --- Models ---

class Node(BaseModel):
    """Pydantic model representing a Configuration Item (CI) Node."""
    id: str
    label: str 
    type: str  
    status: Optional[str] = "OK" 
    ip: Optional[str] = None
    location: Optional[dict] = None 
    metadata: Optional[dict] = {} 
    # Flattened Fields (Optional)
    owner: Optional[str] = None
    locationName: Optional[str] = None
    pollingInterval: Optional[int] = 60
    snmp: Optional[Union[dict, str]] = None # Can be dict or JSON string
    brand: Optional[str] = None
    model: Optional[str] = None
    serialNumber: Optional[str] = None
    firmwareVersion: Optional[str] = None
    metrics: Optional[List[Dict[str, Any]]] = []

class Link(BaseModel):
    """Pydantic model representing a Relationship Link between CIs."""
    source: str
    target: str
    relationship: str
    id: Optional[str] = None
    source_label: Optional[str] = None
    target_label: Optional[str] = None

class Category(BaseModel):
    name: str

class MetricDef(BaseModel):
    """Definition of a monitored metric."""
    id: str
    protocol: str = "SNMP"
    oid: Optional[str] = None
    warning: Optional[float] = None
    critical: Optional[float] = None
    dataType: Optional[str] = "INTEGER"
    unit: Optional[str] = None
    description: Optional[str] = None
    criticality: Optional[int] = 1 # 1: Info, 2: Warning, 3: Exception
    applicable_to: Optional[Dict[str, List[str]]] = None

class HardwareModel(BaseModel):
    brand: str
    model: str
    category: Optional[str] = None
    owner: Optional[str] = None

class OwnerGroup(BaseModel):
    name: str
    users: Optional[List[dict]] = []
