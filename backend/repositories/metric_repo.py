from sqlalchemy.orm import Session
from sqlalchemy import text, func
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
import logging
from models.timescale_models import MetricValue

logger = logging.getLogger(__name__)

def create_hypertable(db: Session):
    """
    Ensures the metric_values table is converted to a hypertable.
    This should be called on startup.
    """
    try:
        # Check if already hypertable
        # Note: This is a rough check, typically we just try to convert and ignore if exists or check timescaledb_information.hypertables
        db.execute(text("SELECT create_hypertable('metric_values', 'time', if_not_exists => TRUE);"))
        db.commit()
    except Exception as e:
        print(f"Error creating hypertable: {e}")
        db.rollback()

def insert_metric_value(db: Session, node_id: str, metric_id: str, value: float, timestamp: Optional[datetime] = None):
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    
    mv = MetricValue(
        time=timestamp,
        node_id=node_id,
        metric_id=metric_id,
        value=value
    )
    db.add(mv)
    # We commit immediately for real-time data, or we could batch. 
    # For current SNMP worker which pushes one by one or in small loops, commit is fine.
    db.commit()

def bulk_insert_metrics(db: Session, metrics: List[Dict[str, Any]]):
    """
    Bulk insert metrics. 
    metrics: List of dicts with keys: node_id, metric_id, value, time (optional)
    """
    objects = []
    now = datetime.now(timezone.utc)
    for m in metrics:
        objects.append(MetricValue(
            time=m.get('time', now),
            node_id=m['node_id'],
            metric_id=m['metric_id'],
            value=m['value']
        ))
    
    db.bulk_save_objects(objects)
    db.commit()

def get_metric_history(
    db: Session, 
    node_id: str, 
    metric_id: str, 
    limit: int = 100, 
    hours: int = 24,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None
) -> List[Dict[str, Any]]:
    
    query = db.query(MetricValue).filter(MetricValue.node_id == node_id, MetricValue.metric_id == metric_id)
    
    if start_time and end_time:
        # ISO Format strings expected
        try:
            start = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            end = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
            query = query.filter(MetricValue.time >= start, MetricValue.time <= end)
        except ValueError:
             # Fallback or error? For now fallback to hours
             cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
             query = query.filter(MetricValue.time >= cutoff)
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        query = query.filter(MetricValue.time >= cutoff)
        
    results = query.order_by(MetricValue.time.asc()).limit(limit).all()
    
    return [{"time": r.time, "value": r.value} for r in results]

def get_metric_history_days(
    db: Session,
    node_id: str,
    metric_id: str,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> List[str]:
    """Return local/UTC date keys (YYYY-MM-DD) that contain metric samples."""
    query = db.query(func.date(MetricValue.time)).filter(
        MetricValue.node_id == node_id,
        MetricValue.metric_id == metric_id,
    )

    if start_time and end_time:
        try:
            start = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            end = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
            query = query.filter(MetricValue.time >= start, MetricValue.time <= end)
        except ValueError:
            pass

    rows = query.distinct().order_by(func.date(MetricValue.time).asc()).all()
    return [str(row[0]) for row in rows]


def get_latest_metrics(db: Session, node_id: str) -> Dict[str, Any]:
    # This is expensive in standard SQL without strict constraints or specialized index usage (Latest LKT).
    # For now, we simple query.
    # Better to keep "last_value" in Neo4j or use a specialized query if we have many metrics.
    # Using specific query for known metrics is better.
    # Let's try to get latest for all metrics of a node.
    query = text("""
        SELECT DISTINCT ON (metric_id) metric_id, value, time
        FROM metric_values
        WHERE node_id = :node_id
        ORDER BY metric_id, time DESC
    """)
    results = db.execute(query, {"node_id": node_id}).fetchall()
    return {r.metric_id: {"value": r.value, "time": r.time} for r in results}


def _interpolate_to_grid(
    data: List[Dict[str, Any]], grid: List[datetime]
) -> List[Dict[str, Any]]:
    """
    Linearly interpolate metric values onto a common time grid.
    
    Args:
        data: List of {time, value} dicts sorted by time ascending
        grid: Target datetime grid (30-second intervals)
    
    Returns:
        List of {time, value} dicts aligned to grid, missing values filled via linear interpolation
    """
    if not data or not grid:
        return []
    
    # Build a lookup: find the two source points surrounding each grid point
    result = []
    for target_time in grid:
        # Find surrounding points in source data
        before = None
        after = None
        for pt in data:
            pt_time = pt["time"]
            if isinstance(pt_time, str):
                pt_time = datetime.fromisoformat(pt_time.replace('Z', '+00:00'))
            if pt_time <= target_time:
                before = pt
            if pt_time >= target_time and after is None:
                after = pt
        
        if before is None and after is None:
            # No source data at all — skip
            continue
        elif before is None:
            # Before first source point — use first available
            if after is not None:
                result.append({"time": target_time, "value": after["value"]})
        elif after is None:
            # After last source point — use last available
            result.append({"time": target_time, "value": before["value"]})
        elif before["time"] == after["time"]:
            # Exact match
            result.append({"time": target_time, "value": before["value"]})
        else:
            # Linear interpolation
            before_time = before["time"]
            after_time = after["time"]
            if isinstance(before_time, str):
                before_time = datetime.fromisoformat(before_time.replace('Z', '+00:00'))
            if isinstance(after_time, str):
                after_time = datetime.fromisoformat(after_time.replace('Z', '+00:00'))
            
            total_range = (after_time - before_time).total_seconds()
            if total_range == 0:
                result.append({"time": target_time, "value": before["value"]})
            else:
                elapsed = (target_time - before_time).total_seconds()
                ratio = elapsed / total_range
                interpolated = before["value"] + ratio * (after["value"] - before["value"])
                result.append({"time": target_time, "value": interpolated})
    
    return result


def get_metric_history_batch(
    db: Session,
    node_ids: List[str],
    metric_id: str,
    hours: int = 24,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    limit: int = 1000
) -> List[Dict[str, Any]]:
    """
    Fetch historical data for the same metric across multiple CIs,
    interpolating timestamps to a common 30-second grid.
    
    Args:
        db: SQLAlchemy session
        node_ids: List of node IDs (max 10 enforced by router)
        metric_id: Metric identifier
        hours: Lookback window in hours
        start_time: Optional ISO start time override
        end_time: Optional ISO end time override
        limit: Max points per CI
    
    Returns:
        List of {node_id, label, data: [{time, value}]} dicts
    """
    from database import get_db
    from models.core import Node

    # Determine time range
    if start_time and end_time:
        try:
            start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
        except ValueError:
            end_dt = datetime.now(timezone.utc)
            start_dt = end_dt - timedelta(hours=hours)
    else:
        end_dt = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(hours=hours)
    
    # Build 30-second interpolation grid
    grid = []
    current = start_dt
    while current <= end_dt:
        grid.append(current)
        current += timedelta(seconds=30)
    
    # Fetch node labels from Neo4j (batch query - single round trip)
    node_labels: Dict[str, str] = {}
    try:
        with get_db().session() as neo4j_session:
            result = neo4j_session.run(
                "MATCH (n:CiNode) WHERE n.nodeId IN $nodeIds RETURN n.nodeId AS nodeId, n.label AS label",
                nodeIds=node_ids
            )
            for record in result:
                node_labels[record["nodeId"]] = record["label"] or record["nodeId"]
            # Fill missing with node_id
            for node_id in node_ids:
                if node_id not in node_labels:
                    node_labels[node_id] = node_id
    except Exception as e:
        logger.error(f"Failed to fetch node labels: {e}")
        # Fallback: use node_id as label
        for node_id in node_ids:
            node_labels[node_id] = node_id
    
    # Fetch per-CI data
    results = []
    for node_id in node_ids:
        # Query TimescaleDB for this node's metric data
        query = db.query(MetricValue).filter(
            MetricValue.node_id == node_id,
            MetricValue.metric_id == metric_id,
            MetricValue.time >= start_dt,
            MetricValue.time <= end_dt
        ).order_by(MetricValue.time.asc()).limit(limit)
        
        raw_data = [
            {"time": r.time, "value": r.value}
            for r in query.all()
        ]
        
        # Interpolate to common grid
        interpolated = _interpolate_to_grid(raw_data, grid)
        
        # Format timestamps as ISO strings (normalize to UTC with Z suffix)
        formatted_data = []
        for pt in interpolated:
            ts = pt["time"]
            if hasattr(ts, 'isoformat'):
                # datetime object - convert to UTC and format
                ts_str = ts.isoformat()
                if ts_str.endswith('+00:00'):
                    ts_str = ts_str[:-6] + 'Z'
                elif not ts_str.endswith('Z'):
                    ts_str = ts_str + 'Z'
                formatted_data.append({"time": ts_str, "value": pt["value"]})
            else:
                # String already
                formatted_data.append({"time": str(pt["time"]), "value": pt["value"]})
        
        results.append({
            "node_id": node_id,
            "label": node_labels.get(node_id, node_id),
            "data": formatted_data
        })
    
    return results
