/**
 * MQTT Monitoring Frontend (Issue #385) — mutation hook contract.
 *
 * PR1 verifies two safety-critical promises from the spec:
 *   1. On success, every mutation invalidates the `mqtt*` cache keys listed
 *      in `openspec/changes/feat-mqtt-385-frontend-ux/design.md`
 *      §State Management. Approve/revoke additionally invalidate
 *      `systemStatus` because the System Dashboard KPI cards can derive from
 *      mapping state.
 *   2. On a 403, a sonner toast naming `MQTT_MAPPING_MANAGE` fires so the
 *      operator can request access. The prior list state is preserved because
 *      we never optimistically update.
 */
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  useApproveMqttMapping,
  useCreateMqttMapping,
  useRevokeMqttMapping,
  useUpdateMqttMapping,
  useUpdateMqttMappingThresholds,
} from "./useMqttMutations";
import { ApiError } from "../../services/api";

const { mockApiPost, mockApiPut } = vi.hoisted(() => ({
  mockApiPost: vi.fn(),
  mockApiPut: vi.fn(),
}));

vi.mock("../../services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../services/api")>();
  return {
    ...actual,
    api: {
      post: mockApiPost,
      put: mockApiPut,
    },
  };
});

const sonnerMocks = vi.hoisted(() => ({
  toast: { error: vi.fn() },
}));
vi.mock("sonner", () => ({
  toast: sonnerMocks.toast,
}));

function Probe() {
  const create = useCreateMqttMapping();
  const update = useUpdateMqttMapping();
  const approve = useApproveMqttMapping();
  const revoke = useRevokeMqttMapping();
  const thresholds = useUpdateMqttMappingThresholds();

  return (
    <div>
      <button
        onClick={() =>
          void create
            .mutateAsync({
              source_device_id: "dev-1",
              source_metric_id: "metric-1",
              source_metric_name: "rssi",
              target_ci_id: "ci-1",
              target_metric_def_id: "metric-def-1",
            })
            .catch(() => undefined)
        }
      >
        create
      </button>
      <button
        onClick={() =>
          void update.mutateAsync("map-1", { source_metric_name: "x" }).catch(() => undefined)
        }
      >
        update
      </button>
      <button onClick={() => void approve.mutateAsync("map-1").catch(() => undefined)}>
        approve
      </button>
      <button onClick={() => void revoke.mutateAsync("map-1").catch(() => undefined)}>
        revoke
      </button>
      <button
        onClick={() =>
          void thresholds
            .mutateAsync("map-1", { operator: ">", warning: 1, critical: 2 })
            .catch(() => undefined)
        }
      >
        thresholds
      </button>
    </div>
  );
}

describe("useMqttMutations — cache invalidation contract", () => {
  let client: QueryClient;

  beforeEach(() => {
    client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    vi.spyOn(client, "invalidateQueries");
    mockApiPost.mockReset();
    mockApiPut.mockReset();
    sonnerMocks.toast.error.mockReset();
    mockApiPost.mockResolvedValue({ id: "map-1", status: "DRAFT" });
    mockApiPut.mockResolvedValue({ id: "map-1", status: "APPROVED" });
  });

  it.each([
    ["create", "create", "/mqtt/mappings"],
    ["update", "update", "/mqtt/mappings/map-1"],
    ["thresholds", "thresholds", "/mqtt/mappings/map-1/thresholds"],
  ] as const)(
    "invalidates mqtt* keys after %s succeeds (no systemStatus)",
    async (button, _label, _endpoint) => {
      render(
        <QueryClientProvider client={client}>
          <Probe />
        </QueryClientProvider>,
      );

      fireEvent.click(screen.getByRole("button", { name: button }));

      await waitFor(() => {
        expect(client.invalidateQueries).toHaveBeenCalledWith({ queryKey: ["mqtt", "mappings"] });
      });

      // All four shared mqtt* keys must be invalidated.
      const calls = (client.invalidateQueries as unknown as { mock: { calls: unknown[][] } }).mock
        .calls;
      const invalidatedKeys = calls.flatMap((c) => c[0] as { queryKey: readonly unknown[] });
      expect(invalidatedKeys).toContainEqual({ queryKey: ["mqtt", "mappings"] });
      expect(invalidatedKeys).toContainEqual({
        queryKey: ["mqtt", "mappings", undefined, "thresholds"],
      });
      expect(invalidatedKeys).toContainEqual({ queryKey: ["mqtt", "readings"] });
      expect(invalidatedKeys).toContainEqual({ queryKey: ["mqtt", "status"] });

      // systemStatus must NOT be invalidated for create/update/threshold.
      expect(invalidatedKeys).not.toContainEqual({ queryKey: ["system-status"] });
    },
  );

  it.each([
    ["approve", "approve"],
    ["revoke", "revoke"],
  ] as const)("invalidates systemStatus only after %s succeeds", async (button) => {
    render(
      <QueryClientProvider client={client}>
        <Probe />
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: button }));

    await waitFor(() => {
      expect(client.invalidateQueries).toHaveBeenCalledWith({ queryKey: ["system-status"] });
    });
  });

  it("surfaces a named-permission toast on 403 and leaves the cache untouched", async () => {
    mockApiPost.mockRejectedValueOnce(new ApiError("Forbidden", 403));

    render(
      <QueryClientProvider client={client}>
        <Probe />
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "approve" }));

    await waitFor(() => {
      expect(sonnerMocks.toast.error).toHaveBeenCalledWith(
        "Permission denied: MQTT_MAPPING_MANAGE",
      );
    });

    // No cache invalidation happens when the mutation fails — the prior list
    // state must remain intact.
    const calls = (client.invalidateQueries as unknown as { mock: { calls: unknown[][] } }).mock
      .calls;
    expect(calls).toHaveLength(0);
  });
});
