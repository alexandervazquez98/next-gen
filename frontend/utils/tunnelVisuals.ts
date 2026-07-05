import type {
	CategoryIconKey,
	GraphLink,
	TunnelHealthErrorKind,
	TunnelHealthResponse,
	TunnelMedium,
	TunnelTooltipRow,
	TunnelVisualModel,
	TunnelWarning,
} from "../types";

const TUNNEL_MEDIUM_LABELS: Record<TunnelMedium, string> = {
	vpn: "VPN tunnel",
	sd_wan: "SD-WAN tunnel",
	satellite: "Satellite link",
};

const TUNNEL_MEDIUM_ICONS: Record<TunnelMedium, CategoryIconKey> = {
	vpn: "vpn_tunnel",
	sd_wan: "sd_wan_tunnel",
	satellite: "satellite_link",
};

export const TUNNEL_MEDIA = new Set<TunnelMedium>(["vpn", "sd_wan", "satellite"]);

export function isTunnelMedium(medium: GraphLink["medium"] | string | undefined | null): medium is TunnelMedium {
	return medium === "vpn" || medium === "sd_wan" || medium === "satellite";
}

function base64UrlEncodeUtf8(value: string): string {
	const bytes = new TextEncoder().encode(value);
	let binary = "";
	for (const byte of bytes) binary += String.fromCharCode(byte);
	return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

export function encodeTunnelLinkId(link: Pick<GraphLink, "source" | "relationship" | "target" | "medium">): string {
	const payload = {
		source: String(link.source),
		relationship: String(link.relationship),
		target: String(link.target),
		medium: link.medium ?? "vpn",
	};
	return base64UrlEncodeUtf8(JSON.stringify(payload));
}

function warningFromHealth(health?: TunnelHealthResponse): TunnelWarning {
	const reason = health?.icmp?.reason;
	if (reason === "missing_public_ip") return "missing_public_ip";
	if (reason === "poor_rtt" || reason === "icmp_poor_rtt") return "icmp_poor_rtt";
	if (health?.icmp?.available === false || health?.icmp?.error || reason === "icmp_failed") return "icmp_failed";
	return null;
}

function warningLabel(warning: TunnelWarning): string | null {
	if (warning === "missing_public_ip") return "Missing public IP";
	if (warning === "icmp_poor_rtt") return "Poor ICMP RTT";
	if (warning === "icmp_failed") return "ICMP failed";
	return null;
}

export function buildTunnelTooltipRows(visual: Pick<TunnelVisualModel, "mediumLabel" | "authorityText" | "warning" | "stale" | "errorKind">): TunnelTooltipRow[] {
	const rows: TunnelTooltipRow[] = [
		{ label: "Medium", value: visual.mediumLabel },
		{ label: "Authority", value: visual.authorityText },
	];
	const warning = warningLabel(visual.warning);
	if (warning) rows.push({ label: "ICMP", value: warning });
	if (visual.stale) rows.push({ label: "Cache", value: "Using stale health" });
	if (visual.errorKind) rows.push({ label: "Health", value: `Unavailable: ${visual.errorKind}` });
	return rows;
}

export function resolveTunnelVisual(
	link: Pick<GraphLink, "medium">,
	health?: TunnelHealthResponse,
	options: { stale?: boolean; errorKind?: TunnelHealthErrorKind } = {},
): TunnelVisualModel {
	const medium = isTunnelMedium(health?.medium) ? health.medium : isTunnelMedium(link.medium) ? link.medium : null;
	const authorityText = health?.status ?? "UNKNOWN";
	const state = authorityText === "UP" ? "up" : authorityText === "DOWN" ? "down" : "unknown";
	const warning = warningFromHealth(health);
	const base = {
		medium,
		mediumLabel: medium ? TUNNEL_MEDIUM_LABELS[medium] : "Tunnel",
		iconKey: medium ? TUNNEL_MEDIUM_ICONS[medium] : "generic",
		authorityText,
		state,
		warning,
		healthAffectsIcon: false as const,
		stale: options.stale ?? false,
		errorKind: options.errorKind,
	};
	return { ...base, tooltipRows: buildTunnelTooltipRows(base) };
}
