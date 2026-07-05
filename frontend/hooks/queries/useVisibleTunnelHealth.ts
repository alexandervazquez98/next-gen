import { useEffect, useMemo, useRef, useState } from "react";
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../../services/api";
import type { GraphLink, TunnelHealthErrorKind, TunnelHealthResponse } from "../../types";
import { queryKeys } from "../../services/queryKeys";
import { fetchTunnelHealth } from "../../services/queryResources";
import { encodeTunnelLinkId, isTunnelMedium, resolveTunnelVisual } from "../../utils/tunnelVisuals";
import { createTunnelHealthTelemetryBatcher } from "../../utils/tunnelHealthTelemetry";

export const TUNNEL_HEALTH_LIMITS = {
	maxVisibleLinks: 50,
	maxInFlight: 4,
	baseIntervalMs: 30_000,
	cooldownMs: 120_000,
	maxRequestsPerMinute: 120,
} as const;

type VisibleLink = GraphLink & { visible?: boolean; hidden?: boolean };
type CooldownMap = Record<string, number>;

export interface VisibleTunnelHealthPlan {
	linkIds: string[];
	skippedOverCap: number;
	suppressedCooldown: number;
	pollingDisabled: boolean;
	refetchIntervalMs: number;
	retry: false;
	requestBudgetPerMinute: number;
}

const telemetryBatcher = createTunnelHealthTelemetryBatcher();

function envPollingDisabled(): boolean {
	const env = (import.meta as unknown as { env?: Record<string, string | undefined> }).env;
	return env?.VITE_TUNNEL_HEALTH_POLLING === "false";
}

function runtimePollingDisabled(): boolean {
	try {
		return globalThis.localStorage?.getItem("tunnelHealthPollingDisabled") === "true";
	} catch {
		return false;
	}
}

function deterministicJitter(seed: number): number {
	return 0.1 + Math.min(1, Math.max(0, seed)) * 0.1;
}

export function buildVisibleTunnelHealthPlan(
	links: VisibleLink[],
	options: {
		nowMs?: number;
		cooldownUntilByLinkId?: Record<string, number>;
		pollingDisabled?: boolean;
		jitterSeed?: number;
	} = {},
): VisibleTunnelHealthPlan {
	const pollingDisabled = options.pollingDisabled ?? (envPollingDisabled() || runtimePollingDisabled());
	const refetchIntervalMs = Math.round(
		TUNNEL_HEALTH_LIMITS.baseIntervalMs * (1 + deterministicJitter(options.jitterSeed ?? 0)),
	);
	if (pollingDisabled) {
		return { linkIds: [], skippedOverCap: 0, suppressedCooldown: 0, pollingDisabled: true, refetchIntervalMs, retry: false, requestBudgetPerMinute: 0 };
	}

	const nowMs = options.nowMs ?? Date.now();
	const unique = new Set<string>();
	let suppressedCooldown = 0;
	for (const link of links) {
		if (link.visible === false || link.hidden || !isTunnelMedium(link.medium)) continue;
		const linkId = encodeTunnelLinkId(link);
		if ((options.cooldownUntilByLinkId?.[linkId] ?? 0) > nowMs) {
			suppressedCooldown += 1;
			continue;
		}
		unique.add(linkId);
	}
	const allLinkIds = Array.from(unique);
	const linkIds = allLinkIds.slice(0, TUNNEL_HEALTH_LIMITS.maxVisibleLinks);
	return {
		linkIds,
		skippedOverCap: Math.max(0, allLinkIds.length - linkIds.length),
		suppressedCooldown,
		pollingDisabled: false,
		refetchIntervalMs,
		retry: false,
		requestBudgetPerMinute: Math.min(TUNNEL_HEALTH_LIMITS.maxRequestsPerMinute, linkIds.length * 2),
	};
}

export function selectActiveTunnelHealthIds(linkIds: string[], cycle: number): string[] {
	if (linkIds.length <= TUNNEL_HEALTH_LIMITS.maxInFlight) return linkIds;
	const start = (cycle * TUNNEL_HEALTH_LIMITS.maxInFlight) % linkIds.length;
	return Array.from({ length: TUNNEL_HEALTH_LIMITS.maxInFlight }, (_, offset) => linkIds[(start + offset) % linkIds.length]);
}

export function classifyTunnelHealthError(error: unknown): TunnelHealthErrorKind {
	const status = error instanceof ApiError ? error.status : typeof (error as { status?: unknown })?.status === "number" ? (error as { status: number }).status : undefined;
	if (status === 400) return "bad_request";
	if (status === 404) return "not_found";
	if (status === 401 || status === 403) return "auth";
	if (typeof status === "number" && status >= 500) return "server";
	if ((error as { name?: unknown })?.name === "AbortError") return "timeout";
	return "network";
}

export function updateTunnelHealthCooldown(cooldown: CooldownMap, linkId: string, _errorKind: TunnelHealthErrorKind, nowMs: number): CooldownMap {
	return { ...cooldown, [linkId]: nowMs + TUNNEL_HEALTH_LIMITS.cooldownMs };
}

function pruneExpiredCooldowns(cooldown: CooldownMap, nowMs: number): CooldownMap {
	const activeEntries = Object.entries(cooldown).filter(([, cooldownUntil]) => cooldownUntil > nowMs);
	if (activeEntries.length === Object.keys(cooldown).length) return cooldown;
	return Object.fromEntries(activeEntries);
}

export function resolveTunnelHealthFallbackVisual(
	link: Pick<GraphLink, "medium">,
	staleHealth: TunnelHealthResponse | undefined,
	errorKind: TunnelHealthErrorKind,
) {
	return resolveTunnelVisual(link, staleHealth, { stale: Boolean(staleHealth), errorKind });
}

export function useVisibleTunnelHealth(links: VisibleLink[]) {
	const queryClient = useQueryClient();
	const [cycle, setCycle] = useState(0);
	const [cooldownUntilByLinkId, setCooldownUntilByLinkId] = useState<CooldownMap>({});
	const lastTelemetrySignature = useRef("");
	const failedQueriesRef = useRef<Array<{ linkId: string; errorKind: TunnelHealthErrorKind }>>([]);
	const linkById = useMemo(() => {
		const entries = links.filter((link) => isTunnelMedium(link.medium)).map((link) => [encodeTunnelLinkId(link), link] as const);
		return Object.fromEntries(entries) as Record<string, VisibleLink>;
	}, [links]);
	const plan = useMemo(() => buildVisibleTunnelHealthPlan(links, { cooldownUntilByLinkId }), [links, cooldownUntilByLinkId]);
	const activeLinkIds = useMemo(() => selectActiveTunnelHealthIds(plan.linkIds, cycle), [plan.linkIds, cycle]);

	useEffect(() => {
		if (plan.pollingDisabled || plan.linkIds.length <= TUNNEL_HEALTH_LIMITS.maxInFlight) return;
		const timer = window.setInterval(() => setCycle((current) => current + 1), plan.refetchIntervalMs);
		return () => window.clearInterval(timer);
	}, [plan.linkIds.length, plan.pollingDisabled, plan.refetchIntervalMs]);

	useEffect(() => {
		if (plan.pollingDisabled) return;
		const nowMs = Date.now();
		const cooldownUntilValues = Object.values(cooldownUntilByLinkId);
		const nextWakeMs = cooldownUntilValues.reduce<number | undefined>((next, cooldownUntil) => {
			if (cooldownUntil <= nowMs) return next;
			return next === undefined ? cooldownUntil : Math.min(next, cooldownUntil);
		}, undefined);

		setCooldownUntilByLinkId((current) => pruneExpiredCooldowns(current, nowMs));
		if (nextWakeMs === undefined) return;

		const timer = window.setTimeout(() => {
			setCooldownUntilByLinkId((current) => pruneExpiredCooldowns(current, Date.now()));
			setCycle((current) => current + 1);
		}, Math.max(0, nextWakeMs - nowMs) + 1);
		return () => window.clearTimeout(timer);
	}, [cooldownUntilByLinkId, plan.pollingDisabled]);

	const queries = useQueries({
		queries: activeLinkIds.map((linkId) => ({
			queryKey: queryKeys.tunnelHealth(linkId),
			queryFn: ({ signal }: { signal?: AbortSignal }) => fetchTunnelHealth(linkId, { signal }),
			refetchInterval: plan.refetchIntervalMs,
			retry: false,
		})),
	});

	const { healthByLinkId, visualByLinkId, failureByKind, success, failedQueries } = useMemo(() => {
		const nextHealthByLinkId: Record<string, TunnelHealthResponse> = {};
		const nextVisualByLinkId: Record<string, ReturnType<typeof resolveTunnelVisual>> = {};
		const nextFailureByKind: Partial<Record<TunnelHealthErrorKind, number>> = {};
		const nextFailedQueries: Array<{ linkId: string; errorKind: TunnelHealthErrorKind }> = [];
		let nextSuccess = 0;

		activeLinkIds.forEach((linkId, index) => {
			const query = queries[index];
			const data = query?.data;
			if (data) {
				nextSuccess += 1;
				nextHealthByLinkId[linkId] = data;
				nextVisualByLinkId[linkId] = resolveTunnelVisual({ medium: data.medium }, data);
				return;
			}
			if (query?.error) {
				const errorKind = classifyTunnelHealthError(query.error);
				nextFailedQueries.push({ linkId, errorKind });
				nextFailureByKind[errorKind] = (nextFailureByKind[errorKind] ?? 0) + 1;
				const staleHealth = queryClient.getQueryData<TunnelHealthResponse>(queryKeys.tunnelHealth(linkId));
				nextVisualByLinkId[linkId] = resolveTunnelHealthFallbackVisual(linkById[linkId] ?? { medium: undefined }, staleHealth, errorKind);
			}
		});

		return {
			healthByLinkId: nextHealthByLinkId,
			visualByLinkId: nextVisualByLinkId,
			failureByKind: nextFailureByKind,
			success: nextSuccess,
			failedQueries: nextFailedQueries,
		};
	}, [activeLinkIds, linkById, queries, queryClient]);
	const failedQueriesSignature = failedQueries.map(({ linkId, errorKind }) => `${linkId}:${errorKind}`).join("|");
	// The cooldown effect should run only when the set of failures changes. Reading the
	// current array through a ref avoids depending on the memoized array identity, which
	// can churn with React Query updates and repeatedly extend cooldowns.
	failedQueriesRef.current = failedQueries;

	useEffect(() => {
		const currentFailedQueries = failedQueriesRef.current;
		if (currentFailedQueries.length === 0) return;
		setCooldownUntilByLinkId((current) => {
			const nowMs = Date.now();
			return currentFailedQueries.reduce((next, item) => updateTunnelHealthCooldown(next, item.linkId, item.errorKind, nowMs), current);
		});
	}, [failedQueriesSignature]);

	useEffect(() => {
		const signature = JSON.stringify({ scheduled: activeLinkIds.length, skipped: plan.skippedOverCap, suppressed: plan.suppressedCooldown, success, failureByKind, disabled: plan.pollingDisabled });
		if (signature === lastTelemetrySignature.current) return;
		lastTelemetrySignature.current = signature;
		void telemetryBatcher.flush({
			scheduled: activeLinkIds.length,
			skippedOverCap: plan.skippedOverCap,
			suppressedCooldown: plan.suppressedCooldown,
			success,
			failureByKind,
			killSwitchEnabled: plan.pollingDisabled,
		});
	}, [activeLinkIds.length, failureByKind, plan.pollingDisabled, plan.skippedOverCap, plan.suppressedCooldown, success]);

	return { ...plan, healthByLinkId, visualByLinkId };
}
