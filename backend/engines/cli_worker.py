"""
CLI Engine Worker — SSH/Telnet polling with regex extraction.
Phase 2 of CLI Polling SDD.

Schedules poll_cli() every 10 seconds.
Fetches CLI metrics via paramiko SSH (or Telnet fallback on port 23),
executes configured commands, extracts values via regex, and emits
numeric metrics to TimescaleDB.
"""

import time
import os
import re
import schedule
import math
from datetime import datetime
from typing import Optional, Dict, Tuple

# Add root and backend to python path to verify imports work
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(os.path.join(os.path.dirname(__file__), '../backend'))

from neo4j import GraphDatabase
from repositories.metric_repo import insert_metric_value, bulk_insert_metrics
from postgres_db import SessionLocal

# Paramiko for SSH; socket for Telnet fallback
try:
    import paramiko
    PARAMIKO_AVAILABLE = True
except ImportError:
    PARAMIKO_AVAILABLE = False

# Connection
URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

driver = GraphDatabase.driver(URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

# ─── Connection ────────────────────────────────────────────────────────────────

def verify_connection():
    """Verify Neo4j connectivity. Blocks until available."""
    max_retries = 60
    for i in range(max_retries):
        try:
            driver.verify_connectivity()
            print("[CLI] Connected to Neo4j!")
            return
        except Exception as e:
            print(f"[CLI] Waiting for Neo4j... ({i+1}/{max_retries})")
            time.sleep(2)
    raise Exception("[CLI] Could not connect to Neo4j after multiple retries")


# ─── Credential Resolution ───────────────────────────────────────────────────

def resolve_credential(cli_credential_ref: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Resolve username and password from a cli_credential_ref.
    The ref is an env key name that points to a "DEVICE_USER" style entry,
    which is resolved as: {ref}_USER and {ref}_PASS.
    Falls back to CLI_DEFAULT_* if specific ref not set.
    """
    if not cli_credential_ref:
        cli_credential_ref = "CLI_DEFAULT"

    username = os.getenv(f"{cli_credential_ref}_USER")
    password = os.getenv(f"{cli_credential_ref}_PASS")

    if not username:
        username = os.getenv("CLI_DEFAULT_USER")
    if not password:
        password = os.getenv("CLI_DEFAULT_PASS")

    return username, password


# ─── Escalation ──────────────────────────────────────────────────────────────

def apply_escalation(client, escalation_script: Optional[str]) -> bool:
    """
    Apply privilege escalation by sending commands from escalation_script.
    Each line is sent as a separate command.
    Returns True if escalation appears successful (no error detected).
    """
    if not escalation_script:
        return True

    commands = [c.strip() for c in escalation_script.split('\n') if c.strip()]
    for cmd in commands:
        # Read any pending output first
        if client.recv_ready():
            client.recv(65535)
        client.send(cmd + '\r')
        time.sleep(1)

    # Check for privilege prompt (enable mode typically ends with #)
    try:
        client.settimeout(3)
        output = client.recv(4096).decode('utf-8', errors='ignore')
        # Simple heuristic: if we see '#' prompt, we're in privileged mode
        if '#' in output or 'configure' in output.lower():
            return True
        return False
    except Exception:
        return False


# ─── CLI Fetch ────────────────────────────────────────────────────────────────

def fetch_cli_value(metric_def: dict, node: dict) -> Tuple[Optional[str], Optional[str]]:
    """
    Connect to a network device via SSH (preferred) or Telnet (fallback),
    optionally apply escalation, execute the CLI command, and return
    (raw_output, error_message).

    metric_def: dict with keys: cli_command, cli_target, cli_credential_ref,
                cli_escalation_script, cli_protocol, cli_timeout, cli_value_extractor
    node: dict with keys: ip, label (for logging)

    Returns (raw_output, None) on success or (None, error_string) on failure.
    """
    if not PARAMIKO_AVAILABLE:
        return None, "paramiko not installed"

    ip = node.get('ip')
    if not ip:
        return None, "No IP address for node"

    cli_protocol = (metric_def.get('cli_protocol') or 'SSH').strip().upper()
    cli_timeout = metric_def.get('cli_timeout', 30)
    cli_command = metric_def.get('cli_command', '')
    cli_target = metric_def.get('cli_target', '')
    cli_credential_ref = metric_def.get('cli_credential_ref')
    cli_escalation_script = metric_def.get('cli_escalation_script')

    # Build full command if cli_target is set
    if cli_target and '{target}' in cli_command:
        print(f"[CLI] {node.get('label', ip)}: both cli_target and {{target}} in cli_command — using replacement only")
        command = cli_command.replace('{target}', cli_target)
    elif cli_target:
        command = f"{cli_command} {cli_target}"
    else:
        command = cli_command

    username, password = resolve_credential(cli_credential_ref)

    if not username or not password:
        return None, "No credentials resolved"

    raw_output = None
    error_msg = None

    # Try SSH first
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        if cli_protocol != 'Telnet':
            try:
                client.connect(
                    ip,
                    port=22,
                    username=username,
                    password=password,
                    timeout=cli_timeout,
                    look_for_keys=False,
                    allow_agent=False
                )
            except Exception as ssh_err:
                # SSH refused/timed out — try Telnet fallback
                error_msg = f"SSH failed ({ssh_err}), falling back to Telnet"
                print(f"[CLI] {node.get('label', ip)}: {error_msg}")
                client.close()
                client = None

                # Telnet fallback
                try:
                    import socket
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(cli_timeout)
                    sock.connect((ip, 23))
                    import telnetlib
                    tconn = telnetlib.Telnet()
                    tconn.sock = sock
                    tconn.read_until(b'login:', timeout=cli_timeout)
                    tconn.write(f"{username}\r".encode('utf-8'))
                    tconn.read_until(b'Password:', timeout=cli_timeout)
                    tconn.write(f"{password}\r".encode('utf-8'))
                    # Try to get to privileged mode
                    if cli_escalation_script:
                        tconn.read_until(b'>', timeout=cli_timeout)
                        for line in cli_escalation_script.split('\n'):
                            if line.strip():
                                tconn.write(f"{line.strip()}\r".encode('utf-8'))
                                time.sleep(1)
                    tconn.write(f"{command}\r".encode('utf-8'))
                    raw_output = tconn.read_all().decode('utf-8', errors='ignore')
                    tconn.close()
                    return raw_output, None
                except Exception as telnet_err:
                    return None, f"Telnet fallback also failed: {telnet_err}"

        # SSH connected — proceed
        if client:
            # Apply escalation if script is set
            if cli_escalation_script:
                escalation_timeout = min(3, (cli_timeout or 30) // 2)
                client.settimeout(escalation_timeout)
                escalation_ok = apply_escalation(client, cli_escalation_script)
                if not escalation_ok:
                    client.close()
                    return None, "Privilege escalation failed"

            # Execute command
            stdin, stdout, stderr = client.exec_command(command, timeout=cli_timeout)
            raw_output = stdout.read().decode('utf-8', errors='ignore')
            client.close()
            return raw_output, None

    except Exception as e:
        return None, f"Connection error: {e}"

    return None, "Unexpected exit path"


# ─── Regex Extraction ────────────────────────────────────────────────────────

# Keyword-to-numeric mapping as per spec
_KEYWORD_MAP = {
    'up': 1.0,
    'down': 0.0,
    'enabled': 1.0,
    'disabled': 0.0,
    'ok': 1.0,
    'error': 0.0,
    'fail': 0.0,
}


def extract_regex_value(raw_output: str, extractor: str) -> Tuple[Optional[str], Optional[float]]:
    """
    Apply a regex extractor to raw CLI output and return (extracted_value, numeric_value).

    Format: "regex:pattern" or "regex:pattern (group_index)"
    - Full match required; if no match, returns (None, None)
    - Capture groups supported; group index (1-based) can be specified in parentheses
    - Numeric mapping: keyword table → float, digit patterns → float, unknown → NaN

    Returns (extracted_str, numeric_float) or (None, float('nan')) on failure.
    """
    if not raw_output or not extractor:
        return None, float('nan')

    if not extractor.startswith('regex:'):
        return None, float('nan')

    pattern_str = extractor[6:]  # Strip 'regex:' prefix

    # Parse optional capture group: "pattern (group)" or "pattern(group)"
    capture_group = None
    m = re.search(r'\s*\((\d+)\)\s*$', pattern_str)
    if m:
        capture_group = int(m.group(1))
        pattern_str = pattern_str[:m.start()].strip()

    try:
        compiled = re.compile(pattern_str)
    except re.error:
        return None, float('nan')

    match = compiled.search(raw_output)
    if not match:
        return None, float('nan')

    # Extract captured group or full match
    if capture_group is not None:
        try:
            extracted = match.group(capture_group)
        except IndexError:
            return None, float('nan')
    else:
        if match.groups():
            extracted = match.group(1)
        else:
            extracted = match.group(0)

    if not extracted:
        return None, float('nan')

    # Numeric mapping
    extracted_lower = extracted.strip().lower()

    # Check keyword map first
    for keyword, num_val in _KEYWORD_MAP.items():
        if keyword in extracted_lower:
            return extracted, num_val

    # Digit pattern → float
    digit_m = re.match(r'^(\d+(?:\.\d+)?)$', extracted.strip())
    if digit_m:
        return extracted, float(digit_m.group(1))

    # Unknown string → NaN
    return extracted, float('nan')


# ─── NaN Rate Limiter ────────────────────────────────────────────────────────

# Track consecutive NaN misses per metric: metric_id -> consecutive_nan_count
_nan_tracker: Dict[str, int] = {}


def nan_rate_limiter(metric_id: str, value: float, raw_output: Optional[str], node_label: str):
    """
    Track consecutive NaN misses per metric. Delegates to check_nan_threshold.
    After 3 consecutive misses, an alert event is emitted to Neo4j and
    raw output is logged at WARNING level.
    """
    check_nan_threshold(metric_id, value, raw_output, node_label)


def check_nan_threshold(metric_id: str, value: float, raw_output: Optional[str], node_label: str):
    """Check if metric has hit 3 consecutive NaN misses; emit Neo4j alert event."""
    if math.isnan(value):
        count = _nan_tracker.get(metric_id, 0) + 1
        _nan_tracker[metric_id] = count
        if count >= 3:
            # Emit alert event to Neo4j
            try:
                with driver.session() as session:
                    session.run("""
                        MATCH (m:MetricDef {id: $mid})
                        CREATE (e:Event {
                            type: 'CLI_POLL_ALERT',
                            metric_id: $mid,
                            node_label: $node_label,
                            message: '3 consecutive NaN misses for CLI metric',
                            raw_output: $raw_output,
                            timestamp: datetime()
                        })
                        SET m.last_alert = datetime()
                    """, mid=metric_id, node_label=node_label, raw_output=raw_output or '')
            except Exception as e:
                print(f"[CLI] Failed to emit alert event: {e}")
            print(f"[CLI] WARNING: 3 consecutive NaN misses for metric {metric_id} on {node_label}.")
            if raw_output:
                print(f"[CLI] Raw output: {raw_output[:500]}")
    else:
        # Reset counter on successful poll
        _nan_tracker[metric_id] = 0


# ─── Poll CLI ────────────────────────────────────────────────────────────────

def poll_cli():
    """Main CLI polling cycle. Queries Neo4j for CLI metrics, fetches values, emits to TimescaleDB."""
    start_time = time.time()
    print(f"[{datetime.now().isoformat()}] Starting CLI Polling Cycle...")

    db = SessionLocal()
    metrics_to_save = []
    metrics_count = 0

    try:
        with driver.session() as session:
            result = session.run("""
                MATCH (n:CI)-[r:HAS_METRIC]->(m:MetricDef)
                WHERE m.protocol = 'CLI'
                WITH n, r, m,
                     coalesce(m.polling_interval, 60) as interval,
                     coalesce(r.last_polled, datetime({year:1970})) as last_p
                WHERE duration.between(last_p, datetime()).seconds >= interval
                RETURN n.id as node_id, n.ip as ip, n.label as node_label,
                       m.id as metric_id, m.cli_command as cli_command,
                       m.cli_target as cli_target,
                       m.cli_value_extractor as cli_value_extractor,
                       m.cli_credential_ref as cli_credential_ref,
                       m.cli_escalation_script as cli_escalation_script,
                       m.cli_protocol as cli_protocol,
                       m.cli_timeout as cli_timeout,
                       interval
            """)

            for record in result:
                metrics_count += 1
                node_id = record["node_id"]
                ip = record["ip"]
                node_label = record.get("node_label", node_id)
                metric_id = record["metric_id"]

                if not ip:
                    print(f"[CLI] Skipping {node_id}: No IP address.")
                    continue

                metric_def = {
                    'cli_command': record.get('cli_command'),
                    'cli_target': record.get('cli_target'),
                    'cli_value_extractor': record.get('cli_value_extractor'),
                    'cli_credential_ref': record.get('cli_credential_ref'),
                    'cli_escalation_script': record.get('cli_escalation_script'),
                    'cli_protocol': record.get('cli_protocol', 'SSH'),
                    'cli_timeout': record.get('cli_timeout', 30) or 30,
                }

                node_dict = {'ip': ip, 'label': node_label}

                raw_output, error = fetch_cli_value(metric_def, node_dict)

                if error:
                    print(f"[CLI] {node_label}/{metric_id}: {error}")
                    # Emit NaN for fetch errors
                    value = float('nan')
                    extracted_value = None
                    metrics_to_save.append({
                        "node_id": node_id,
                        "metric_id": metric_id,
                        "value": value,
                        "time": datetime.utcnow()
                    })
                    nan_rate_limiter(metric_id, value, raw_output, node_label)
                    continue

                if not raw_output:
                    print(f"[CLI] {node_label}/{metric_id}: Empty output")
                    value = float('nan')
                    metrics_to_save.append({
                        "node_id": node_id,
                        "metric_id": metric_id,
                        "value": value,
                        "time": datetime.utcnow()
                    })
                    nan_rate_limiter(metric_id, value, None, node_label)
                    continue

                # Extract value via regex
                extractor = record.get('cli_value_extractor', 'regex:(.*)')
                extracted_value, value = extract_regex_value(raw_output, extractor)

                print(f"[CLI] {node_label}/{metric_id}: raw={raw_output[:80].strip()!r} → extracted={extracted_value!r}, value={value}")

                metrics_to_save.append({
                    "node_id": node_id,
                    "metric_id": metric_id,
                    "value": value,
                    "time": datetime.utcnow()
                })

                nan_rate_limiter(metric_id, value, raw_output, node_label)

                # Update last_polled
                session.run("""
                    MATCH (n:CI {id: $nid})-[r:HAS_METRIC]->(m:MetricDef {id: $mid})
                    SET r.last_polled = datetime()
                """, nid=node_id, mid=metric_id)

        if metrics_to_save:
            bulk_insert_metrics(db, metrics_to_save)
            print(f"[{datetime.now().isoformat()}] CLI: saved {len(metrics_to_save)} metrics to TimescaleDB.")

        duration = time.time() - start_time
        if metrics_count > 0:
            print(f"[{datetime.now().isoformat()}] CLI Cycle Complete: {metrics_count} metrics in {duration:.2f}s.")

    except Exception as e:
        print(f"[CLI] Error during CLI polling cycle: {e}")
    finally:
        db.close()


# ─── Job Wrapper + Schedule ───────────────────────────────────────────────────

def job():
    """Scheduled job wrapper around poll_cli()."""
    try:
        poll_cli()
    except Exception as e:
        print(f"[CLI] Error in CLI polling job: {e}")


# ─── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("[CLI] NEX-GEN CLI Engine Starting...")
    if not PARAMIKO_AVAILABLE:
        print("[CLI] WARNING: paramiko not found. CLI polling will be unavailable.")
    verify_connection()
    print("[CLI] Engine Running. Waiting for scheduled tasks...")
    schedule.every(10).seconds.do(job)
    while True:
        schedule.run_pending()
        time.sleep(1)