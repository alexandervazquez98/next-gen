# CLI Regex Extractor Manual

## Overview

The CLI Polling system extracts numeric values from raw CLI command output using a regex-based extractor. This document covers the format, syntax, and worked examples.

---

## Extractor Format

Every metric that uses the CLI protocol requires a `cli_value_extractor` string. The format is:

```
regex:<pattern>
```

or with an explicit capture group:

```
regex:<pattern> (group_index)
```

- The `regex:` prefix is **required** — without it, the extractor returns `NaN`.
- The pattern follows Python `re` syntax (PCRE-style).
- Capture groups are written with parentheses `(...)`.
- The group index is **1-based** (group 1 = first capturing group).

---

## How Extraction Works

1. The raw CLI output string is searched with the regex pattern.
2. If no match is found → `extracted_value = None`, `numeric_value = NaN`.
3. If a match is found:
   - Without explicit `(group_index)`: uses `match.group(1)` if groups exist, else `match.group(0)` (full match).
   - With explicit `(group_index)`: uses `match.group(group_index)`.
4. The extracted string is then mapped to a numeric value.

---

## Numeric Mapping Table

The extracted string is mapped to a float using this priority order:

| Keyword (substring match, case-insensitive) | Numeric Value |
|---|---|
| `up` | `1.0` |
| `down` | `0.0` |
| `enabled` | `1.0` |
| `disabled` | `0.0` |
| `ok` | `1.0` |
| `error` | `0.0` |
| `fail` | `0.0` |

> ⚠️ **IMPORTANTE:** El matching de keywords es por **substring**, no por palabra completa. Ejemplo: `setup` contiene `up` → `1.0` | `shutdown` contiene `down` → `0.0`. Para evitar falsos positivos, usa regex con word boundaries: `regex:\bup\b`

If no keyword matches, the system checks for a digit pattern:

| Pattern | Example Match | Numeric Value |
|---|---|---|
| Integer | `45` → `45` | `45.0` |
| Decimal | `73.5` → `73.5` | `73.5` |

If neither a keyword nor a digit pattern matches → `NaN`.

---

## Capture Group Syntax

Python regex capture groups are written with parentheses. The full match is always `group(0)`.

```
regex:is (up|down)       → uses group(1): "up" or "down"  → keyword mapping applies
regex:load (\d+)         → uses group(1): "45"            → digit pattern → 45.0
regex:load (\d+) (2)     → uses group(2): second capture group
```

**Without an explicit group index**, the extractor prefers `group(1)` if the pattern has any capturing groups. This means:

```
regex:Description: (\w+)      → extracts group(1) e.g. "FastEthernet0/1"
regex:Description: \w+        → extracts group(0) (full match) → no group(1) exists
```

---

## Common Gotchas

1. **Missing `regex:` prefix** — The extractor returns `NaN` if the string doesn't start with `regex:`.
2. **Case sensitivity** — Keyword matching is case-insensitive (`UP`, `Up`, `up` all work).
3. **Substring keyword match** — Keywords match if they appear anywhere in the extracted string. `setup` contains `up` → maps to `1.0`.
4. **Empty capture group** — If `match.group(1)` is an empty string, returns `NaN`.
5. **Invalid regex** — Malformed patterns (unbalanced parens, etc.) return `NaN`.
6. **`(group_index)` vs regex groups** — The `(group_index)` notation is **outside** the regex pattern, appended after a space. `regex:foo (1)` means "group 1 of the match".
7. **Non-numeric strings without keywords** — `FastEthernet0/1` → `NaN` (no keyword, no digit pattern).

---

## Worked Examples

### 1. Interface Status (`up`/`down`)

**Raw output:**
```
GigabitEthernet0/0 is up
```

**Extractor:** `regex:is (up|down)`

**Steps:**
1. Search `GigabitEthernet0/0 is up` for `is (up|down)` → match at "is up"
2. Capture group 1 = `"up"`
3. `"up"` matches keyword `up` → `1.0`

**Result:** `extracted_value = "up"`, `numeric_value = 1.0`

---

### 2. Load Percentage (digits)

**Raw output:**
```
5 minute load: 45%
CPU utilization: 73.5 percent
```

**Extractors:**
- `regex:load: (\d+)` → captures `"45"` → digit pattern → `45.0`
- `regex:utilization: ([\d.]+)` → captures `"73.5"` → digit pattern → `73.5`

---

### 3. Error Count

**Raw output:**
```
Checks: 3 failures detected in last 60 seconds
```

**Extractor:** `regex:(\d+) failures`

**Steps:**
1. Match captures `"3"` (group 1)
2. `"3"` matches digit pattern → `3.0`

**Result:** `numeric_value = 3.0`

---

### 4. Memory Usage

**Raw output:**
```
Memory Usage: Total: 8192MB, Used: 4096MB, Free: 4096MB
```

**Extractor:** `regex:Used: (\d+)MB`

**Steps:**
1. Capture group = `"4096"`
2. Digit pattern → `4096.0`

---

### 5. Interface Administrative Status

**Raw output:**
```
GigabitEthernet0/0 administrative state is enabled, operational state is up
```

**Extractor:** `regex:administrative state is (\w+)`

**Steps:**
1. Capture group = `"enabled"`
2. Keyword `enabled` → `1.0`

---

### 6. Fallback to Full Match (no groups)

**Raw output:**
```
Link: up
```

**Extractor:** `regex:Link: \w+`

**Steps:**
1. Match = `"Link: up"`
2. No capture groups → uses `match.group(0)` = `"Link: up"`
3. `"Link: up"` contains keyword `up` → `1.0`

---

### 7. Capture Group 2 (multiple groups)

**Raw output:**
```
ip: 10.0.0.1, mask: 255.255.255.0
```

**Extractor:** `regex:ip: ([0-9.]+), mask: ([0-9.]+) (2)`

**Steps:**
1. Match has two groups: group 1 = `"10.0.0.1"`, group 2 = `"255.255.255.0"`
2. Explicit `(2)` → uses group 2
3. `"255.255.255.0"` → no keyword, no digit pattern → `NaN`

**Note:** Extracting IP addresses as numeric values is not useful — consider using string-type metrics or different extraction logic.

---

### 8. No Match → NaN

**Raw output:**
```
Interface is physically present
```

**Extractor:** `regex:is (up|down)`

**Steps:**
1. No match found
2. Returns `(None, NaN)`

---

## CLI Configuration Reference

When creating a CLI metric in the UI, the following fields are available:

| Field | Description | Example |
|---|---|---|
| `cli_command` | The CLI command to execute | `show interfaces {target} status | include {target}` |
| `cli_target` | Value to substitute for `{target}` in the command | `GigabitEthernet0/0` |
| `cli_credential_ref` | Env variable prefix for credentials (looks up `{ref}_USER` and `{ref}_PASS`) | `CLI_DEFAULT` |
| `cli_escalation_script` | Multi-line script for privilege escalation (e.g. `enable` then password) | `enable\nsecret_password` |
| `cli_protocol` | Transport protocol: `SSH` (port 22) or `Telnet` (port 23) | `SSH` |
| `cli_timeout` | Connection/command timeout in seconds | `30` |

### Credential Setup

Set environment variables before starting the engine:

```bash
export CLI_DEFAULT_USER=admin
export CLI_DEFAULT_PASS=secret123
export MYDEVICE_USER=operator
export MYDEVICE_PASS=op-pass
```

The `cli_credential_ref` field selects which credential pair to use:

- `CLI_DEFAULT` → reads `CLI_DEFAULT_USER` / `CLI_DEFAULT_PASS`
- `MYDEVICE` → reads `MYDEVICE_USER` / `MYDEVICE_PASS`

---

## Testing in the UI

The Metrics Manager UI provides a **Test CLI Query** button in the CLI panel. It:

1. Sends the CLI fields to `POST /api/cli/test`
2. Displays `raw_output`, `extracted_value`, `numeric_value`, and a status badge
3. Allows iterating on the regex extractor until the correct value is extracted
4. Then **Save as Metric** commits the metric definition to Neo4j

---

## Engine Integration

The CLI engine (`engines/cli_worker.py`) runs as a standalone process:

```bash
python engines/cli_worker.py
```

It polls every 10 seconds and emits metrics to TimescaleDB. The NaN rate limiter in the engine tracks 3 consecutive misses and emits a `CLI_POLLL_ALERT` event to Neo4j.