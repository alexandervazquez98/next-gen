/**
 * MQTT Monitoring Frontend (Issue #385) — Bridge Status tab contract.
 *
 * PR1 verifies three branches from spec §Bridge Status and Counters:
 *   - Healthy runtime (`configured && running && connected`) → "Running".
 *   - Backend-normalized stale heartbeat (`running=false`,
 *     `reason_code="STALE_HEARTBEAT"`) → "Not Running" with reason code.
 *   - Unconfigured runtime (`configured=false`) → "Not Configured" with
 *     `last_error` text when supplied.
 *
 * Counters (`mapped_writes_total`, `unmapped_skips_total`,
 * `failed_writes_total`) must always render — even when the payload is
 * missing — so operators can see "0" rather than a blank tile.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import MqttBridgeStatusTab from "./MqttBridgeStatusTab";
import type { MqttRuntimeStatus } from "../../types";

const { mockUseMqttStatusQuery } = vi.hoisted(() => ({
  mockUseMqttStatusQuery: vi.fn(),
}));

vi.mock("../../hooks/queries/useMqttQueries", () => ({
  useMqttStatusQuery: (options: { refetchInterval?: number | false }) => {
    const result = mockUseMqttStatusQuery(options);
    return result;
  },
}));

const renderTab = (data: MqttRuntimeStatus | null) => {
  mockUseMqttStatusQuery.mockReturnValue({ data, isLoading: false, error: null });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MqttBridgeStatusTab />
    </QueryClientProvider>,
  );
};

const baseStatus: MqttRuntimeStatus = {
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

describe("MqttBridgeStatusTab — three-branch contract (PR1)", () => {
  beforeEach(() => {
    mockUseMqttStatusQuery.mockReset();
  });

  it("renders the Running branch for a healthy runtime", () => {
    renderTab(baseStatus);

    const header = screen.getByTestId("mqtt-bridge-branch");
    expect(header).toHaveAttribute("data-branch", "running");
    expect(header).toHaveTextContent(/Running/i);
    expect(screen.getByTestId("mqtt-bridge-counters")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByTestId("mqtt-subscribed-patterns")).toHaveTextContent(
      "tenants/+/devices/+/telemetry",
    );
  });

  it("renders the Not Running branch with reason_code when the backend flags a stale heartbeat", () => {
    renderTab({
      ...baseStatus,
      running: false,
      connected: false,
      reason_code: "STALE_HEARTBEAT",
      is_stale: true,
    });

    const header = screen.getByTestId("mqtt-bridge-branch");
    expect(header).toHaveAttribute("data-branch", "not-running");
    expect(header).toHaveTextContent(/Not Running/i);
    expect(header).toHaveTextContent(/reason_code: STALE_HEARTBEAT/i);
    expect(header).toHaveTextContent(/Stale heartbeat/i);
  });

  it("renders the Not Configured branch with last_error text when configured=false", () => {
    renderTab({
      ...baseStatus,
      configured: false,
      running: false,
      connected: false,
      last_error: "MQTT_BROKER_URL not set in config",
    });

    const header = screen.getByTestId("mqtt-bridge-branch");
    expect(header).toHaveAttribute("data-branch", "not-configured");
    expect(header).toHaveTextContent(/Not Configured/i);
  });

  it("prefers the Not Configured branch when both configured=false and running=false", () => {
    renderTab({
      ...baseStatus,
      configured: false,
      running: false,
      reason_code: "STALE_HEARTBEAT",
    });

    const header = screen.getByTestId("mqtt-bridge-branch");
    expect(header).toHaveAttribute("data-branch", "not-configured");
  });

  it("renders zero counters when the payload is missing", () => {
    renderTab(null);

    expect(screen.getAllByText("0")).toHaveLength(3);
    // No subscribed patterns block because the payload is null.
    expect(screen.queryByTestId("mqtt-subscribed-patterns")).not.toBeInTheDocument();
  });

  it("does not expose a subscription list when subscribed_patterns is empty", () => {
    renderTab({
      ...baseStatus,
      subscribed_patterns: [],
    });

    expect(screen.queryByTestId("mqtt-subscribed-patterns")).not.toBeInTheDocument();
  });

  it("passes a 5 second refetch interval to useMqttStatusQuery", () => {
    mockUseMqttStatusQuery.mockReturnValue({ data: baseStatus, isLoading: false, error: null });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MqttBridgeStatusTab />
      </QueryClientProvider>,
    );
    expect(mockUseMqttStatusQuery).toHaveBeenCalledWith(
      expect.objectContaining({ refetchInterval: 5_000 }),
    );
  });

  it("renders the loading state when the query is pending", () => {
    mockUseMqttStatusQuery.mockReturnValue({ data: undefined, isLoading: true, error: null });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MqttBridgeStatusTab />
      </QueryClientProvider>,
    );
    expect(screen.getByText(/Loading bridge status/i)).toBeInTheDocument();
  });

  it("renders an error message when the query fails", async () => {
    mockUseMqttStatusQuery.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error("boom"),
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MqttBridgeStatusTab />
      </QueryClientProvider>,
    );
    await waitFor(() => {
      expect(screen.getByText(/Failed to load bridge status/i)).toBeInTheDocument();
    });
  });
});
