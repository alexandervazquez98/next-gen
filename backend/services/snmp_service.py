import asyncio
import time
from datetime import datetime
import json
import logging
import subprocess
from database import get_db

# Configure Logging
logger = logging.getLogger(__name__)

# Try to import PySNMP (Optional Dependency)
# Try to import PySNMP (Optional Dependency)
try:
    from pysnmp.hlapi import getCmd, SnmpEngine, CommunityData, UdpTransportTarget, ContextData, ObjectType, ObjectIdentity
    SNMP_AVAILABLE = True
except ImportError:
    SNMP_AVAILABLE = False
    logger.warning("PySNMP not installed. SNMP features will be disabled.")
COLLECTOR_STATUS = "STOPPED"
GLOBAL_STATS = {
    "cis_monitored": 0,
    "metrics_collected": 0,
    "metrics_failed": 0,
    "cycle_duration": 0.0,
    "jobs_per_min": 0.0
}

def get_collector_status():
    return {
        "last_run": LAST_COLLECTION_TIME,
        "status": COLLECTOR_STATUS,
        "stats": GLOBAL_STATS
    }

async def snmp_collector_loop():
    """
    Background task to poll CIs based on their pollingInterval and applicable metrics.
    Runs indefinitely in the background.
    """
    if not SNMP_AVAILABLE:
        logger.warning("SNMP Collector disabled due to missing pysnmp.")
        return

    global LAST_COLLECTION_TIME, COLLECTOR_STATUS
    
    driver = get_db()
    COLLECTOR_STATUS = "RUNNING"
    
    while True:
        try:
            logger.info("[Collector] Starting Poll Cycle (Thread Offload)...")
            start_time = time.time()
            
            # Offload the entire blocking cycle to a separate thread
            stats = await asyncio.to_thread(run_snmp_cycle_sync, driver)

            elapsed = time.time() - start_time
            LAST_COLLECTION_TIME = datetime.now().isoformat()
            
            # Update Global Stats
            GLOBAL_STATS["cycle_duration"] = round(elapsed, 2)
            GLOBAL_STATS["cis_monitored"] = stats.get("cis", 0)
            GLOBAL_STATS["metrics_collected"] = stats.get("total", 0)
            GLOBAL_STATS["metrics_failed"] = stats.get("errors", 0)
            
            # Calculate Throughput (Metrics per minute equivalent)
            if elapsed > 0:
                GLOBAL_STATS["jobs_per_min"] = round((stats.get("total", 0) / elapsed) * 60, 1)

            logger.info(f"[Collector] Cycle finished in {elapsed:.2f}s. Stats: {GLOBAL_STATS}")
            
            # Simple fixed sleep (Demo Mode)
            await asyncio.sleep(60) 
            
        except Exception as e:
             logger.error(f"[Collector] Critical Loop Error: {e}", exc_info=True)
             COLLECTOR_STATUS = "ERROR"
             await asyncio.sleep(10)

def run_snmp_cycle_sync(driver):
    """
    Synchronous wrapper for the polling cycle to run in a thread.
    """
    with driver.session() as session:
        # 1. Fetch Candidates (Relaxed: Allow CIs without SNMP if they have IP)
        cis_result = session.run("""
            MATCH (n:CI) 
            WHERE n.ip IS NOT NULL AND n.status <> 'EXCEPTION'
            RETURN n
        """)
        cis = [dict(record["n"]) for record in cis_result]
        logger.info(f"[Collector] Found {len(cis)} candidate CIs for monitoring.")
        
        # 2. Fetch Metric Definitions
        metrics_result = session.run("MATCH (m:MetricDef) RETURN m")
        metrics = []
        for record in metrics_result:
            m = dict(record["m"])
            criteria = {}
            if m.get("applicable_to"):
                try: criteria = json.loads(m.get("applicable_to"))
                except: pass
            
            metrics.append({
                "id": m.get("id"),
                "name": m.get("name") or m.get("id"),
                "oid": m.get("oid"),
                "protocol": m.get("protocol"),
                "criticality": m.get("criticality", 1),
                "warning": m.get("warning"),
                "critical": m.get("critical"),
                "applicable_to": criteria
            })

    # 3. Process Each Node
    logger.info(f"[Collector] Processing {len(cis)} Nodes vs {len(metrics)} MetricDefs...")
    
    total_metrics = 0
    total_errors = 0
    
    for ci in cis:
        # Debug Log for individual CI processing
        # logger.debug(f"[Collector] Checking CI: {ci.get('name')} ({ci.get('ip')})")
        t, e = process_ci_metrics(ci, metrics, driver)
        total_metrics += t
        total_errors += e
        
    return {"cis": len(cis), "total": total_metrics, "errors": total_errors}

def process_ci_metrics(ci, metrics, driver):
    """
    Evaluates which metrics apply to the CI and executes them.
    Returns (total_executed, total_errors)
    """
    # Parse SNMP config
    snmp_conf = {}
    snmp_raw = ci.get("snmp")
    if snmp_raw:
        try:
            snmp_conf = json.loads(snmp_raw)
        except:
             try:
                 import ast
                 snmp_conf = ast.literal_eval(snmp_raw)
             except: pass
    
    # Validation for SNMP only (skip if ICMP/API)
    # But we can't skip entirely if we have ICMP metrics.
    # Refactor: Only require SNMP conf if we have SNMP metrics to run.
    
    # Determine applicable metrics
    ci_brand = ci.get("brand", "").lower() if ci.get("brand") else ""
    ci_model = ci.get("model", "").lower() if ci.get("model") else ""
    ci_layer = ci.get("layer", "").lower() if ci.get("layer") else ""
    
    target_metrics = []
    for m in metrics:
        crit = m["applicable_to"]
        match = True
        if crit:
            if match and crit.get("names") and ci.get("name") not in crit["names"]: match = False
            if match and crit.get("brands") and ci_brand not in [b.lower() for b in crit["brands"]]: match = False
            if match and crit.get("models") and ci_model not in [mod.lower() for mod in crit["models"]]: match = False
            if match and crit.get("layers") and ci_layer not in [l.lower() for l in crit["layers"]]: match = False
        
        # Only add if match AND (OID exists OR Protocol is ICMP)
        if match:
             if m.get("oid") or m.get("protocol") == 'ICMP':
                  target_metrics.append(m)
             else:
                  pass # logger.warning(f"Metric Match but missing OID/Protocol: {m.get('name')}")
        else:
             pass # logger.debug(f"Metric {m.get('name')} mismatch for {ci.get('name')}")

    # Execute Polls
    executed = 0
    errors = 0
    
    for tm in target_metrics:
        try:
            executed += 1
            # Check SNMP prerequisites if needed
            if tm.get("protocol") == 'SNMP' and (not snmp_conf or not snmp_conf.get("readCommunity")):
                 # logger.warning(f"[Collector] Skipping SNMP metric {tm.get('name')} for {ci.get('name')} (No Community String)")
                 continue
            
            # logger.debug(f"[Collector] Polling {tm.get('name')} for {ci.get('name')}...")
            val, status, err_msg = poll_metric(ci, tm, snmp_conf)
            # logger.debug(f"[Collector] Poll Result: {val}, {status}")
            
            # Always store result
            store_metric_result(ci, tm, val, status, err_msg, driver)
            
        except Exception as e:
            errors += 1
            logger.error(f"[Collector] Error processing metric {tm.get('name')} for {ci.get('name')}: {e}", exc_info=True)
            
    return (executed, errors)

def poll_metric(ci, metric_def, snmp_conf):
    """
    Executes the actual poll (ICMP or SNMP).
    Returns (value, status, error_message).
    Status: 'OK', 'TIMEOUT', 'ERROR'
    """
    proto = str(metric_def.get("protocol", "")).upper().strip()
    
    # 1. ICMP PING
    if proto == 'ICMP':
        import platform
        # Detect OS for correct Ping Flag
        param = '-n' if platform.system().lower() == 'windows' else '-c'
        
        command = ['ping', param, '1', ci.get("ip")]
        logger.debug(f"[Collector] Executing ICMP: {' '.join(command)}")
        try:
            # 0 = Success (UP), 1 = Fail (DOWN)
            res = subprocess.call(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if res == 0:
                return (1, 'OK', None)
            else:
                return (0, 'OK', None) # Valid result, value is 0 (Down)
        except Exception as e:
            logger.error(f"PING Exception for {ci.get('ip')}: {e}")
            return (0, 'ERROR', str(e))
    
    # 2. SNMP
    elif metric_def.get("oid") and metric_def.get("oid") != 'ICMP' and SNMP_AVAILABLE:
        try:
            oid = metric_def["oid"]
            # logger.debug(f"[Collector] SNMP GET {oid} from {ci.get('ip')}...")
            
            errorIndication, errorStatus, errorIndex, varBinds = next(
                getCmd(SnmpEngine(),
                    CommunityData(snmp_conf.get("readCommunity")),
                    UdpTransportTarget((ci.get("ip"), snmp_conf.get("port", 161)), timeout=1.0, retries=0),
                    ContextData(),
                    ObjectType(ObjectIdentity(oid)))
            )
            
            if errorIndication:
                logger.warning(f"[Collector] SNMP Timeout for {ci.get('name')} (OID: {oid}): {errorIndication}")
                return (None, 'TIMEOUT', str(errorIndication))
            elif errorStatus:
                err = f"{errorStatus.prettyPrint()} at {errorIndex and varBinds[int(errorIndex) - 1][0] or '?'}"
                logger.error(f"[Collector] SNMP Error for {ci.get('name')} (OID: {oid}): {err}")
                return (None, 'ERROR', err)
            else:
                val = str(varBinds[0][1])
                # logger.debug(f"[Collector] SNMP Success {ci.get('name')} (OID: {oid}): {val}")
                return (val, 'OK', None)
                
        except Exception as snmp_err:
            logger.error(f"SNMP Error {ci.get('id')}: {snmp_err}")
            return (None, 'ERROR', str(snmp_err))
    
    return (None, 'ERROR', 'Unknown Protocol or OID')

def store_metric_result(ci, metric_def, val, poll_status, err_msg, driver):
    """
    Stores the metric result and triggers event logic.
    """
    # 1. Resolve Criticality to Severity
    # 1 -> INFO, 2 -> WARNING, 3 -> CRITICAL (Exception)
    crit_level = metric_def.get("criticality", 1) # Default Info
    base_severity = 'INFO'
    if crit_level == 2: base_severity = 'WARNING'
    if crit_level == 3: base_severity = 'CRITICAL'

    # Default State
    status = 'OK'
    severity = 'INFO' # For the event
    is_breach = False
    message = f"Metric {metric_def.get('name', metric_def['id'])} is OK. Value: {val}"
    
    # 1. Handle Poll Failures (Timeout/Error)
    if poll_status != 'OK':
        status = 'CRITICAL'
        severity = base_severity # Use the metric's criticality level for the alert
        is_breach = True
        message = f"Metric Collection Failed: {err_msg or 'Timeout'}"
        val = "N/A"
    
    # 2. Handle Threshold Validations (If Poll OK)
    elif val is not None:
        try:
            # Normalize Value
            num_val = float(val)
            
            # Check Critical
            # EXCLUDE ICMP and Availability Checks (mariadb-GS) from generic '>=' checks.
            # For these, 1=GOOD (UP) and 0=BAD (DOWN).
            is_availability_metric = metric_def.get("protocol") == 'ICMP' or metric_def.get("name") == 'mariadb-GS'
            
            if not is_availability_metric:
                if metric_def.get("critical") is not None and num_val >= float(metric_def["critical"]):
                    status = 'CRITICAL'
                    severity = 'CRITICAL'
                    is_breach = True
                    message = f"Critical Threshold Breached: {val} >= {metric_def['critical']}"
                
                # Check Warning (Only if not already Critical)
                elif metric_def.get("warning") is not None and num_val >= float(metric_def["warning"]):
                    status = 'WARNING'
                    severity = 'WARNING'
                    is_breach = True
                    message = f"Warning Threshold Breached: {val} >= {metric_def['warning']}"
                
            # SPECIAL CASE: ICMP/Availability (1=UP, 0=DOWN)
            if is_availability_metric and float(val) == 0:
                 status = 'CRITICAL'
                 severity = base_severity # Use mapped criticality (e.g. Exception/Level 3)
                 is_breach = True
                 message = f"Service/Host Down: {metric_def.get('name')}"
                 
        except ValueError:
            # String Value Comparison logic could go here
            pass

    with driver.session() as session:
        # 1. Store Raw Result (History)
        session.run("""
            MATCH (n:CI {id: $nid})
            MATCH (m:MetricDef {id: $mid})
            MERGE (n)-[r:HAS_METRIC]->(m)
            SET r.last_value = $val, r.last_updated = datetime(), r.status = $status, r.last_message = $msg
            
            CREATE (res:MetricResult {
                timestamp: datetime(), 
                value: $val,
                status: $status
            })
            CREATE (n)-[:HAS_RESULT]->(res)
            CREATE (res)-[:FOR_METRIC]->(m)
        """, nid=ci.get("id"), mid=metric_def["id"], val=str(val), status=status, msg=message)
        
        # logger.info(f"[Collector] Stored Metric for {ci.get('name')}: {metric_def.get('name')} = {val} ({status})")

        # 2. Event Management Logic
        if is_breach:
            # Upsert OPEN Event
            session.run("""
                MATCH (n:CI {id: $nid})
                MATCH (m:MetricDef {id: $mid})
                
                OPTIONAL MATCH (existing:Event)
                WHERE existing.ci_id = $nid AND existing.metric_id = $mid AND existing.status IN ['OPEN', 'ACK']
                
                FOREACH (ignoreMe IN CASE WHEN existing IS NULL THEN [1] ELSE [] END | 
                    CREATE (e:Event {
                        id: randomUUID(),
                        ci_id: $nid,
                        metric_id: $mid,
                        status: 'OPEN',
                        severity: $sev,
                        message: $msg,
                        created_at: datetime(),
                        last_seen: datetime(),
                        ack: false
                    })
                    MERGE (n)-[:HAS_EVENT]->(e)
                    MERGE (e)-[:TRIGGERED_BY]->(m)
                )
                
                FOREACH (ignoreMe IN CASE WHEN existing IS NOT NULL THEN [1] ELSE [] END | 
                    SET existing.last_seen = datetime(),
                        existing.message = $msg,
                        existing.severity = $sev
                )
            """, nid=ci.get("id"), mid=metric_def["id"], val=str(val), sev=severity, msg=message)
        
        else:
            # Recovery Logic
            session.run("""
                MATCH (n:CI {id: $nid})-[:HAS_EVENT]->(e:Event {metric_id: $mid})
                WHERE e.status IN ['OPEN', 'ACK']
                SET e.status = 'RECOVERED', e.recovered_at = datetime(), e.message = $msg
            """, nid=ci.get("id"), mid=metric_def["id"], msg=message)

def run_diagnostic(ci, metric):
    """
    Runs an on-demand diagnostic based on protocol.
    Returns the diagnostic message.
    """
    protocol = metric.get("protocol")
    diag_msg = ""
    
    if protocol == 'ICMP':
        try:
            # Run ping count 3
            process = subprocess.Popen(['ping', '-c', '3', ci.get("ip")], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = process.communicate()
            
            if process.returncode == 0:
                 diag_msg = f"[SUCCESS] PING CHECK PASSED\nOutput:\n{stdout.decode()}"
            else:
                 diag_msg = f"[FAILED] PING CHECK FAILED\nError:\n{stderr.decode() or stdout.decode()}"
        except Exception as e:
            diag_msg = f"[ERROR] Diagnostic Error: {str(e)}"
            
    elif protocol == 'SNMP':
         diag_msg = f"[INFO] SNMP Diagnostic initiated for OID {metric.get('oid')}. \n(Verify connectivity manually to {ci.get('ip')})"
    else:
         diag_msg = f"[INFO] No automated diagnostic available for protocol {protocol}"

    return diag_msg

def validate_snmp_oid(ip, community, oid, port=161):
    """
    Validates an SNMP OID against a target IP.
    Returns dict with success status and value/type.
    """
    if not SNMP_AVAILABLE:
        return {"success": False, "error": "PySNMP not installed"}

    try:
        errorIndication, errorStatus, errorIndex, varBinds = next(
            getCmd(SnmpEngine(),
                CommunityData(community),
                UdpTransportTarget((ip, port), timeout=2.0, retries=1),
                ContextData(),
                ObjectType(ObjectIdentity(oid)))
        )

        if errorIndication:
            return {"success": False, "error": str(errorIndication)}
        elif errorStatus:
             return {"success": False, "error": f"{errorStatus.prettyPrint()} at {errorIndex and varBinds[int(errorIndex) - 1][0] or '?'}"}
        else:
            # Success - Analyze type
            vb = varBinds[0]
            val = vb[1]
            val_type = type(val).__name__
            pretty_val = str(val)
            
            # Simple heuristic mapping
            dtype = "STRING"
            if "Integer" in val_type or "Gauge" in val_type or "Counter" in val_type:
                dtype = "INTEGER"
            elif "Float" in val_type:
                dtype = "FLOAT"
            
            return {
                "success": True, 
                "value": pretty_val, 
                "detectedType": dtype, 
                "rawType": val_type
            }
    except Exception as e:
        return {"success": False, "error": str(e)}
