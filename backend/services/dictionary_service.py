"""
Dictionary Service — CRUD operations for MetricDictionary nodes in Neo4j.
"""

import ast
import asyncio
import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

from database import get_db

logger = logging.getLogger(__name__)


def _get_driver():
    return get_db()


def _now():
    return datetime.now()


# SNMP preview parallel query batch size
SNMP_PREVIEW_BATCH_SIZE = 20


def get_metrics_from_dictionary(dictionary_id: str) -> list[str]:
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


def get_dictionary(id: str) -> dict[str, Any] | None:
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


def get_dictionary_by_brand_model(brand: str, model: str) -> dict[str, Any] | None:
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


class MetricDictionaryLookup:
    """Read managed values from ``MetricDictionary`` nodes by dictionary key.

    Managed keys (``value_stream``, ``tier``, ``criticality``) share the
    ``MetricDictionary`` label with the brand/model dictionary templates but
    are scoped by the ``dictionary_key`` property and carry ``value``/``label``
    instead of ``id``/``name``/``brand``/``model``.

    This class is the single read seam for managed dictionary values: the
    dictionaries router and the Service Management import path both use it, so
    the dropdown sources and the import validation can never drift apart.
    """

    DICTIONARY_KEY = ""

    def __init__(self, dictionary_key: str | None = None, driver: Any | None = None) -> None:
        self.dictionary_key = dictionary_key or self.DICTIONARY_KEY
        self._driver = driver if driver is not None else _get_driver()

    def list_values(self, *, active: bool = True) -> list[dict[str, Any]]:
        """Return ``[{value, label}]`` rows for this dictionary key."""

        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (v:MetricDictionary {dictionary_key: $key})
                WHERE coalesce(v.active, true) = $active
                RETURN v.value AS value, coalesce(v.label, v.value) AS label
                ORDER BY v.value
                """,
                key=self.dictionary_key,
                active=active,
            )
            return [{"value": r["value"], "label": r["label"]} for r in result]

    def list_active(self) -> list[dict[str, Any]]:
        """Return the active ``[{value, label}]`` rows for this dictionary key."""

        return self.list_values(active=True)

    def is_active(self, value: str) -> bool:
        """Return True when ``value`` is an active row of this dictionary key."""

        if not value:
            return False
        with self._driver.session() as session:
            record = session.run(
                """
                MATCH (v:MetricDictionary {dictionary_key: $key, value: $value})
                RETURN coalesce(v.active, true) AS active
                """,
                key=self.dictionary_key,
                value=value,
            ).single()
        if record is None:
            return False
        return bool(record.get("active"))


def list_dictionaries() -> list[dict[str, Any]]:
    """List all dictionaries with their metric_ids.

    Managed MetricDictionary rows (``dictionary_key`` set — ``value_stream``,
    ``tier``, ``criticality``) are value lists, not dictionary templates, so
    they are excluded here: they would otherwise surface as null-shaped
    records for the legacy CMDB dictionary manager.
    """
    driver = _get_driver()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (md:MetricDictionary)
            WHERE md.dictionary_key IS NULL
            RETURN md.id AS id, md.name AS name, md.brand AS brand,
                   md.model AS model, md.polling_interval AS polling_interval,
                   md.created_at AS created_at, md.updated_at AS updated_at,
                   md.dictionary_key AS dictionary_key
            ORDER BY md.name
            """
        )

        dictionaries = []
        for record in result:
            if record.get("dictionary_key") is not None:
                # Defense in depth: managed rows never belong in the legacy list.
                continue
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


def list_dictionary_values(dictionary_key: str, *, active: bool = True) -> list[dict[str, Any]]:
    """Return ``[{value, label}]`` for a managed MetricDictionary key.

    Managed key surfaces (``value_stream``, ``tier``, ``criticality``) live on
    the same label as the brand/model dictionaries, but are scoped by
    ``dictionary_key`` and carry ``value``/``label``. This helper keeps that
    property layout out of the routers.
    """

    return MetricDictionaryLookup(dictionary_key).list_values(active=active)


def create_dictionary(data: dict[str, Any]) -> dict[str, Any]:
    """
    Create a new MetricDictionary node with HAS_METRIC relationships.
    Raises ValueError if brand+model pair already exists.
    """
    driver = _get_driver()

    # Check for duplicate brand+model
    existing = get_dictionary_by_brand_model(data["brand"], data["model"])
    if existing:
        raise ValueError(
            f"Dictionary with brand='{data['brand']}' and model='{data['model']}' already exists"
        )

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


def update_dictionary(id: str, data: dict[str, Any]) -> dict[str, Any] | None:
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
        raise ValueError(
            f"Another dictionary with brand='{new_brand}' and model='{new_model}' already exists"
        )

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


def get_target_cis(dictionary_id: str) -> list[dict[str, Any]]:
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
    ci_ids: list[str],
    dry_run: bool = False,
) -> dict[str, Any]:
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


def validate_metric_ids(metric_ids: list[str]) -> tuple[bool, list[str]]:
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


# ---- 3. Batch metric_ids collection per brand+model group ----
def _collect_metric_ids_by_group(
    rows: list[dict[str, Any]],
) -> dict[tuple[str, str], list[str]]:
    """Group metric_ids by brand+model, deduplicated."""
    by_group: dict[tuple[str, str], set[str]] = {}
    for row in rows:
        key = (row["brand"].lower(), row["model"].lower())
        by_group.setdefault(key, set()).update(row["metric_ids"])
    return {k: list(v) for k, v in by_group.items()}


# ---- 4. Pre-validate all metric_ids before transaction ----
def _pre_validate_metric_ids(
    rows: list[dict[str, Any]],
) -> tuple[bool, dict[str, list[str]]]:
    """
    Collect all unique metric_ids across all rows and validate in one query.
    Returns (all_valid, per_row_errors) where per_row_errors maps row_index to invalid ids.
    """
    all_metric_ids: set[str] = set()
    for row in rows:
        all_metric_ids.update(row["metric_ids"])

    if not all_metric_ids:
        return True, {}

    driver = _get_driver()
    with driver.session() as session:
        result = session.run(
            "MATCH (m:MetricDef) WHERE m.id IN $ids RETURN m.id AS id",
            ids=list(all_metric_ids),
        )
        found = {record["id"] for record in result}

    invalid_by_row: dict[str, list[str]] = {}
    for row in rows:
        invalid = [mid for mid in row["metric_ids"] if mid not in found]
        if invalid:
            key = str(row["row_index"])
            invalid_by_row[key] = invalid

    return len(invalid_by_row) == 0, invalid_by_row


# ---------------------------------------------------------------------------
# Preview — Parallel SNMP query for live readings
# ---------------------------------------------------------------------------

try:
    from pysnmp.hlapi import (
        CommunityData,
        ContextData,
        ObjectIdentity,
        ObjectType,
        SnmpEngine,
        UdpTransportTarget,
        getCmd,
    )

    SNMP_AVAILABLE = True
except ImportError:
    SNMP_AVAILABLE = False


def _parse_snmp_config(snmp_raw: Any) -> dict[str, Any]:
    """Parse SNMP config from CI node snmp field (dict, JSON string, or ast-literal)."""
    if not snmp_raw:
        return {}
    if isinstance(snmp_raw, dict):
        return snmp_raw
    try:
        return json.loads(snmp_raw)
    except Exception:
        try:
            return ast.literal_eval(snmp_raw)
        except Exception:
            return {}


def _get_metric_defs(metric_ids: list[str]) -> list[dict[str, Any]]:
    """Fetch MetricDef details (oid, warning, critical, operator) for given IDs."""
    if not metric_ids:
        return []
    driver = _get_driver()
    with driver.session() as session:
        result = session.run(
            "MATCH (m:MetricDef) WHERE m.id IN $ids RETURN m",
            ids=metric_ids,
        )
        metric_defs = []
        for record in result:
            m = record["m"]
            metric_defs.append(
                {
                    "id": m.get("id"),
                    "oid": m.get("oid"),
                    "protocol": m.get("protocol", "SNMP"),
                    "warning": m.get("warning"),
                    "critical": m.get("critical"),
                    "operator": m.get("operator", ">="),
                }
            )
        return metric_defs


def _poll_single_metric(ci_ip: str, snmp_conf: dict[str, Any], metric_def: dict[str, Any]):
    """
    Poll a single metric on a single CI via SNMP.
    Returns (value, poll_status_str) where poll_status_str is 'OK' or 'NO_DATA'.
    Runs in-thread (blocking SNMP call).
    """
    if not SNMP_AVAILABLE:
        return None, "NO_DATA"

    oid = metric_def.get("oid")
    if not oid or oid == "ICMP":
        return None, "NO_DATA"

    community = snmp_conf.get("readCommunity")
    if not community:
        return None, "NO_DATA"

    port = snmp_conf.get("port", 161)
    try:
        error_indication, error_status, error_index, var_binds = next(
            getCmd(
                SnmpEngine(),
                CommunityData(community),
                UdpTransportTarget((ci_ip, port), timeout=1.0, retries=0),
                ContextData(),
                ObjectType(ObjectIdentity(oid)),
            )
        )
        if error_indication:
            return None, "NO_DATA"
        if error_status:
            return None, "NO_DATA"
        value = str(var_binds[0][1])
        return value, "OK"
    except Exception:
        return None, "NO_DATA"


def _compute_metric_status(value: Any, metric_def: dict[str, Any]) -> str:
    """Determine status (OK/WARNING/CRITICAL/NO_DATA) based on value and thresholds."""
    if value is None:
        return "NO_DATA"

    try:
        num_val = float(value)
        operator = metric_def.get("operator", ">=")

        def check_op(left, right, oper):
            if oper == ">=":
                return left >= right
            if oper == "<=":
                return left <= right
            if oper == "==":
                return left == right
            if oper == "!=":
                return left != right
            return left >= right

        if metric_def.get("critical") is not None and check_op(
            num_val, float(metric_def["critical"]), operator
        ):
            return "CRITICAL"
        if metric_def.get("warning") is not None and check_op(
            num_val, float(metric_def["warning"]), operator
        ):
            return "WARNING"
        return "OK"
    except (ValueError, TypeError):
        # Non-numeric value — can't apply thresholds
        return "OK" if value is not None else "NO_DATA"


async def preview_dictionary(
    dictionary_id: str,
    ci_ids: list[str],
) -> list[dict[str, Any]]:
    """
    Preview live SNMP readings for a dictionary applied to specified CIs.
    For each CI: fetch SNMP config, poll each metric in the dictionary.
    Runs in parallel batches of 20 CIs.
    Returns [{ci_id, ci_name, ip, results: [{metric_id, oid, value, status}]}].
    Raises ValueError if dictionary not found.
    """
    dictionary = get_dictionary(dictionary_id)
    if not dictionary:
        raise ValueError(f"Dictionary '{dictionary_id}' not found")

    metric_defs = _get_metric_defs(dictionary["metric_ids"])
    if not metric_defs:
        return []

    # Fetch CI details (name, ip, snmp) in bulk
    driver = _get_driver()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (n:CI)
            WHERE n.id IN $ids
            RETURN n.id AS id, n.name AS name, n.ip AS ip, n.snmp AS snmp
            """,
            ids=ci_ids,
        )
        ci_records = list(result)

    ci_map = {
        rec["id"]: {
            "name": rec["name"],
            "ip": rec["ip"],
            "snmp": _parse_snmp_config(rec["snmp"]) if rec["snmp"] else {},
        }
        for rec in ci_records
    }

    def poll_ci(ci_id: str) -> dict[str, Any]:
        """Poll all metrics for a single CI (runs in thread pool)."""
        ci = ci_map.get(ci_id, {})
        ci_name = ci.get("name", ci_id)
        ip = ci.get("ip")
        snmp_conf = ci.get("snmp", {})

        results = []
        for metric_def in metric_defs:
            if not ip:
                results.append(
                    {
                        "metric_id": metric_def["id"],
                        "oid": metric_def.get("oid", ""),
                        "value": None,
                        "status": "NO_DATA",
                    }
                )
                continue

            value, poll_status = _poll_single_metric(ip, snmp_conf, metric_def)
            if poll_status == "NO_DATA":
                results.append(
                    {
                        "metric_id": metric_def["id"],
                        "oid": metric_def.get("oid", ""),
                        "value": None,
                        "status": "NO_DATA",
                    }
                )
            else:
                status = _compute_metric_status(value, metric_def)
                results.append(
                    {
                        "metric_id": metric_def["id"],
                        "oid": metric_def.get("oid", ""),
                        "value": value,
                        "status": status,
                    }
                )

        return {
            "ci_id": ci_id,
            "ci_name": ci_name,
            "ip": ip,
            "results": results,
        }

    # Parallel execution in batches of SNMP_PREVIEW_BATCH_SIZE
    batch_size = SNMP_PREVIEW_BATCH_SIZE
    previews = []
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=batch_size) as executor:
        for i in range(0, len(ci_ids), batch_size):
            batch = ci_ids[i : i + batch_size]
            futures = [loop.run_in_executor(executor, poll_ci, ci_id) for ci_id in batch]
            batch_results = await asyncio.gather(*futures)
            previews.extend(batch_results)

    return previews


# ---------------------------------------------------------------------------
# Per-CI Exclusions — AppliedDictionary management
# ---------------------------------------------------------------------------


def get_applied_dictionary(ci_id: str) -> dict[str, Any] | None:
    """
    Get the AppliedDictionary for a CI, including dictionary details.
    Returns dict with {dictionary_id, dictionary_name, excluded_metrics, extra_metrics, applied_at}
    or None if no dictionary is applied.
    """
    driver = _get_driver()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (ci:CI {id: $ci_id})-[:HAS_DICTIONARY]->(ad:AppliedDictionary)
            OPTIONAL MATCH (ad)-[:REFERENCE_DICTIONARY]->(md:MetricDictionary)
            RETURN ad.id AS ad_id,
                   ad.dictionary_id AS dictionary_id,
                   ad.excluded_metrics AS excluded_metrics,
                   ad.extra_metrics AS extra_metrics,
                   ad.applied_at AS applied_at,
                   md.name AS dictionary_name,
                   md.brand AS dictionary_brand,
                   md.model AS dictionary_model,
                   md.metric_ids AS dictionary_metric_ids
            """,
            ci_id=ci_id,
        ).single()

    if not result or not result.get("dictionary_id"):
        return None

    # Get the dictionary's actual metric_ids from HAS_METRIC relationships
    dict_metric_ids = (
        get_metrics_from_dictionary(result["dictionary_id"]) if result["dictionary_id"] else []
    )

    return {
        "dictionary_id": result["dictionary_id"],
        "dictionary_name": result["dictionary_name"],
        "dictionary_brand": result["dictionary_brand"],
        "dictionary_model": result["dictionary_model"],
        "metric_ids": dict_metric_ids,
        "excluded_metrics": result.get("excluded_metrics") or [],
        "extra_metrics": result.get("extra_metrics") or [],
        "applied_at": result.get("applied_at"),
    }


def update_ci_exclusions(
    ci_id: str,
    excluded_metrics: list[str] | None = None,
    extra_metrics: list[str] | None = None,
) -> dict[str, Any]:
    """
    Update or create AppliedDictionary exclusions/extras for a CI.
    excluded_metrics and extra_metrics REPLACE existing values (not merge).
    If CI has no AppliedDictionary, this is a no-op (caller should use apply_dictionary first).
    Raises ValueError if extra_metric_ids contain non-existent MetricDefs.
    """
    # Validate extra_metrics if provided
    if extra_metrics is not None and extra_metrics:
        valid, invalid = validate_metric_ids(extra_metrics)
        if not valid:
            raise ValueError(f"Invalid extra_metric_ids: {invalid}")

    driver = _get_driver()
    with driver.session() as session:
        # Check if AppliedDictionary exists for this CI
        exists = session.run(
            """
            MATCH (ci:CI {id: $ci_id})-[:HAS_DICTIONARY]->(ad:AppliedDictionary)
            RETURN ad.id AS ad_id
            """,
            ci_id=ci_id,
        ).single()

        if not exists:
            raise ValueError(
                f"No AppliedDictionary found for CI '{ci_id}'. Apply a dictionary first."
            )

        # Update excluded_metrics and extra_metrics
        session.run(
            """
            MATCH (ci:CI {id: $ci_id})-[:HAS_DICTIONARY]->(ad:AppliedDictionary)
            SET ad.excluded_metrics = $excluded,
                ad.extra_metrics = $extra
            """,
            ci_id=ci_id,
            excluded=excluded_metrics if excluded_metrics is not None else [],
            extra=extra_metrics if extra_metrics is not None else [],
        )

    return get_applied_dictionary(ci_id)


def remove_applied_dictionary(ci_id: str) -> bool:
    """
    Remove AppliedDictionary from a CI (un-apply dictionary).
    Does NOT delete the MetricDictionary or MetricDef nodes.
    Returns True if removed, False if no AppliedDictionary existed.
    """
    driver = _get_driver()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (ci:CI {id: $ci_id})-[r:HAS_DICTIONARY]->(ad:AppliedDictionary)
            DELETE r
            DETACH DELETE ad
            RETURN count(*) AS deleted
            """,
            ci_id=ci_id,
        ).single()

    if result is None:
        return False
    deleted = result.get("deleted")
    # Handle case where result.get returns a non-int (e.g., MagicMock in tests)
    if not isinstance(deleted, int):
        return False
    return deleted >= 0


# ---------------------------------------------------------------------------
# Bulk CSV Upload Helpers
# ---------------------------------------------------------------------------


def get_template_brands_models() -> list[tuple[str, str]]:
    """
    Return distinct (brand, model) pairs from CI nodes that have both fields.
    Used to pre-populate the CSV template.
    """
    driver = _get_driver()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (n:CI)
            WHERE n.brand IS NOT NULL AND n.model IS NOT NULL
              AND n.brand <> '' AND n.model <> ''
            RETURN DISTINCT n.brand AS brand, n.model AS model
            ORDER BY n.brand, n.model
            """
        )
        return [(record["brand"], record["model"]) for record in result]


def bulk_validate_rows(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Validate a list of parsed CSV rows (dicts with brand, model, name,
    polling_interval, metric_ids keys).

    Validation steps:
      1. Format completeness (all required fields present and non-empty)
      2. CI existence per brand+model (at least one CI matches)
      3. metric_ids exist as MetricDef nodes
      4. Duplicate within CSV (same brand+model+name triple)

    Returns (valid_rows, errors):
      valid_rows: list of validated row dicts with row_index included
      errors: list of {row, field, message} dicts
    """
    errors: list[dict[str, Any]] = []
    validated_rows: list[dict[str, Any]] = []

    # Collect existing brand+model pairs from CIs once
    existing_pairs: set[tuple[str, str]] = set(get_template_brands_models())

    # Collect all (brand, model, name) triples for duplicate detection
    seen_triples: set[tuple[str, str, str]] = set()

    # Pre-collect ALL metric_ids across all rows for batch validation
    all_row_metric_ids: list[list[str]] = []
    row_metric_ids_map: dict[int, list[str]] = {}
    for row in rows:
        row_idx = row.get("row_index", 0)
        metric_ids = [
            mid.strip() for mid in str(row.get("metric_ids") or "").split(",") if mid.strip()
        ]
        all_row_metric_ids.append(metric_ids)
        row_metric_ids_map[row_idx] = metric_ids

    all_unique_metric_ids = set()
    for mids in all_row_metric_ids:
        all_unique_metric_ids.update(mids)

    if all_unique_metric_ids:
        driver = _get_driver()
        with driver.session() as session:
            result = session.run(
                "MATCH (m:MetricDef) WHERE m.id IN $ids RETURN m.id AS id",
                ids=list(all_unique_metric_ids),
            )
            valid_metric_ids = {record["id"] for record in result}
    else:
        valid_metric_ids = set()

    for row in rows:
        row_idx = row.get("row_index", 0)

        # ---- 1. Format completeness ----
        required = ["brand", "model", "name", "polling_interval", "metric_ids"]
        for field in required:
            if field not in row or str(row.get(field) or "").strip() == "":
                errors.append(
                    {"row": row_idx, "field": field, "message": f"Missing or empty '{field}'"}
                )
                break
        else:
            brand = str(row["brand"]).strip()
            model = str(row["model"]).strip()
            name = str(row["name"]).strip()
            polling_interval_str = str(row["polling_interval"] or "60").strip()

            # ---- 4. Duplicate within CSV ----
            triple = (brand.lower(), model.lower(), name.lower())
            if triple in seen_triples:
                errors.append(
                    {
                        "row": row_idx,
                        "field": "name",
                        "message": f"Duplicate dictionary name '{name}' for brand='{brand}' model='{model}'",
                    }
                )
            else:
                seen_triples.add(triple)

            # ---- 2. CI existence ----
            if (brand.lower(), model.lower()) not in existing_pairs:
                errors.append(
                    {
                        "row": row_idx,
                        "field": "brand",
                        "message": f"No CIs found for brand='{brand}' model='{model}'",
                    }
                )

            # ---- 3. metric_ids exist (in-memory check against batch-validated set) ----
            metric_ids = row_metric_ids_map.get(row_idx, [])
            if metric_ids:
                invalid = [mid for mid in metric_ids if mid not in valid_metric_ids]
                if invalid:
                    errors.append(
                        {
                            "row": row_idx,
                            "field": "metric_ids",
                            "message": f"Invalid metric_ids: {invalid}",
                        }
                    )

            # ---- polling_interval must be numeric ----
            try:
                int(polling_interval_str)
            except ValueError:
                errors.append(
                    {
                        "row": row_idx,
                        "field": "polling_interval",
                        "message": f"polling_interval must be an integer, got '{polling_interval_str}'",
                    }
                )

            # If no errors for this row, add to validated_rows
            row_errors = [e for e in errors if e["row"] == row_idx]
            if not row_errors:
                validated_rows.append(
                    {
                        "brand": brand,
                        "model": model,
                        "name": name,
                        "polling_interval": int(polling_interval_str),
                        "metric_ids": metric_ids,
                        "row_index": row_idx,
                    }
                )

    return validated_rows, errors


def bulk_validate_snmp_sample(
    validated_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    For each distinct brand+model in validated_rows, select ~10% of matching CIs
    at random and poll each metric via SNMP.  Returns aggregated results.

    validated_rows: list of row dicts from bulk_validate_rows

    Returns:
      {
        "results": {
          "brand+model_key": {
            "sampled_ips": [...],
            "polled": [{ip, metric_id, value, status}],
            "no_data": [{ip, metric_id, status}],
          }
        }
      }
    """
    import random

    results: dict[str, Any] = {}
    driver = _get_driver()

    # Group rows by brand+model
    by_brand_model: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in validated_rows:
        key = (row["brand"].lower(), row["model"].lower())
        by_brand_model.setdefault(key, []).append(row)

    for (brand, model), _ in by_brand_model.items():
        # Get all CIs for this brand+model
        with driver.session() as session:
            cis = list(
                session.run(
                    """
                MATCH (n:CI)
                WHERE n.brand IS NOT NULL AND n.model IS NOT NULL
                  AND toLower(n.brand) = $brand
                  AND toLower(n.model) = $model
                  AND n.ip IS NOT NULL AND n.ip <> ''
                RETURN n.id AS id, n.ip AS ip, n.snmp AS snmp, n.name AS name
                """,
                    brand=brand,
                    model=model,
                )
            )

        if not cis:
            continue

        # Select ~10% random CIs (minimum 1)
        sample_size = max(1, int(len(cis) * 0.1))
        sampled = random.sample(cis, min(sample_size, len(cis)))
        sampled_ips = [c["ip"] for c in sampled]

        polled: list[dict[str, Any]] = []
        no_data: list[dict[str, Any]] = []

        all_metric_ids_for_group: list[str] = []
        for row in by_brand_model[(brand, model)]:
            all_metric_ids_for_group.extend(row["metric_ids"])
        unique_metric_ids = list(set(all_metric_ids_for_group))
        metric_defs_by_id = {m["id"]: m for m in _get_metric_defs(unique_metric_ids)}

        for ci in sampled:
            ip = ci["ip"]
            snmp_conf = _parse_snmp_config(ci["snmp"]) if ci["snmp"] else {}

            # Poll each metric from each row for this brand+model
            for row in by_brand_model[(brand, model)]:
                for metric_id in row["metric_ids"]:
                    metric_def = metric_defs_by_id.get(metric_id)
                    if not metric_def:
                        no_data.append({"ip": ip, "metric_id": metric_id, "status": "NO_DATA"})
                        continue

                    value, poll_status = _poll_single_metric(ip, snmp_conf, metric_def)

                    if poll_status == "NO_DATA" or value is None:
                        no_data.append({"ip": ip, "metric_id": metric_id, "status": "NO_DATA"})
                    else:
                        polled.append(
                            {
                                "ip": ip,
                                "metric_id": metric_id,
                                "value": value,
                                "status": "OK",
                            }
                        )

        key = f"{brand}-{model}"
        results[key] = {
            "sampled_ips": sampled_ips,
            "polled": polled,
            "no_data": no_data,
        }

    return {"results": results}


def bulk_create_dictionaries(
    validated_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Atomically create all MetricDictionary nodes and their HAS_METRIC links
    in a single Neo4j write transaction.

    validated_rows: list of row dicts from bulk_validate_rows

    Returns list of created dictionary summaries: [{id, name, brand, model}].
    Raises ValueError on any failure (transaction rollback).
    """
    if not validated_rows:
        return []

    driver = _get_driver()
    created: list[dict[str, Any]] = []

    def write_tx(tx):
        now = _now()
        for row in validated_rows:
            dict_id = str(uuid.uuid4())

            tx.run(
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
                name=row["name"],
                brand=row["brand"],
                model=row["model"],
                polling_interval=row["polling_interval"],
                now=now,
            )

            for metric_id in row["metric_ids"]:
                result = tx.run(
                    """
                    MATCH (md:MetricDictionary {id: $dict_id})
                    MATCH (m:MetricDef {id: $mid})
                    RETURN md
                    """,
                    dict_id=dict_id,
                    mid=metric_id,
                )
                if result.single() is None:
                    raise ValueError(f"MetricDef {metric_id} not found during transaction")

                tx.run(
                    """
                    MATCH (md:MetricDictionary {id: $dict_id})
                    MATCH (m:MetricDef {id: $mid})
                    CREATE (md)-[:HAS_METRIC]->(m)
                    """,
                    dict_id=dict_id,
                    mid=metric_id,
                )

            created.append(
                {
                    "id": dict_id,
                    "name": row["name"],
                    "brand": row["brand"],
                    "model": row["model"],
                }
            )

    with driver.session() as session:
        session.execute_write(write_tx)

    return created
