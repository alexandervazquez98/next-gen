import { beforeEach, describe, expect, it, vi } from "vitest";
import {
	buildTunnelHealthTelemetryPayload,
	createTunnelHealthTelemetryBatcher,
	postTunnelHealthTelemetry,
} from "./tunnelHealthTelemetry";

const { mockApiPost } = vi.hoisted(() => ({ mockApiPost: vi.fn() }));

vi.mock("../services/api", () => ({
	api: { post: mockApiPost },
}));

describe("tunnel health telemetry", () => {
	beforeEach(() => mockApiPost.mockReset());

	it("builds aggregate-only payloads without link ids, endpoints, URLs, IPs, or per-link arrays", () => {
		const payload = buildTunnelHealthTelemetryPayload({
			scheduled: 5,
			skippedOverCap: 2,
			suppressedCooldown: 1,
			success: 3,
			failureByKind: { network: 1 },
			latencyMs: [100, 800, 2000, 6000],
			killSwitchEnabled: false,
		});

		expect(payload).toEqual({
			window_seconds: 60,
			scheduled: 5,
			skipped_over_cap: 2,
			suppressed_cooldown: 1,
			success: 3,
			failure_by_kind: { network: 1 },
			latency_bucket: { lt_250: 1, lt_1000: 1, lt_5000: 1, gte_5000: 1 },
			kill_switch_enabled: false,
		});
		expect(JSON.stringify(payload)).not.toMatch(/link_id|hub-a|edge-b|\/tunnels\/|203\.0\.113\.10|192\.168\.1\.1|\[/);
	});

	it("flushes at most once per minute and only when active or failing", async () => {
		vi.useFakeTimers();
		mockApiPost.mockResolvedValue({ accepted: true });
		const batcher = createTunnelHealthTelemetryBatcher({ now: () => Date.now() });

		expect(await batcher.flush({ scheduled: 0, success: 0 })).toBe(false);
		expect(await batcher.flush({ scheduled: 1, success: 1 })).toBe(true);
		expect(await batcher.flush({ scheduled: 1, success: 1 })).toBe(false);
		vi.advanceTimersByTime(60_000);
		expect(await batcher.flush({ scheduled: 0, success: 0, failureByKind: { network: 1 } })).toBe(true);

		expect(mockApiPost).toHaveBeenCalledTimes(2);
		vi.useRealTimers();
	});

	it("does not let an early scheduled-only flush hide later failure or cooldown telemetry", async () => {
		let now = 0;
		mockApiPost.mockResolvedValue({ accepted: true });
		const batcher = createTunnelHealthTelemetryBatcher({ now: () => now });

		expect(await batcher.flush({ scheduled: 1, success: 0 })).toBe(true);
		now = 1_000;
		expect(await batcher.flush({ scheduled: 1, success: 0, failureByKind: { server: 1 }, suppressedCooldown: 1 })).toBe(true);
		now = 2_000;
		expect(await batcher.flush({ scheduled: 1, success: 1 })).toBe(false);

		expect(mockApiPost).toHaveBeenCalledTimes(2);
		expect(mockApiPost).toHaveBeenLastCalledWith(
			"/tunnels/health/telemetry",
			expect.objectContaining({ failure_by_kind: { server: 1 }, suppressed_cooldown: 1 }),
		);
	});

	it("does not let earlier failure diagnostics hide later cooldown-only telemetry", async () => {
		let now = 0;
		mockApiPost.mockResolvedValue({ accepted: true });
		const batcher = createTunnelHealthTelemetryBatcher({ now: () => now });

		expect(await batcher.flush({ scheduled: 1, success: 0, failureByKind: { server: 1 } })).toBe(true);
		now = 1_000;
		expect(await batcher.flush({ scheduled: 0, suppressedCooldown: 1, success: 0 })).toBe(true);
		now = 2_000;
		expect(await batcher.flush({ scheduled: 0, suppressedCooldown: 1, success: 0 })).toBe(false);

		expect(mockApiPost).toHaveBeenCalledTimes(2);
		expect(mockApiPost).toHaveBeenLastCalledWith(
			"/tunnels/health/telemetry",
			expect.objectContaining({ failure_by_kind: {}, suppressed_cooldown: 1 }),
		);
	});

	it("keeps failed flushes fail-open and does not consume the rate-limit window", async () => {
		let now = 0;
		mockApiPost.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce({ accepted: true });
		const batcher = createTunnelHealthTelemetryBatcher({ now: () => now });

		expect(await batcher.flush({ scheduled: 1, failureByKind: { network: 1 } })).toBe(false);
		expect(await batcher.flush({ scheduled: 1, success: 1 })).toBe(true);

		expect(mockApiPost).toHaveBeenCalledTimes(2);
	});

	it("posts aggregate telemetry to the authenticated backend route", async () => {
		mockApiPost.mockResolvedValue({ accepted: true });
		const payload = buildTunnelHealthTelemetryPayload({ scheduled: 1, success: 1 });

		await postTunnelHealthTelemetry(payload);

		expect(mockApiPost).toHaveBeenCalledWith("/tunnels/health/telemetry", payload);
	});
});
