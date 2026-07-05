# Delta for Tunnel Monitoring

## ADDED Requirements

### Requirement: Frontend Tunnel Health Visualization

Frontend tunnel surfaces MUST consume latest tunnel health through one shared visual model that preserves backend authority text. `UNKNOWN` with ICMP problems or missing public IP MUST render as neutral unknown with tooltip context only. `UP` with ICMP failure or poor RTT MUST render as `UP` with a warning badge/tooltip, not as `DEGRADED` or `DOWN`.

#### Scenario: Unknown with missing public IP remains neutral

- GIVEN a visible tunnel health response has `status=UNKNOWN` and `icmp.reason=missing_public_ip`
- WHEN a topology or monitoring surface renders the tunnel
- THEN the textual state MUST be `UNKNOWN`
- AND the visual treatment MUST be neutral unknown with the ICMP reason only in tooltip/context rows

#### Scenario: Up with poor ICMP keeps authority

- GIVEN a visible tunnel health response has `status=UP` and failed or poor RTT ICMP context
- WHEN the tunnel is rendered
- THEN the textual state MUST remain `UP`
- AND the UI MAY show a warning badge and tooltip explaining the ICMP context

### Requirement: Shared Tunnel Visual Surfaces

NetworkVisualizer, MonitoringConsole topology views, VisualRelationshipEditor, TopologyViewer/RelationshipManager, and CIDetailModal topology context SHALL use the shared tunnel visual model when rendering eligible tunnel links, including medium, icon key, authority status, warning badge state, and tooltip rows.

#### Scenario: Existing medium and health render consistently

- GIVEN the same visible tunnel appears in two supported surfaces
- WHEN both surfaces render the link
- THEN both MUST derive medium label, icon key, authority text, badge state, and tooltip rows from the shared model

#### Scenario: Detail modal has relevant topology context

- GIVEN a CI detail view includes relevant tunnel relationships
- WHEN the detail modal renders topology context
- THEN tunnel links MUST use the same visual contract as other supported topology surfaces

### Requirement: Canonical Tunnel Link Encoder Compatibility

Frontend tunnel link encoding MUST match the backend canonical `link_id` contract: JSON field order `source`, `relationship`, `target`, `medium`, UTF-8 input, URL-safe unpadded base64 output, and deterministic output for non-ASCII endpoint identifiers.

#### Scenario: Canonical encoder fixtures are stable

- GIVEN fixture links with ASCII and UTF-8/non-ASCII endpoint identifiers
- WHEN the frontend encoder builds link IDs
- THEN output MUST match backend fixtures exactly
- AND output MUST be URL-safe and contain no `=` padding

### Requirement: Visible Tunnel Health Polling Guardrails

Frontend health fetching SHALL be bounded to currently visible eligible tunnel links, keyed per canonical encoded link id, and cached/polled to avoid large-topology request storms. Production bounds MUST include a maximum of 50 visible link IDs per surface, a maximum of 4 concurrent health requests, polling `retry: false`, deterministic 10-20% interval jitter/backoff, a page-level budget no higher than 120 health requests/minute, and a cooldown that suppresses repeatedly failing link IDs for at least 2 minutes.

#### Scenario: Only visible tunnel links are polled

- GIVEN a topology contains hidden, filtered, and visible links
- WHEN tunnel health polling runs
- THEN only visible links with tunnel media `vpn`, `sd_wan`, or `satellite` MUST request health

#### Scenario: Non-tunnel and repeated links are bounded

- GIVEN repeated renders include non-tunnel links and duplicate tunnel identities
- WHEN health queries are scheduled
- THEN non-tunnel links MUST NOT be queried
- AND duplicate visible tunnel identities MUST share the same cached query key

#### Scenario: Production polling bounds are enforced

- GIVEN more than 50 visible eligible tunnel links are present
- WHEN health polling is scheduled
- THEN at most 50 IDs MUST be active for that surface
- AND no more than 4 requests MAY be in flight at once
- AND polling retries MUST be disabled and jitter/backoff MUST avoid synchronized bursts

### Requirement: Tunnel Health Failure Fallback

Health endpoint failures MUST degrade gracefully for 400, 404, 5xx, timeout, network, and auth-refresh failure states. If a stale cached health response exists, surfaces MUST keep the stale visual and expose error context in tooltip/debug metadata. If no cached response exists, surfaces MUST render neutral `UNKNOWN` with a tooltip explaining that health is unavailable. Repeated failures for the same link ID MUST enter cooldown instead of polling every interval.

#### Scenario: Failed fetch with stale visual

- GIVEN a tunnel has a cached `UP` visual and the next health fetch returns 5xx or times out
- WHEN the surface re-renders
- THEN the previous visual MUST remain visible as stale
- AND tooltip/debug context MUST identify the fetch failure

#### Scenario: Failed fetch without cache

- GIVEN a visible tunnel has no cached health response
- WHEN its health fetch returns 400, 404, auth failure, or network failure
- THEN the tunnel MUST render neutral `UNKNOWN`
- AND repeated polling for that link ID MUST be suppressed during cooldown

### Requirement: Tunnel Health Polling Operations Controls

Tunnel health polling MUST expose a production-observable operations signal and MUST include an operational kill switch. Because no centralized frontend telemetry sink exists, the system SHALL send authenticated, backend-visible aggregate telemetry for the page/session/window. Telemetry MUST be bounded, rate-limited to at most once per minute per browser tab/page, and emitted only when polling is active or failures occur. Payloads MUST include scheduled count, skipped-over-cap count, suppressed-cooldown count, success count, failure counts by error kind, latency buckets, and kill-switch state. Payloads MUST NOT include `link_id`, source/target identifiers, URL paths containing encoded IDs, per-link arrays, public IPs, or other IP-like values. Polling MUST stop when the build/env gate or runtime localStorage kill switch is disabled.

#### Scenario: Polling can be disabled operationally

- GIVEN `VITE_TUNNEL_HEALTH_POLLING=false` or runtime localStorage disables polling
- WHEN topology surfaces render visible tunnels
- THEN health requests MUST NOT be scheduled
- AND surfaces MUST render deterministic neutral/no-live-health context

#### Scenario: Polling fan-out is measurable

- GIVEN health polling runs for visible tunnel links
- WHEN requests succeed, fail, or are skipped
- THEN the frontend MUST batch aggregate counts for the active page/session/window
- AND the backend-visible operations signal MUST expose fan-out, error, fallback, latency, and kill-switch state for production debugging

#### Scenario: Telemetry is redacted and bounded

- GIVEN telemetry is flushed for a page/session/window
- WHEN the payload is built or accepted by the backend
- THEN it MUST contain only aggregate counts, error-kind counts, latency buckets, and kill-switch state
- AND it MUST reject or omit `public_ip`, IP-like values, `link_id`, endpoint names, URL paths containing encoded IDs, and per-link details

#### Scenario: Telemetry batching respects rate limit

- GIVEN polling remains active across multiple intervals in one browser tab
- WHEN telemetry flushes are scheduled
- THEN telemetry MUST be sent at most once per minute for that tab/page
- AND no telemetry MUST be sent while polling is idle and no failures occurred
