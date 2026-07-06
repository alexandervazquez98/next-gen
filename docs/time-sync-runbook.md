# Time Sync Runbook

`/api/system/status.time_sync` reports backend-vs-Neo4j clock skew. Use this runbook when the status is `WARNING`, `CRITICAL`, or `UNKNOWN`.

## Quick path

1. Verify host clock synchronization on every Docker host.
2. Fix NTP, chrony, or systemd-timesyncd at the host level.
3. Recheck `/api/system/status.time_sync` after the services inherit the corrected host time.

## Status guide

| Status | Meaning | Default threshold |
|--------|---------|-------------------|
| `OK` | Backend and Neo4j clocks are below the warning threshold. | `< 1000 ms` |
| `WARNING` | Clock skew can affect event/history interpretation. | `>= 1000 ms` |
| `CRITICAL` | Clock skew is severe and should be remediated immediately. | `>= 5000 ms` |
| `UNKNOWN` | The backend could not query or parse Neo4j time. | Not applicable |

## Host verification

Run the checks on the host, not inside the application containers.

### systemd-timesyncd

```bash
timedatectl status
timedatectl timesync-status
sudo systemctl status systemd-timesyncd
```

If sync is disabled, enable it and restart the service:

```bash
sudo timedatectl set-ntp true
sudo systemctl restart systemd-timesyncd
```

### chrony

```bash
chronyc tracking
chronyc sources -v
sudo systemctl status chronyd
```

If chrony is unhealthy, verify configured sources and restart it:

```bash
sudo systemctl restart chronyd
chronyc tracking
```

### NTP daemon

```bash
ntpq -p
sudo systemctl status ntp
```

If peers are unreachable, fix network/DNS/firewall access to the configured time sources and restart NTP:

```bash
sudo systemctl restart ntp
ntpq -p
```

## Container expectations

Containers inherit the host clock. `TZ=UTC` controls timezone/display consistency only; it does not synchronize time. This project does not require or prescribe privileged in-container NTP, chrony, or systemd management.

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `TZ` | `UTC` | Keeps container timezone display consistent. |
| `TIME_SYNC_MODE` | `host` | Documents that host-level clock sync is expected. |
| `TIME_SYNC_WARNING_MS` | `1000` | Warning skew threshold for `/api/system/status.time_sync`. |
| `TIME_SYNC_CRITICAL_MS` | `5000` | Critical skew threshold for `/api/system/status.time_sync`. |
| `TIME_SYNC_QUERY_TIMEOUT_S` | `1` | Short Neo4j time-query transaction timeout; timeouts report `UNKNOWN` without changing service health fields. |
