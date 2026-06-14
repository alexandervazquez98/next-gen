import json
from typing import List, Dict, Any, Optional
from database import get_db
from models.core import Category, HardwareModel, OwnerGroup
from services.category_icons import (
    get_default_category_icon,
    normalize_icon_key,
    is_valid_icon_key,
    resolve_category_icon,
)
from fastapi import HTTPException

def get_categories() -> List[Dict[str, str]]:
    driver = get_db()
    with driver.session() as session:
        result = session.run(
            "MATCH (c:Category) RETURN c.name as name, c.icon_key as icon_key"
        )
        return [
            {
                "name": record["name"],
                "icon_key": resolve_category_icon(record["name"], record.get("icon_key")),
            }
            for record in result
        ]

def create_category(category: Category) -> Dict[str, str]:
    driver = get_db()
    if category.icon_key is not None and not is_valid_icon_key(category.icon_key):
        # Unknown icon values are rejected at API level, but keep defense in depth.
        raise HTTPException(status_code=400, detail="Invalid icon_key")

    icon_key = normalize_icon_key(category.icon_key) or get_default_category_icon(category.name)

    # Respect default catalog mapping for known technologies while avoiding overriding
    # unknown/custom metadata.
    default_icon = get_default_category_icon(category.name)

    with driver.session() as session:
        if icon_key is not None:
            session.run(
                """
                MERGE (c:Category {name: $name})
                ON CREATE SET c.icon_key = $icon_key
                ON MATCH SET c.icon_key = COALESCE(c.icon_key, $default_icon_key)
                """,
                name=category.name,
                icon_key=icon_key,
                default_icon_key=default_icon,
            )
        else:
            session.run(
                """
                MERGE (c:Category {name: $name})
                ON MATCH SET c.icon_key = COALESCE(c.icon_key, $default_icon_key)
                """,
                name=category.name,
                default_icon_key=default_icon,
            )
    return {"message": "Category created"}

def delete_category(name: str) -> Dict[str, str]:
    driver = get_db()
    with driver.session() as session:
        session.run("MATCH (c:Category {name: $name}) DETACH DELETE c", name=name)
    return {"message": "Category deleted"}

def update_category(
    name: str,
    new_name: str,
    icon_key: Optional[str] = None,
) -> Dict[str, str]:
    if icon_key is not None and not is_valid_icon_key(icon_key):
        raise HTTPException(status_code=400, detail="Invalid icon_key")

    # Always keep legacy behavior even if icon_key is omitted.
    default_icon = get_default_category_icon(new_name)

    driver = get_db()
    with driver.session() as session:
        query = """
            MATCH (c:Category {name: $name})
            SET c.name = $new_name
            """

        if icon_key is None:
            # Preserve stored metadata for unknown categories; only set default for
            # known technologies when absent.
            if default_icon:
                query += " SET c.icon_key = COALESCE(c.icon_key, $default_icon_key)"
            session.run(
                query,
                name=name,
                new_name=new_name,
                default_icon_key=default_icon,
            )
            return {"message": "Category updated"}

        session.run(
            query + " SET c.icon_key = $icon_key",
            name=name,
            new_name=new_name,
            icon_key=resolve_category_icon(new_name, icon_key),
        )
    return {"message": "Category updated"}

def get_category_usage(name: str) -> Dict[str, int]:
    driver = get_db()
    with driver.session() as session:
        result = session.run("MATCH (n:CI)-[:CATEGORIZED_AS]->(c:Category {name: $name}) RETURN count(n) as count", name=name)
        return {"count": result.single()["count"]}

# ---------------------------------------------------------

def get_hardware_catalog() -> List[Dict[str, Any]]:
    driver = get_db()
    with driver.session() as session:
        query = """
        MATCH (h:HardwareModel)
        OPTIONAL MATCH (h)-[:BELONGS_TO]->(c:Category)
        OPTIONAL MATCH (h)-[:MANAGED_BY]->(o:OwnerGroup)
        RETURN h.brand as brand, h.model as model, c.name as category, o.name as owner
        """
        result = session.run(query)
        return [{
            "brand": r["brand"], "model": r["model"], "category": r["category"], "owner": r["owner"]
        } for r in result]

def create_hardware_model(item: HardwareModel) -> Dict[str, str]:
    driver = get_db()
    with driver.session() as session:
        session.run("MERGE (h:HardwareModel {brand: $brand, model: $model})", brand=item.brand, model=item.model)
        
        if item.category:
            session.run("""
                MATCH (h:HardwareModel {brand: $brand, model: $model})
                MATCH (c:Category {name: $cat})
                MERGE (h)-[:BELONGS_TO]->(c)
            """, brand=item.brand, model=item.model, cat=item.category)
            
        if item.owner:
            session.run("""
                MATCH (h:HardwareModel {brand: $brand, model: $model})
                MATCH (o:OwnerGroup {name: $own})
                MERGE (h)-[:MANAGED_BY]->(o)
            """, brand=item.brand, model=item.model, own=item.owner)
    return {"message": "Hardware Model saved"}

def delete_hardware_model(brand: str, model: str) -> Dict[str, str]:
    driver = get_db()
    with driver.session() as session:
        session.run("MATCH (h:HardwareModel {brand: $brand, model: $model}) DETACH DELETE h", brand=brand, model=model)
    return {"message": "Hardware Model deleted"}

def update_hardware_model(brand: str, model: str, update: HardwareModel) -> Dict[str, str]:
    driver = get_db()
    with driver.session() as session:
        if update.category:
            session.run("""
                MATCH (h:HardwareModel {brand: $brand, model: $model})
                MATCH (c:Category {name: $cat})
                MERGE (h)-[:BELONGS_TO]->(c)
            """, brand=brand, model=model, cat=update.category)
        
        if update.owner:
            session.run("""
                MATCH (h:HardwareModel {brand: $brand, model: $model})
                MATCH (o:OwnerGroup {name: $own})
                MERGE (h)-[:MANAGED_BY]->(o)
            """, brand=brand, model=model, own=update.owner)

        if update.brand or update.model:
            new_brand = update.brand or brand
            new_model = update.model or model
            session.run("""
                MATCH (h:HardwareModel {brand: $brand, model: $model})
                SET h.brand = $new_brand, h.model = $new_model
            """, brand=brand, model=model, new_brand=new_brand, new_model=new_model)
            
    return {"message": "Hardware Model updated"}

def get_hardware_usage(brand: str, model: str) -> Dict[str, int]:
    driver = get_db()
    with driver.session() as session:
        result = session.run("MATCH (n:CI {brand: $brand, model: $model}) RETURN count(n) as count", brand=brand, model=model)
        return {"count": result.single()["count"]}

def assign_metric_to_model(brand: str, model: str, metric_id: str) -> Dict[str, str]:
    driver = get_db()
    with driver.session() as session:
        session.run("""
            MATCH (h:HardwareModel {brand: $brand, model: $model})
            MATCH (m:MetricDef {id: $mid})
            MERGE (h)-[:HAS_METRIC]->(m)
        """, brand=brand, model=model, mid=metric_id)
        
        # Backward compatibility
        result = session.run("MATCH (m:MetricDef {id: $mid}) RETURN m.applicable_to as apt", mid=metric_id)
        current = result.single()["apt"]
        
        criteria = json.loads(current) if current else {}
        if "models" not in criteria: criteria["models"] = []
        if model not in criteria["models"]: criteria["models"].append(model)
            
        session.run("MATCH (m:MetricDef {id: $mid}) SET m.applicable_to = $apt", mid=metric_id, apt=json.dumps(criteria))
        
    return {"message": "Metric assigned to model"}

def unassign_metric_from_model(brand: str, model: str, metric_id: str) -> Dict[str, str]:
    driver = get_db()
    with driver.session() as session:
        session.run("""
            MATCH (h:HardwareModel {brand: $brand, model: $model})-[r:HAS_METRIC]->(m:MetricDef {id: $mid})
            DELETE r
        """, brand=brand, model=model, mid=metric_id)
        
        # Backward compatibility
        result = session.run("MATCH (m:MetricDef {id: $mid}) RETURN m.applicable_to as apt", mid=metric_id)
        if result.peek():
            criteria = json.loads(result.single()["apt"] or "{}")
            if "models" in criteria and model in criteria["models"]:
                criteria["models"].remove(model)
                session.run("MATCH (m:MetricDef {id: $mid}) SET m.applicable_to = $apt", mid=metric_id, apt=json.dumps(criteria))
            
    return {"message": "Metric unassigned from model"}

# ---------------------------------------------------------

def get_owners() -> List[Dict[str, Any]]:
    driver = get_db()
    with driver.session() as session:
        result = session.run("""
        MATCH (g:OwnerGroup)
        OPTIONAL MATCH (g)<-[:BELONGS_TO]-(u:User)
        RETURN g.name as group_name, collect({name: u.name, email: u.email, phone: u.phone}) as users
        """)
        owners = []
        for record in result:
             users_data = [u for u in record["users"] if u.get("name")]
             owners.append({"name": record["group_name"], "users": users_data})
        return owners

def create_owner_group(group: OwnerGroup) -> Dict[str, str]:
    driver = get_db()
    with driver.session() as session:
        session.run("MERGE (g:OwnerGroup {name: $name})", name=group.name)
        if group.users:
            for user in group.users:
                 # Ensure 'user' is a dict as per Pydantic model check, or convert if needed
                 uname = user.get('name')
                 uemail = user.get('email')
                 uphone = user.get('phone')
                 if uname:
                     session.run("""
                        MATCH (g:OwnerGroup {name: $gname})
                        MERGE (u:User {name: $uname})
                        SET u.email = $email, u.phone = $phone
                        MERGE (u)-[:BELONGS_TO]->(g)
                     """, gname=group.name, uname=uname, email=uemail, phone=uphone)
    return {"message": "Owner Group created/updated"}

def delete_owner_group(name: str) -> Dict[str, str]:
    driver = get_db()
    with driver.session() as session:
        session.run("MATCH (g:OwnerGroup {name: $name}) DETACH DELETE g", name=name)
    return {"message": "Owner Group deleted"}

def update_owner_group(name: str, update: OwnerGroup) -> Dict[str, str]:
    driver = get_db()
    with driver.session() as session:
        if update.name:
            session.run("MATCH (g:OwnerGroup {name: $name}) SET g.name = $new_name", name=name, new_name=update.name)
            name = update.name 
            
        if update.users is not None:
            session.run("MATCH (u:User)-[r:BELONGS_TO]->(g:OwnerGroup {name: $name}) DELETE r", name=name)
            for user in update.users:
                 uname = user.get('name')
                 uemail = user.get('email')
                 uphone = user.get('phone')
                 if uname:
                    session.run("""
                        MATCH (g:OwnerGroup {name: $gname})
                        MERGE (u:User {name: $uname})
                        SET u.email = $email, u.phone = $phone
                        MERGE (u)-[:BELONGS_TO]->(g)
                    """, gname=name, uname=uname, email=uemail, phone=uphone)
    return {"message": "Owner Group updated"}

def get_owner_usage(name: str) -> Dict[str, int]:
    driver = get_db()
    with driver.session() as session:
        cis_res = session.run("MATCH (n:CI)-[:OWNED_BY]->(g:OwnerGroup {name: $name}) RETURN count(n) as count", name=name).single()
        users_res = session.run("MATCH (u:User)-[:BELONGS_TO]->(g:OwnerGroup {name: $name}) RETURN count(u) as count", name=name).single()
        
        cis = cis_res["count"] if cis_res else 0
        users = users_res["count"] if users_res else 0
        return {"count": cis, "user_count": users}

def link_user_to_group(group_name: str, user_data: Dict[str, str]) -> Dict[str, str]:
    driver = get_db()
    with driver.session() as session:
        session.run("""
            MATCH (g:OwnerGroup {name: $gname})
            MERGE (u:User {name: $uname})
            SET u.email = $email, u.phone = $phone
            MERGE (u)-[:BELONGS_TO]->(g)
        """, gname=group_name, uname=user_data.get('name'), email=user_data.get('email'), phone=user_data.get('phone'))
    return {"message": "User linked to group"}

def unlink_user_from_group(group_name: str, user_name: str) -> Dict[str, str]:
    driver = get_db()
    with driver.session() as session:
        session.run("""
            MATCH (u:User {name: $uname})-[r:BELONGS_TO]->(g:OwnerGroup {name: $gname})
            DELETE r
        """, uname=user_name, gname=group_name)
    return {"message": "User unlinked from group"}
