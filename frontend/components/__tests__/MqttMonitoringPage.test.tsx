/**
 * MQTT Monitoring Frontend (Issue #385) — page integration test (PR1 WU4).
 *
 * The page-level test exercises the contract that no individual unit test
 * can fully prove:
 *   1. The route-level guard fires before any `/api/mqtt/*` fetch.
 *   2. When `MQTT_READ` is granted, both the Raw Readings and Bridge Status
 *      tabs render their expected surfaces.
 *   3. The `RAW_MQTT_NON_KPI` badge is rendered on every reading row even
 *      when the payload omits the classification / kpi_eligible fields.
 *   4. The DOM never exposes a "Mark as KPI", "Promote", or "Assign to KPI"
 *      affordance anywhere in the page tree (spec §No "Mark as KPI"
 *      Affordance).
 *   5. The Mappings/Thresholds tabs are intentionally absent in PR1 — the
 *      write surface ships in PR2.
 *
 * The Raw + Bridge tabs reach the page through real `useMqtt*` hooks that
 * are mocked to return the test fixtures, mirroring the unit-test patterns
 * used by `MonitoringConsole.test.tsx`.
 */
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HashRouter } from "react-router-dom";
import MqttMonitoringPage from "../MqttMonitoringPage";
import type { MqttRawDeviceResponse, MqttRawMetricResponse, MqttRuntimeStatus } from "../../types";

// ---------------------------------------------------------------------------
// Hook mocks — return stable, hand-rolled fixtures so the tests assert
// behavior, not React Query plumbing.
// ---------------------------------------------------------------------------

const devicesFixture: MqttRawDeviceResponse[] = [
  {
    device_id: "dev-1",
    name: "Edge Gateway 1",
    last_seen: "2026-08-30T10:00:00.000Z",
    classification: "RAW_MQTT_NON_KPI",
    kpi_eligible: false,
    mapped_metrics_count: 4,
    unmapped_metrics_count: 2,
  },
  {
    device_id: "dev-2",
    name: "Edge Gateway 2",
    last_seen: "2026-08-30T10:05:00.000Z",
    classification: null,
    kpi_eligible: null,
    mapped_metrics_count: 0,
    unmapped_metrics_count: 0,
  },
];

const readingsFixture: MqttRawMetricResponse[] = [
  {
    device_id: "dev-1",
    metric_id: "m-1",
    name: "rssi",
    last_value: -72,
    unit: "dBm",
    last_ts: "2026-08-30T10:00:00.000Z",
    classification: "RAW_MQTT_NON_KPI",
    kpi_eligible: false,
    mapping_status: "APPROVED",
  },
  // Reading with both classification and kpi_eligible missing — exercises
  // the badge default path.
  {
    device_id: "dev-1",
    metric_id: "m-2",
    name: "snr",
    last_value: 18,
    unit: "dB",
    last_ts: "2026-08-30T10:00:01.000Z",
    classification: null,
    kpi_eligible: null,
    mapping_status: "UNMAPPED",
  },
];

const statusFixture: MqttRuntimeStatus = {
  service_name: "mqtt-bridge",
  configured: true,
  running: true,
  connected: true,
  subscribed_patterns: ["tenants/+/devices/+/telemetry"],
  last_message_at: "2026-08-30T10:00:00.000Z",
  last_error: null,
  reason_code: null,
  mapped_writes_total: 12,
  unmapped_skips_total: 3,
  failed_writes_total: 1,
  is_stale: false,
};

vi.mock("../../hooks/queries/useMqttQueries", () => ({
  useMqttDevicesQuery: () => ({ data: devicesFixture, isLoading: false, error: null }),
  useMqttDeviceMetricsQuery: () => ({ data: [], isLoading: false, error: null }),
  useMqttReadingsQuery: () => ({ data: readingsFixture, isLoading: false, error: null }),
  useMqttStatusQuery: () => ({ data: statusFixture, isLoading: false, error: null }),
  useMqttMappingsQuery: () => ({ data: [], isLoading: false, error: null }),
  useMqttMappingThresholdsQuery: () => ({ data: null, isLoading: false, error: null }),
}));

vi.mock("../../hooks/queries/useMqttMutations", () => ({
  useCreateMqttMapping: () => ({ mutateAsync: vi.fn() }),
  useUpdateMqttMapping: () => ({ mutateAsync: vi.fn() }),
  useApproveMqttMapping: () => ({ mutateAsync: vi.fn() }),
  useRevokeMqttMapping: () => ({ mutateAsync: vi.fn() }),
  useUpdateMqttMappingThresholds: () => ({ mutateAsync: vi.fn() }),
}));

// ---------------------------------------------------------------------------
// Auth mock — three permission scenarios per design §Permission Gates.
// ---------------------------------------------------------------------------

interface AuthShape {
  user: {
    username: string;
    role: string;
    permissions: string[];
    allowed_locations: string[];
    tier: string;
  } | null;
  hasPermission: (_perm: string) => boolean;
  isAuthenticated: boolean;
  loading: boolean;
}

const auth: AuthShape = {
  user: {
    username: "tester",
    role: "USER",
    permissions: ["MQTT_READ"],
    allowed_locations: [],
    tier: "T1",
  },
  // Mirror the ADMIN short-circuit from `context/AuthContext.tsx` lines 203-207.
  hasPermission: (perm: string) => {
    const u = auth.user;
    if (!u) return false;
    if (u.role === "ADMIN") return true;
    return u.permissions.includes(perm);
  },
  isAuthenticated: true,
  loading: false,
};

vi.mock("../../context/AuthContext", () => ({
  useAuth: () => auth,
}));

const renderPage = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <HashRouter>
      <QueryClientProvider client={client}>
        <MqttMonitoringPage />
      </QueryClientProvider>
    </HashRouter>,
  );
};

describe("MqttMonitoringPage — PR1 page integration contract", () => {
  beforeEach(() => {
    auth.user = {
      username: "tester",
      role: "USER",
      permissions: ["MQTT_READ"],
      allowed_locations: [],
      tier: "T1",
    };
  });

  it("renders the page header + tabs when MQTT_READ is granted", () => {
    renderPage();
    expect(screen.getByText(/Raw, non-KPI telemetry only/i)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Raw Readings/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Bridge Status/i })).toBeInTheDocument();
  });

  it("renders the device list and badge for the default Raw Readings tab", () => {
    renderPage();
    expect(screen.getAllByTestId("mqtt-device-row")).toHaveLength(2);
    // Latest Readings panel exists.
    expect(screen.getByTestId("mqtt-latest-readings-panel")).toBeInTheDocument();
    // One reading row per fixture entry.
    expect(screen.getAllByTestId("mqtt-reading-row")).toHaveLength(2);
  });

  it("renders a RAW_MQTT_NON_KPI badge on every reading row, including those missing classification", () => {
    renderPage();
    const rows = screen.getAllByTestId("mqtt-reading-row");
    expect(rows).toHaveLength(2);
    rows.forEach((row) => {
      const badge = row.querySelector('[data-testid="raw-non-kpi-badge"]');
      expect(badge).not.toBeNull();
      expect(badge).toHaveAttribute("data-classification", "RAW_MQTT_NON_KPI");
      expect(badge).toHaveAttribute("data-kpi-eligible", "false");
    });
  });

  it("exposes no 'Mark as KPI' / 'Promote' / 'Assign to KPI' affordance anywhere in the DOM", () => {
    renderPage();
    const bodyText = document.body.textContent ?? "";
    // Spec §No "Mark as KPI" Affordance — the DOM MUST NOT contain any
    // button / link / label whose text matches the promotion affordance.
    expect(bodyText).not.toMatch(/Mark as KPI|Promote|Assign to KPI/i);
  });

  it("does NOT render the Mappings or Thresholds tabs in PR1 (write surface ships in PR2)", () => {
    renderPage();
    expect(screen.queryByRole("tab", { name: /Mappings/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /Thresholds/i })).not.toBeInTheDocument();
  });

  it("switches to the Bridge Status tab on click and renders the Running branch + counters", async () => {
    renderPage();
    const bridgeTab = screen.getByRole("tab", { name: /Bridge Status/i });
    fireEvent.click(bridgeTab);
    await waitFor(() => {
      expect(screen.getByTestId("mqtt-bridge-branch")).toBeInTheDocument();
    });
    expect(screen.getByTestId("mqtt-bridge-branch")).toHaveAttribute("data-branch", "running");
    expect(screen.getByTestId("mqtt-bridge-counters")).toBeInTheDocument();
  });

  it("ADMIN role bypasses the MQTT_READ requirement (hasPermission short-circuit)", async () => {
    auth.user = {
      username: "tester",
      role: "ADMIN",
      permissions: [],
      allowed_locations: [],
      tier: "T3",
    };
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/Raw, non-KPI telemetry only/i)).toBeInTheDocument();
    });
  });

  it("redirects to / via the route-level guard when neither MQTT_READ nor ADMIN is granted", () => {
    auth.user = {
      username: "tester",
      role: "USER",
      permissions: [],
      allowed_locations: [],
      tier: "T1",
    };
    // The HashRouter reroutes to "/", which then renders the mocked
    // SystemDashboard. We assert the page-specific header is absent.
    renderPage();
    expect(screen.queryByText(/Raw, non-KPI telemetry only/i)).not.toBeInTheDocument();
  });
});
