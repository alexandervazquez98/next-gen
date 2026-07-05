import { describe, expect, it } from "vitest";
import {
	buildTunnelTooltipRows,
	encodeTunnelLinkId,
	resolveTunnelVisual,
} from "./tunnelVisuals";
import type { GraphLink, TunnelHealthResponse } from "../types";

const asciiLink: GraphLink = {
	id: "edge",
	source: "hub-a",
	relationship: "CONNECTS_TO",
	target: "edge-b",
	medium: "vpn",
};

const utf8Link: GraphLink = {
	id: "edge-utf8",
	source: "Madrid-ñ",
	relationship: "CONNECTS_TO",
	target: "München-東",
	medium: "sd_wan",
};

describe("tunnelVisuals", () => {
	it("encodes canonical link IDs using backend field order and unpadded base64url", () => {
		expect(encodeTunnelLinkId(asciiLink)).toBe(
			"eyJzb3VyY2UiOiJodWItYSIsInJlbGF0aW9uc2hpcCI6IkNPTk5FQ1RTX1RPIiwidGFyZ2V0IjoiZWRnZS1iIiwibWVkaXVtIjoidnBuIn0",
		);
		expect(encodeTunnelLinkId(asciiLink)).not.toContain("=");
	});

	it("encodes UTF-8 endpoint identifiers deterministically", () => {
		expect(encodeTunnelLinkId(utf8Link)).toBe(
			"eyJzb3VyY2UiOiJNYWRyaWQtw7EiLCJyZWxhdGlvbnNoaXAiOiJDT05ORUNUU19UTyIsInRhcmdldCI6Ik3DvG5jaGVuLeadsSIsIm1lZGl1bSI6InNkX3dhbiJ9",
		);
		expect(encodeTunnelLinkId(utf8Link)).toMatch(/^[A-Za-z0-9_-]+$/);
	});

	it("keeps authority labels separate from ICMP warning context", () => {
		const health: TunnelHealthResponse = {
			link_id: "link-1",
			source: "hub-a",
			target: "edge-b",
			relationship: "CONNECTS_TO",
			medium: "vpn",
			status: "UP",
			authority: { state: "UP", source: "SNMP", observed_at: null, reason: "sample" },
			icmp: { available: false, latency_ms: null, error: "timeout", reason: "icmp_failed" },
			observed_at: "2026-07-04T10:00:00Z",
		};

		expect(resolveTunnelVisual(asciiLink, health)).toMatchObject({
			mediumLabel: "VPN tunnel",
			iconKey: "vpn_tunnel",
			authorityText: "UP",
			state: "up",
			warning: "icmp_failed",
			healthAffectsIcon: false,
		});
	});

	it("renders UNKNOWN and missing public IP as neutral tooltip context only", () => {
		const health: TunnelHealthResponse = {
			link_id: "link-2",
			source: "hub-a",
			target: "edge-b",
			relationship: "CONNECTS_TO",
			medium: "satellite",
			status: "UNKNOWN",
			authority: { state: null, source: null, observed_at: null, reason: "no_sample" },
			icmp: { available: false, latency_ms: null, error: null, reason: "missing_public_ip" },
			observed_at: null,
		};

		const visual = resolveTunnelVisual({ ...asciiLink, medium: "satellite" }, health);
		expect(visual).toMatchObject({
			mediumLabel: "Satellite link",
			iconKey: "satellite_link",
			authorityText: "UNKNOWN",
			state: "unknown",
			warning: "missing_public_ip",
		});
		expect(buildTunnelTooltipRows(visual)).toContainEqual({ label: "ICMP", value: "Missing public IP" });
	});

	it("returns deterministic fallback visuals when health is unavailable", () => {
		const visual = resolveTunnelVisual({ ...asciiLink, medium: undefined }, undefined, {
			errorKind: "network",
		});

		expect(visual).toMatchObject({
			mediumLabel: "Tunnel",
			iconKey: "generic",
			authorityText: "UNKNOWN",
			state: "unknown",
			warning: null,
		});
		expect(buildTunnelTooltipRows(visual)).toContainEqual({
			label: "Health",
			value: "Unavailable: network",
		});
	});
});
