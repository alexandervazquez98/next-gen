import React from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { createQueryWrapper } from "../../test/queryTestUtils";
import { queryKeys } from "../../services/queryKeys";
import { fetchTunnelHealth } from "../../services/queryResources";
import {
	TUNNEL_HEALTH_LIMITS,
	buildVisibleTunnelHealthPlan,
	classifyTunnelHealthError,
	resolveTunnelHealthFallbackVisual,
	selectActiveTunnelHealthIds,
	updateTunnelHealthCooldown,
	useVisibleTunnelHealth,
} from "./useVisibleTunnelHealth";
import type { GraphLink } from "../../types";

const { mockApiGet, mockApiPost } = vi.hoisted(() => ({ mockApiGet: vi.fn(), mockApiPost: vi.fn() }));

vi.mock("../../services/api", () => ({
	api: { get: mockApiGet, post: mockApiPost },
}));

beforeEach(() => {
	mockApiGet.mockReset();
	mockApiPost.mockReset();
});

function link(id: string, medium: GraphLink["medium"] = "vpn", visible = true): GraphLink & { visible?: boolean } {
	return { id, source: `source-${id}`, target: `target-${id}`, relationship: "CONNECTS_TO", medium, visible };
}

function HookProbe({ links }: { links: Array<GraphLink & { visible?: boolean }> }) {
	const result = useVisibleTunnelHealth(links);
	return <pre data-testid="payload">{JSON.stringify(result)}</pre>;
}

describe("tunnel health query resources", () => {
	it("fetches tunnel health by encoded link id with an abort signal", async () => {
		const signal = new AbortController().signal;
		mockApiGet.mockResolvedValue({ status: "UP" });

		await fetchTunnelHealth("abc-123", { signal });

		expect(mockApiGet).toHaveBeenCalledWith("/tunnels/abc-123/health", { signal });
	});

	it("returns stable query keys per encoded tunnel link id", () => {
		expect(queryKeys.tunnelHealth("abc-123")).toEqual(["tunnels", "health", "abc-123"]);
	});
});

describe("buildVisibleTunnelHealthPlan", () => {
	it("keeps only visible tunnel links, dedupes identities, caps at 50, and records skipped counts", () => {
		const duplicates = [link("1"), link("1"), link("hidden", "vpn", false), link("plain", undefined)];
		const overflow = Array.from({ length: 55 }, (_, index) => link(`vpn-${index}`));

		const plan = buildVisibleTunnelHealthPlan([...duplicates, ...overflow], { nowMs: 0 });

		expect(plan.linkIds).toHaveLength(50);
		expect(new Set(plan.linkIds).size).toBe(50);
		expect(plan.skippedOverCap).toBeGreaterThan(0);
		expect(plan.suppressedCooldown).toBe(0);
		expect(plan.requestBudgetPerMinute).toBeLessThanOrEqual(120);
	});

	it("suppresses failing links during the 2-minute cooldown and honors kill switches", () => {
		const tunnel = link("cooldown");
		const encoded = buildVisibleTunnelHealthPlan([tunnel], { nowMs: 0 }).linkIds[0];

		expect(buildVisibleTunnelHealthPlan([tunnel], { nowMs: 60_000, cooldownUntilByLinkId: { [encoded]: 120_000 } })).toMatchObject({
			linkIds: [],
			suppressedCooldown: 1,
			pollingDisabled: false,
		});
		expect(buildVisibleTunnelHealthPlan([tunnel], { nowMs: 0, pollingDisabled: true })).toMatchObject({
			linkIds: [],
			pollingDisabled: true,
		});
	});

	it("uses deterministic 10-20% jitter and disables retry", () => {
		const plan = buildVisibleTunnelHealthPlan([link("jitter")], { nowMs: 0, jitterSeed: 0.5 });

		expect(plan.refetchIntervalMs).toBe(34_500);
		expect(plan.retry).toBe(false);
	});

	it("rotates through capped visible IDs instead of polling only the first four forever", () => {
		const plan = buildVisibleTunnelHealthPlan(Array.from({ length: 12 }, (_, index) => link(`vpn-${index}`)), { nowMs: 0 });

		const queried = new Set<string>();
		for (let cycle = 0; cycle < 3; cycle += 1) {
			const active = selectActiveTunnelHealthIds(plan.linkIds, cycle);
			expect(active).toHaveLength(TUNNEL_HEALTH_LIMITS.maxInFlight);
			active.forEach((id) => queried.add(id));
		}

		expect(queried.size).toBe(12);
		expect(queried).toEqual(new Set(plan.linkIds.slice(0, 12)));
	});
});

describe("tunnel health failure fallback", () => {
	it("classifies API, timeout, auth, and network failures", () => {
		expect(classifyTunnelHealthError({ status: 400 })).toBe("bad_request");
		expect(classifyTunnelHealthError({ status: 404 })).toBe("not_found");
		expect(classifyTunnelHealthError({ status: 500 })).toBe("server");
		expect(classifyTunnelHealthError({ status: 401 })).toBe("auth");
		expect(classifyTunnelHealthError({ name: "AbortError" })).toBe("timeout");
		expect(classifyTunnelHealthError(new TypeError("Failed to fetch"))).toBe("network");
	});

	it("keeps stale cached health when a later fetch fails", () => {
		const staleHealth = {
			link_id: "stale",
			source: "hub-a",
			target: "edge-b",
			relationship: "CONNECTS_TO",
			medium: "vpn",
			status: "UP",
			authority: { state: "UP", source: "SNMP", observed_at: null, reason: "sample" },
			icmp: { available: true, latency_ms: 12, error: null, reason: "sample" },
			observed_at: "2026-07-04T10:00:00Z",
		} as const;

		const visual = resolveTunnelHealthFallbackVisual(link("stale"), staleHealth, "server");

		expect(visual).toMatchObject({ authorityText: "UP", state: "up", stale: true, errorKind: "server" });
		expect(visual.tooltipRows).toContainEqual({ label: "Cache", value: "Using stale health" });
		expect(visual.tooltipRows).toContainEqual({ label: "Health", value: "Unavailable: server" });
	});

	it("returns neutral UNKNOWN fallback without cache and enters cooldown", () => {
		const fallback = resolveTunnelHealthFallbackVisual(link("missing"), undefined, "network");
		const cooldown = updateTunnelHealthCooldown({}, "missing-link", "network", 1_000);

		expect(fallback).toMatchObject({ authorityText: "UNKNOWN", state: "unknown", stale: false, errorKind: "network" });
		expect(cooldown["missing-link"]).toBe(1_000 + TUNNEL_HEALTH_LIMITS.cooldownMs);
	});
});

describe("tunnel health scheduling", () => {
	it("returns no live-health queries when disabled", () => {
		const storedValue = window.localStorage.getItem("tunnelHealthPollingDisabled");
		window.localStorage.setItem("tunnelHealthPollingDisabled", "true");

		render(<HookProbe links={[link("disabled")]} />, { wrapper: createQueryWrapper() });

		expect(screen.getByTestId("payload")).toHaveTextContent('"pollingDisabled":true');
		expect(mockApiGet).not.toHaveBeenCalled();
		if (storedValue === null) window.localStorage.removeItem("tunnelHealthPollingDisabled");
		else window.localStorage.setItem("tunnelHealthPollingDisabled", storedValue);
	});

	it("emits aggregate telemetry from the hook without blocking health queries", async () => {
		mockApiGet.mockResolvedValue({ status: "UP" });
		mockApiPost.mockRejectedValue(new Error("telemetry down"));

		render(<HookProbe links={[link("telemetry")]} />, { wrapper: createQueryWrapper() });

		await waitFor(() => {
			expect(mockApiPost).toHaveBeenCalledWith(
				"/tunnels/health/telemetry",
				expect.objectContaining({ scheduled: 1, skipped_over_cap: 0, suppressed_cooldown: 0 }),
			);
		});
		expect(mockApiGet).toHaveBeenCalled();
	});

	it("posts failure telemetry after an earlier scheduled-only telemetry flush", async () => {
		mockApiGet.mockRejectedValue({ status: 500 });
		mockApiPost.mockResolvedValue({ accepted: true });

		render(<HookProbe links={[link("telemetry-failure")]} />, { wrapper: createQueryWrapper() });

		await waitFor(() => {
			expect(mockApiPost).toHaveBeenCalledWith(
				"/tunnels/health/telemetry",
				expect.objectContaining({ scheduled: 1, failure_by_kind: {} }),
			);
		});
		await waitFor(() => {
			expect(mockApiPost).toHaveBeenCalledWith(
				"/tunnels/health/telemetry",
				expect.objectContaining({ failure_by_kind: { server: 1 } }),
			);
		});
		expect(mockApiGet).toHaveBeenCalled();
	});

	it("posts cooldown telemetry after a failed health query enters cooldown", async () => {
		mockApiGet.mockRejectedValue({ status: 500 });
		mockApiPost.mockResolvedValue({ accepted: true });

		render(<HookProbe links={[link("telemetry-cooldown")]} />, { wrapper: createQueryWrapper() });

		await waitFor(() => {
			expect(mockApiGet).toHaveBeenCalled();
			expect(screen.getByTestId("payload")).toHaveTextContent('"suppressedCooldown":1');
		});
		await waitFor(() => {
			expect(mockApiPost).toHaveBeenCalledWith(
				"/tunnels/health/telemetry",
				expect.objectContaining({ scheduled: 0, suppressed_cooldown: 1 }),
			);
		});
	});

	it("wakes up after all visible links are suppressed by cooldown", async () => {
		vi.useFakeTimers();
		try {
			mockApiGet.mockRejectedValueOnce({ status: 500 }).mockResolvedValue({ status: "UP" });

			render(<HookProbe links={[link("recover")]} />, { wrapper: createQueryWrapper() });

			await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(1));
			await waitFor(() => expect(screen.getByTestId("payload")).toHaveTextContent('"suppressedCooldown":1'));

			act(() => {
				vi.advanceTimersByTime(TUNNEL_HEALTH_LIMITS.cooldownMs + 1);
			});

			await waitFor(() => expect(mockApiGet).toHaveBeenCalledTimes(2));
			await waitFor(() => expect(screen.getByTestId("payload")).toHaveTextContent('"suppressedCooldown":0'));
		} finally {
			vi.useRealTimers();
		}
	});
});
