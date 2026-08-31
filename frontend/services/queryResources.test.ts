import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  approveMqttMapping,
  createMqttMapping,
  fetchActiveEvents,
  fetchCategories,
  fetchMqttDeviceMetrics,
  fetchMqttDevices,
  fetchMqttMappingThresholds,
  fetchMqttMappings,
  fetchMqttReadings,
  fetchMqttStatus,
  fetchNodeMetricHistory,
  fetchNodesSearch,
  revokeMqttMapping,
  updateMqttMapping,
  updateMqttMappingThresholds,
} from "./queryResources";

const { mockApiGet, mockApiPost, mockApiPut } = vi.hoisted(() => ({
  mockApiGet: vi.fn(),
  mockApiPost: vi.fn(),
  mockApiPut: vi.fn(),
}));

vi.mock("./api", () => ({
  api: {
    get: mockApiGet,
    post: mockApiPost,
    put: mockApiPut,
  },
}));

describe("fetchActiveEvents", () => {
  beforeEach(() => {
    mockApiGet.mockReset();
  });

  it("calls the console event feed so recovered events remain visible", async () => {
    mockApiGet.mockResolvedValue([]);
    const signal = new AbortController().signal;

    await fetchActiveEvents({ signal });

    expect(mockApiGet).toHaveBeenCalledWith("/events?status=CONSOLE", {
      signal,
    });
  });
});

describe("fetchCategories", () => {
  beforeEach(() => {
    mockApiGet.mockReset();
  });

  it("fetches categories with icon metadata", async () => {
    const signal = new AbortController().signal;
    const mockCategories = [
      { name: "Router", icon_key: "router" },
      { name: "Storage", icon_key: "storage" },
    ];
    mockApiGet.mockResolvedValue(mockCategories);

    const result = await fetchCategories({ signal });

    expect(mockApiGet).toHaveBeenCalledWith("/categories", {
      signal,
    });
    expect(result).toEqual(mockCategories);
    expect(result[0].icon_key).toBe("router");
  });

  it("supports missing icon metadata from older API responses", async () => {
    const mockCategories = [{ name: "Network" }];
    mockApiGet.mockResolvedValue(mockCategories);

    const result = await fetchCategories({});

    expect(mockApiGet).toHaveBeenCalledWith("/categories", { signal: undefined });
    expect(result).toEqual(mockCategories);
  });
});

describe("fetchNodesSearch", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockApiGet.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("calls /nodes/search with q query param", async () => {
    mockApiGet.mockResolvedValue([
      { id: "CI-001", label: "Router", status: "OK", ip: "192.168.1.1" },
    ]);

    await fetchNodesSearch({ q: "router" });

    expect(mockApiGet).toHaveBeenCalledWith("/nodes/search?q=router", {
      signal: undefined,
    });
  });

  it("forwards abort signal", async () => {
    mockApiGet.mockResolvedValue([]);
    const signal = new AbortController().signal;

    await fetchNodesSearch({ q: "server", signal });

    expect(mockApiGet).toHaveBeenCalledWith("/nodes/search?q=server", {
      signal,
    });
  });

  it("returns array of nodes on success", async () => {
    const mockNodes = [
      {
        id: "CI-001",
        label: "Core Router",
        ip: "192.168.1.1",
        status: "OK",
        brand: "Cisco",
        model: "ASR-1000",
      },
      {
        id: "CI-002",
        label: "Backup Router",
        ip: "192.168.1.2",
        status: "ACTIVE",
        brand: "Juniper",
        model: "MX204",
      },
    ];
    mockApiGet.mockResolvedValue(mockNodes);

    const result = await fetchNodesSearch({ q: "router" });

    expect(result).toEqual(mockNodes);
    expect(mockApiGet).toHaveBeenCalledTimes(1);
  });

  it("throws ApiError for non-2xx responses", async () => {
    mockApiGet.mockRejectedValue(new Error("Query must be at least 2 characters"));

    await expect(fetchNodesSearch({ q: "a" })).rejects.toThrow(
      "Query must be at least 2 characters",
    );
  });
});

describe("fetchNodeMetricHistory", () => {
  beforeEach(() => {
    mockApiGet.mockReset();
  });

  it("calls single-node metric history endpoint with encoded params", async () => {
    mockApiGet.mockResolvedValue([]);

    await fetchNodeMetricHistory({
      nodeId: "CI 001",
      metricId: "cpu/load",
      hours: 24,
    });

    expect(mockApiGet).toHaveBeenCalledWith(
      "/metrics/CI%20001/cpu%2Fload/history?limit=1000&hours=24",
      { signal: undefined },
    );
  });
});

// ===========================================================================
// MQTT Monitoring Frontend (Issue #385) — fetcher + mutator contract.
//
// PR1 verifies the URL/body shapes because those encode the safety contract:
//   - raw browse endpoints must NEVER accept or return KPI-derived payloads
//     (the backend enforces this; we assert the URL stays on /mqtt/*).
//   - mutators must POST/PUT against the documented mapping lifecycle paths.
// ===========================================================================

describe("MQTT fetcher — raw browse + bridge status (PR1)", () => {
  beforeEach(() => {
    mockApiGet.mockReset();
    mockApiPost.mockReset();
    mockApiPut.mockReset();
  });

  it("hits /mqtt/devices with no params", async () => {
    mockApiGet.mockResolvedValue([]);
    await fetchMqttDevices({});
    expect(mockApiGet).toHaveBeenCalledWith("/mqtt/devices", { signal: undefined });
  });

  it("encodes device id in /mqtt/devices/{id}/metrics", async () => {
    mockApiGet.mockResolvedValue([]);
    await fetchMqttDeviceMetrics("dev/with spaces", {});
    expect(mockApiGet).toHaveBeenCalledWith("/mqtt/devices/dev%2Fwith%20spaces/metrics", {
      signal: undefined,
    });
  });

  it("defaults the readings limit to 100", async () => {
    mockApiGet.mockResolvedValue([]);
    await fetchMqttReadings({});
    expect(mockApiGet).toHaveBeenCalledWith("/mqtt/readings?limit=100", { signal: undefined });
  });

  it("respects a custom readings limit", async () => {
    mockApiGet.mockResolvedValue([]);
    await fetchMqttReadings({ limit: 25 });
    expect(mockApiGet).toHaveBeenCalledWith("/mqtt/readings?limit=25", { signal: undefined });
  });

  it("hits /mqtt/status for the bridge status tab", async () => {
    mockApiGet.mockResolvedValue({});
    await fetchMqttStatus({});
    expect(mockApiGet).toHaveBeenCalledWith("/mqtt/status", { signal: undefined });
  });

  it("lists /mqtt/mappings without status when no filter is provided", async () => {
    mockApiGet.mockResolvedValue([]);
    await fetchMqttMappings({});
    expect(mockApiGet).toHaveBeenCalledWith("/mqtt/mappings", { signal: undefined });
  });

  it("appends ?status=... when a filter is provided", async () => {
    mockApiGet.mockResolvedValue([]);
    await fetchMqttMappings({ status: "DRAFT" });
    expect(mockApiGet).toHaveBeenCalledWith("/mqtt/mappings?status=DRAFT", { signal: undefined });
  });

  it("fetches a single mapping's thresholds", async () => {
    mockApiGet.mockResolvedValue({});
    await fetchMqttMappingThresholds("map 1", {});
    expect(mockApiGet).toHaveBeenCalledWith("/mqtt/mappings/map%201/thresholds", {
      signal: undefined,
    });
  });
});

describe("MQTT mutator — mapping lifecycle (PR1)", () => {
  beforeEach(() => {
    mockApiGet.mockReset();
    mockApiPost.mockReset();
    mockApiPut.mockReset();
  });

  it("creates a mapping with the documented field shape", async () => {
    mockApiPost.mockResolvedValue({ id: "map-1", status: "DRAFT" });
    await createMqttMapping({
      source_device_id: "dev-1",
      source_metric_id: "metric-1",
      source_metric_name: "rssi",
      target_ci_id: "ci-1",
      target_metric_def_id: "metric-def-1",
    });
    expect(mockApiPost).toHaveBeenCalledWith("/mqtt/mappings", {
      source_device_id: "dev-1",
      source_metric_id: "metric-1",
      source_metric_name: "rssi",
      target_ci_id: "ci-1",
      target_metric_def_id: "metric-def-1",
    });
  });

  it("PUTs a full-payload mapping update", async () => {
    mockApiPut.mockResolvedValue({});
    await updateMqttMapping("map 1", {
      source_metric_name: "rssi-dbm",
      target_ci_id: "ci-2",
      target_metric_def_id: "metric-def-2",
    });
    expect(mockApiPut).toHaveBeenCalledWith("/mqtt/mappings/map%201", {
      source_metric_name: "rssi-dbm",
      target_ci_id: "ci-2",
      target_metric_def_id: "metric-def-2",
    });
  });

  it("approves via POST /mqtt/mappings/{id}/approve with an empty body", async () => {
    mockApiPost.mockResolvedValue({});
    await approveMqttMapping("map-1");
    expect(mockApiPost).toHaveBeenCalledWith("/mqtt/mappings/map-1/approve", {});
  });

  it("revokes via POST /mqtt/mappings/{id}/revoke with an empty body", async () => {
    mockApiPost.mockResolvedValue({});
    await revokeMqttMapping("map-1");
    expect(mockApiPost).toHaveBeenCalledWith("/mqtt/mappings/map-1/revoke", {});
  });

  it("PUTs a thresholds update against the per-mapping endpoint", async () => {
    mockApiPut.mockResolvedValue({});
    await updateMqttMappingThresholds("map-1", {
      operator: ">",
      warning: 80,
      critical: 90,
    });
    expect(mockApiPut).toHaveBeenCalledWith("/mqtt/mappings/map-1/thresholds", {
      operator: ">",
      warning: 80,
      critical: 90,
    });
  });
});
