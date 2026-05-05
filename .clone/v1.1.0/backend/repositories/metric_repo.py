from sqlalchemy.orm import Session
from sqlalchemy import text, func
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from models.timescale_models import MetricValue

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

def insert_metric_value(db: Session, node_id: str, metric_id: str, value: float, timestamp: datetime = None):
    if timestamp is None:
        timestamp = datetime.utcnow()
    
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
    now = datetime.utcnow()
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
    start_time: str = None,
    end_time: str = None
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
             cutoff = datetime.utcnow() - timedelta(hours=hours)
             query = query.filter(MetricValue.time >= cutoff)
    else:
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        query = query.filter(MetricValue.time >= cutoff)
        
    results = query.order_by(MetricValue.time.asc()).limit(limit).all()
    
    return [{"time": r.time, "value": r.value} for r in results]

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
