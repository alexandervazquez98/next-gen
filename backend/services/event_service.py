from typing import List, Dict, Any, Optional
from database import get_db
from fastapi import HTTPException
from services.snmp_service import run_diagnostic

def get_events(status: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Fetch system events filtered by status.
    """
    driver = get_db()
    with driver.session() as session:
        query = """
            MATCH (e:Event)<-[:HAS_EVENT]-(ci:CI)
            MATCH (e)-[:TRIGGERED_BY]->(m:MetricDef)
            WHERE ($status IS NULL OR e.status = $status OR ($status = 'ACTIVE' AND e.status IN ['OPEN', 'ACK', 'RECOVERED']))
            RETURN e, ci.label as ci_name, m.id as metric_name, m.protocol as metric_protocol
            ORDER BY e.created_at DESC
            LIMIT 100
        """
        result = session.run(query, status=status)
        events = []
        for record in result:
            evt = dict(record["e"])
            for k, v in evt.items():
                 if hasattr(v, 'isoformat'): evt[k] = v.isoformat()
            
            evt["ci_name"] = record["ci_name"]
            evt["metric_name"] = record["metric_name"]
            evt["metric_protocol"] = record["metric_protocol"]
            events.append(evt)
        return events

def get_related_events(ci_id: str) -> List[Dict[str, Any]]:
    """
    Fetch all ACTIVE (OPEN, ACK) events for a specific CI.
    """
    driver = get_db()
    with driver.session() as session:
        result = session.run("""
            MATCH (e:Event)-[:TRIGGERED_BY]->(m:MetricDef)
            WHERE e.ci_id = $ci_id AND e.status IN ['OPEN', 'ACK']
            RETURN e, m.name as metric_name
            ORDER BY e.severity DESC, e.created_at DESC
        """, ci_id=ci_id)
        
        events = []
        for record in result:
            evt = dict(record["e"])
            # Format datetime objects
            if hasattr(evt.get("created_at"), 'iso_format'):
                 evt["created_at"] = evt["created_at"].iso_format()
            if hasattr(evt.get("last_seen"), 'iso_format'):
                 evt["last_seen"] = evt["last_seen"].iso_format()
                 
            evt["metric_name"] = record["metric_name"]
            events.append(evt)
            
        return events

def ack_event(event_id: str, user: str) -> Dict[str, str]:
    driver = get_db()
    with driver.session() as session:
        session.run("""
            MATCH (e:Event {id: $eid})
            SET e.status = 'ACK', e.ack = true, e.ack_at = datetime(), e.ack_by = $user
        """, eid=event_id, user=user)
    return {"message": "Event Acknowledged"}

def close_event(event_id: str, user: str) -> Dict[str, str]:
    driver = get_db()
    with driver.session() as session:
        session.run("""
            MATCH (e:Event {id: $eid})
            SET e.status = 'CLOSED', e.closed_at = datetime(), e.closed_by = $user
        """, eid=event_id, user=user)
    return {"message": "Event Closed"}

def add_event_comment(event_id: str, user: str, message: str) -> Dict[str, str]:
    driver = get_db()
    with driver.session() as session:
        session.run("""
            MATCH (e:Event {id: $eid})
            SET e.comments = coalesce(e.comments, []) + ($user + ': ' + $msg + ' (' + toString(datetime()) + ')')
        """, eid=event_id, user=user, msg=message)
    return {"message": "Comment added"}

def prune_recovered_events(user: str) -> Dict[str, Any]:
    driver = get_db()
    with driver.session() as session:
        result = session.run("""
            MATCH (e:Event)
            WHERE e.status = 'RECOVERED' 
              AND (e.ack IS NULL OR e.ack = false)
              AND (e.comments IS NULL OR size(e.comments) = 0)
            SET e.status = 'CLOSED', e.closed_at = datetime(), e.closed_by = $user
            RETURN count(e) as closed_count
        """, user=user).single()
    return {"message": f"Cleaned up {result['closed_count']} events", "count": result['closed_count']}

def run_event_diagnostic(event_id: str, user: str) -> Dict[str, str]:
    """
    Run an on-demand diagnostic (Ping/SNMP) for the CI related to this event.
    """
    driver = get_db()
    with driver.session() as session:
        result = session.run("""
            MATCH (e:Event {id: $eid})<-[:HAS_EVENT]-(ci:CI)
            MATCH (e)-[:TRIGGERED_BY]->(m:MetricDef)
            RETURN ci, m
        """, eid=event_id).single()
        
        if not result:
            raise HTTPException(status_code=404, detail="Event not found")
            
        ci = dict(result["ci"])
        metric = dict(result["m"])
        
        # Call Service (imported from snmp_service)
        diag_msg = run_diagnostic(ci, metric)
        
        # Save Result
        final_msg = f"DIAGNOSTIC RUN BY {user}:\n{diag_msg}"
        session.run("""
            MATCH (e:Event {id: $eid})
            SET e.comments = coalesce(e.comments, []) + ($msg + ' (' + toString(datetime()) + ')')
        """, eid=event_id, msg=final_msg)
        
    return {"message": "Diagnostic run", "result": diag_msg}
