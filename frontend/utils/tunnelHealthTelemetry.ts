import { api } from "../services/api";
import type { TunnelHealthErrorKind, TunnelHealthTelemetryPayload } from "../types";

type LatencyBucket = TunnelHealthTelemetryPayload["latency_bucket"];

export const TUNNEL_HEALTH_TELEMETRY_WINDOW_SECONDS = 60;
export const TUNNEL_HEALTH_TELEMETRY_FLUSH_INTERVAL_MS = TUNNEL_HEALTH_TELEMETRY_WINDOW_SECONDS * 1_000;
export const TUNNEL_HEALTH_LATENCY_BUCKETS = {
	lt250Ms: 250,
	lt1000Ms: 1_000,
	lt5000Ms: 5_000,
} as const;

export interface TunnelHealthTelemetryInput {
	scheduled?: number;
	skippedOverCap?: number;
	suppressedCooldown?: number;
	success?: number;
	failureByKind?: Partial<Record<TunnelHealthErrorKind, number>>;
	latencyMs?: number[];
	killSwitchEnabled?: boolean;
}

const emptyLatencyBucket = (): LatencyBucket => ({ lt_250: 0, lt_1000: 0, lt_5000: 0, gte_5000: 0 });

function countLatencyBuckets(latencyMs: number[] = []): LatencyBucket {
	const bucket = emptyLatencyBucket();
	for (const latency of latencyMs) {
		if (latency < TUNNEL_HEALTH_LATENCY_BUCKETS.lt250Ms) bucket.lt_250 += 1;
		else if (latency < TUNNEL_HEALTH_LATENCY_BUCKETS.lt1000Ms) bucket.lt_1000 += 1;
		else if (latency < TUNNEL_HEALTH_LATENCY_BUCKETS.lt5000Ms) bucket.lt_5000 += 1;
		else bucket.gte_5000 += 1;
	}
	return bucket;
}

export function buildTunnelHealthTelemetryPayload(input: TunnelHealthTelemetryInput): TunnelHealthTelemetryPayload {
	return {
		window_seconds: TUNNEL_HEALTH_TELEMETRY_WINDOW_SECONDS,
		scheduled: input.scheduled ?? 0,
		skipped_over_cap: input.skippedOverCap ?? 0,
		suppressed_cooldown: input.suppressedCooldown ?? 0,
		success: input.success ?? 0,
		failure_by_kind: input.failureByKind ?? {},
		latency_bucket: countLatencyBuckets(input.latencyMs),
		kill_switch_enabled: input.killSwitchEnabled ?? false,
	};
}

export function postTunnelHealthTelemetry(payload: TunnelHealthTelemetryPayload) {
	return api.post<{ accepted: boolean }>("/tunnels/health/telemetry", payload);
}

function hasFailureTelemetry(input: TunnelHealthTelemetryInput): boolean {
	return Object.values(input.failureByKind ?? {}).some((count) => (count ?? 0) > 0);
}

function hasDiagnosticTelemetry(input: TunnelHealthTelemetryInput): boolean {
	return hasFailureTelemetry(input) || (input.suppressedCooldown ?? 0) > 0 || Boolean(input.killSwitchEnabled);
}

type DiagnosticTelemetryKind = "failure" | "cooldown" | "kill_switch";

function getDiagnosticTelemetryKinds(input: TunnelHealthTelemetryInput): DiagnosticTelemetryKind[] {
	const kinds: DiagnosticTelemetryKind[] = [];
	if (hasFailureTelemetry(input)) kinds.push("failure");
	if ((input.suppressedCooldown ?? 0) > 0) kinds.push("cooldown");
	if (input.killSwitchEnabled) kinds.push("kill_switch");
	return kinds;
}

export function createTunnelHealthTelemetryBatcher({ now = () => Date.now() } = {}) {
	let lastFlushMs = -Infinity;
	let lastFlushDiagnosticKinds = new Set<DiagnosticTelemetryKind>();
	return {
		async flush(input: TunnelHealthTelemetryInput): Promise<boolean> {
			const hasFailure = hasFailureTelemetry(input);
			const active =
				(input.scheduled ?? 0) > 0 || hasFailure || (input.suppressedCooldown ?? 0) > 0 || Boolean(input.killSwitchEnabled);
			if (!active) return false;
			const current = now();
			const hasDiagnostics = hasDiagnosticTelemetry(input);
			const diagnosticKinds = getDiagnosticTelemetryKinds(input);
			const diagnosticEscalation = hasDiagnostics && diagnosticKinds.some((kind) => !lastFlushDiagnosticKinds.has(kind));
			if (current - lastFlushMs < TUNNEL_HEALTH_TELEMETRY_FLUSH_INTERVAL_MS && !diagnosticEscalation) return false;
			try {
				await postTunnelHealthTelemetry(buildTunnelHealthTelemetryPayload(input));
				lastFlushMs = current;
				lastFlushDiagnosticKinds = new Set(diagnosticKinds);
				return true;
			} catch {
				return false;
			}
		},
	};
}
