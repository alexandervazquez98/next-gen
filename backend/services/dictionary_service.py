"""
Dictionary Service — CRUD operations for MetricDictionary nodes in Neo4j.
"""
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from database import get_db

logger = logging.getLogger(__name__)


def _get_driver():
    return get_db()


def _now():
    return datetime.now()


def get_metrics_from_dictionary(dictionary_id: str) -> List[str]:
    """
    Resolve HAS_METRIC relationships from a MetricDictionary to get metric_ids.
    Returns list of metric_id strings.
    """
    driver = _get_driver()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (md:MetricDictionary {id: $dict_id})-[r:HAS_METRIC]->(m:MetricDef)
            RETURN m.id AS metric_id
            """,
            dict_id=dictionary_id,
        )
        return [record["metric_id"] for record in result]


def get_dictionary(id: str) -> Optional[Dict[str, Any]]:
    """Get a single dictionary by id, including its metric_ids."""
    driver = _get_driver()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (md:MetricDictionary {id: $id})
            RETURN md.id AS id, md.name AS name, md.brand AS brand,
                   md.model AS model, md.polling_interval AS polling_interval,
                   md.created_at AS created_at, md.updated_at AS updated_at
            """,
            id=id,
        ).single()

        if not result:
            return None

        dictionary = {
            "id": result["id"],
            "name": result["name"],
            "brand": result["brand"],
            "model": result["model"],
            "polling_interval": result["polling_interval"],
            "created_at": result["created_at"],
            "updated_at": result["updated_at"],
        }
        dictionary["metric_ids"] = get_metrics_from_dictionary(id)
        return dictionary


def get_dictionary_by_brand_model(brand: str, model: str) -> Optional[Dict[str, Any]]:
    """Get a dictionary by exact brand+model match."""
    driver = _get_driver()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (md:MetricDictionary {brand: $brand, model: $model})
            RETURN md.id AS id
            """,
            brand=brand,
            model=model,
        ).single()

        if not result:
            return None
        return get_dictionary(result["id"])


def list_dictionaries() -> List[Dict[str, Any]]:
    """List all dictionaries with their metric_ids."""
    driver = _get_driver()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (md:MetricDictionary)
            RETURN md.id AS id, md.name AS name, md.brand AS brand,
                   md.model AS model, md.polling_interval AS polling_interval,
                   md.created_at AS created_at, md.updated_at AS updated_at
            ORDER BY md.name
            """
        )

        dictionaries = []
        for record in result:
            dictionary = {
                "id": record["id"],
                "name": record["name"],
                "brand": record["brand"],
                "model": record["model"],
                "polling_interval": record["polling_interval"],
                "created_at": record["created_at"],
                "updated_at": record["updated_at"],
            }
            dictionary["metric_ids"] = get_metrics_from_dictionary(dictionary["id"])
            dictionaries.append(dictionary)
        return dictionaries


def create_dictionary(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a new MetricDictionary node with HAS_METRIC relationships.
    Raises ValueError if brand+model pair already exists.
    """
    driver = _get_driver()

    # Check for duplicate brand+model
    existing = get_dictionary_by_brand_model(data["brand"], data["model"])
    if existing:
        raise ValueError(f"Dictionary with brand='{data['brand']}' and model='{data['model']}' already exists")

    dict_id = data["id"]
    now = _now()

    with driver.session() as session:
        # Create the MetricDictionary node
        session.run(
            """
            CREATE (md:MetricDictionary {
                id: $id,
                name: $name,
                brand: $brand,
                model: $model,
                polling_interval: $polling_interval,
                created_at: $now,
                updated_at: $now
            })
            """,
            id=dict_id,
            name=data["name"],
            brand=data["brand"],
            model=data["model"],
            polling_interval=data.get("polling_interval", 60),
            now=now,
        )

        # Create HAS_METRIC relationships
        metric_ids = data.get("metric_ids", [])
        for metric_id in metric_ids:
            # Verify MetricDef exists before linking
            exists = session.run(
                """
                MATCH (m:MetricDef {id: $mid})
                RETURN m.id AS id
                """,
                mid=metric_id,
            ).single()
            if exists:
                session.run(
                    """
                    MATCH (md:MetricDictionary {id: $dict_id})
                    MATCH (m:MetricDef {id: $mid})
                    CREATE (md)-[:HAS_METRIC]->(m)
                    """,
                    dict_id=dict_id,
                    mid=metric_id,
                )
            else:
                logger.warning(f"MetricDef '{metric_id}' not found — skipping HAS_METRIC link")

        return get_dictionary(dict_id)


def update_dictionary(id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Update a MetricDictionary node.
    Updates: name, brand, model, polling_interval, metric_ids (replace, not merge).
    Returns None if dictionary not found.
    Raises ValueError if new brand+model conflicts with existing dictionary.
    """
    driver = _get_driver()

    existing = get_dictionary(id)
    if not existing:
        return None

    # Check for brand+model conflict with OTHER dictionary
    new_brand = data.get("brand", existing["brand"])
    new_model = data.get("model", existing["model"])

    with driver.session() as check_session:
        conflict = check_session.run(
            """
            MATCH (md:MetricDictionary {brand: $brand, model: $model})
            WHERE md.id <> $id
            RETURN md.id AS id
            """,
            brand=new_brand,
            model=new_model,
            id=id,
        ).single()

    if conflict:
        raise ValueError(f"Another dictionary with brand='{new_brand}' and model='{new_model}' already exists")

    now = _now()

    with driver.session() as session:
        # Update node properties
        session.run(
            """
            MATCH (md:MetricDictionary {id: $id})
            SET md.name = $name,
                md.brand = $brand,
                md.model = $model,
                md.polling_interval = $polling_interval,
                md.updated_at = $now
            """,
            id=id,
            name=data.get("name", existing["name"]),
            brand=new_brand,
            model=new_model,
            polling_interval=data.get("polling_interval", existing["polling_interval"]),
            now=now,
        )

        # Replace metric_ids if provided
        if "metric_ids" in data:
            # Remove existing HAS_METRIC relationships
            session.run(
                """
                MATCH (md:MetricDictionary {id: $id})-[r:HAS_METRIC]->()
                DELETE r
                """,
                id=id,
            )

            # Create new HAS_METRIC relationships
            for metric_id in data["metric_ids"]:
                exists = session.run(
                    """
                    MATCH (m:MetricDef {id: $mid})
                    RETURN m.id AS id
                    """,
                    mid=metric_id,
                ).single()
                if exists:
                    session.run(
                        """
                        MATCH (md:MetricDictionary {id: $dict_id})
                        MATCH (m:MetricDef {id: $mid})
                        CREATE (md)-[:HAS_METRIC]->(m)
                        """,
                        dict_id=id,
                        mid=metric_id,
                    )
                else:
                    logger.warning(f"MetricDef '{metric_id}' not found — skipping")

        return get_dictionary(id)


def delete_dictionary(id: str) -> bool:
    """
    Delete a MetricDictionary node and cascade-delete all AppliedDictionary nodes.
    Returns True if deleted, False if not found.
    """
    driver = _get_driver()

    existing = get_dictionary(id)
    if not existing:
        return False

    with driver.session() as session:
        # Cascade delete AppliedDictionary nodes first
        session.run(
            """
            MATCH (ad:AppliedDictionary {dictionary_id: $id})
            DETACH DELETE ad
            """,
            id=id,
        )

        # Delete the MetricDictionary node
        session.run(
            """
            MATCH (md:MetricDictionary {id: $id})
            DETACH DELETE md
            """,
            id=id,
        )

    return True


def get_target_cis(dictionary_id: str) -> List[Dict[str, Any]]:
    """
    Return CIs where brand and model match the dictionary's brand+model exactly.
    Case-insensitive comparison. Returns [{id, name, ip, brand, model, location_name}].
    Raises ValueError if dictionary not found.
    """
    dictionary = get_dictionary(dictionary_id)
    if not dictionary:
        raise ValueError(f"Dictionary '{dictionary_id}' not found")

    driver = _get_driver()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (n:CI)
            WHERE n.brand IS NOT NULL AND n.model IS NOT NULL
              AND toLower(n.brand) = toLower($brand)
              AND toLower(n.model) = toLower($model)
            RETURN n.id AS id, n.name AS name, n.ip AS ip,
                   n.brand AS brand, n.model AS model,
                   n.location_name AS location_name
            """,
            brand=dictionary["brand"],
            model=dictionary["model"],
        )

        return [
            {
                "id": record["id"],
                "name": record["name"],
                "ip": record["ip"],
                "brand": record["brand"],
                "model": record["model"],
                "location_name": record["location_name"],
            }
            for record in result
        ]


def apply_dictionary(
    dictionary_id: str,
    ci_ids: List[str],
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Apply a dictionary to the specified CI list.
    Creates/updates AppliedDictionary nodes (idempotent MERGE).
    If dry_run=True, returns count without persisting anything.
    Returns {applied_count, skipped_count, message}.
    Raises ValueError if dictionary not found.
    """
    dictionary = get_dictionary(dictionary_id)
    if not dictionary:
        raise ValueError(f"Dictionary '{dictionary_id}' not found")

    driver = _get_driver()
    applied_count = 0
    skipped_count = 0

    for ci_id in ci_ids:
        with driver.session() as session:
            # Check CI exists and has IP
            ci_result = session.run(
                "MATCH (n:CI {id: $ci_id}) RETURN n.ip AS ip",
                ci_id=ci_id,
            ).single()

            if not ci_result:
                skipped_count += 1
                logger.warning(f"CI '{ci_id}' not found — skipping")
                continue

            if not ci_result["ip"]:
                skipped_count += 1
                logger.warning(f"CI '{ci_id}' has no IP — skipping")
                continue

            if dry_run:
                applied_count += 1
                continue

            # Upsert AppliedDictionary via MERGE (idempotent)
            now = _now()
            session.run(
                """
                MERGE (ci:CI {id: $ci_id})-[:HAS_DICTIONARY]->(ad:AppliedDictionary {dictionary_id: $dict_id})
                ON CREATE SET ad.id = $ad_id,
                              ad.excluded_metrics = [],
                              ad.extra_metrics = [],
                              ad.applied_at = $now
                ON MATCH SET ad.dictionary_id = $dict_id,
                            ad.applied_at = $now
                """,
                ci_id=ci_id,
                dict_id=dictionary_id,
                ad_id=str(uuid.uuid4()),
                now=now,
            )

            # Create REFERENCE_DICTIONARY link
            session.run(
                """
                MATCH (ci:CI {id: $ci_id})-[:HAS_DICTIONARY]->(ad:AppliedDictionary {dictionary_id: $dict_id})
                MATCH (md:MetricDictionary {id: $dict_id})
                MERGE (ad)-[:REFERENCE_DICTIONARY]->(md)
                """,
                ci_id=ci_id,
                dict_id=dictionary_id,
            )

            applied_count += 1

    return {
        "applied_count": applied_count,
        "skipped_count": skipped_count,
        "message": f"Applied to {applied_count} CIs, skipped {skipped_count}",
    }


def validate_metric_ids(metric_ids: List[str]) -> tuple[bool, List[str]]:
    """
    Validate that all metric_ids exist as MetricDef nodes.
    Returns (all_valid, invalid_ids).
    """
    if not metric_ids:
        return True, []

    driver = _get_driver()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (m:MetricDef)
            WHERE m.id IN $ids
            RETURN m.id AS id
            """,
            ids=metric_ids,
        )
        found = {record["id"] for record in result}
        invalid = [mid for mid in metric_ids if mid not in found]

    return len(invalid) == 0, invalid