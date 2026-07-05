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

const UTF8_SINGLE_BYTE_LIMIT = 0x7f;
const UTF8_TWO_BYTE_LIMIT = 0x7ff;
const UTF8_THREE_BYTE_LIMIT = 0xffff;
const UTF8_CONTINUATION_PREFIX = 0x80;
const UTF8_TWO_BYTE_PREFIX = 0xc0;
const UTF8_THREE_BYTE_PREFIX = 0xe0;
const UTF8_FOUR_BYTE_PREFIX = 0xf0;
const UTF8_PAYLOAD_MASK = 0x3f;
const BITS_PER_UTF8_CONTINUATION_BYTE = 6;
const BASE64_URL_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
const BASE64_CHUNK_BYTE_COUNT = 3;
const BASE64_CHUNK_FIRST_BYTE_SHIFT = 16;
const BASE64_CHUNK_SECOND_BYTE_SHIFT = 8;
const BASE64_SEXTET_MASK = 0x3f;
const BASE64_SEXTET_SHIFTS = [18, 12, 6, 0] as const;

export const TUNNEL_MEDIA = new Set<TunnelMedium>(["vpn", "sd_wan", "satellite"]);

export function isTunnelMedium(
  medium: GraphLink["medium"] | string | undefined | null,
): medium is TunnelMedium {
  return medium === "vpn" || medium === "sd_wan" || medium === "satellite";
}

function utf8Bytes(value: string): number[] {
  const bytes: number[] = [];
  for (const character of value) {
    const codePoint = character.codePointAt(0) ?? 0;
    if (codePoint <= UTF8_SINGLE_BYTE_LIMIT) {
      bytes.push(codePoint);
    } else if (codePoint <= UTF8_TWO_BYTE_LIMIT) {
      bytes.push(
        UTF8_TWO_BYTE_PREFIX | (codePoint >> BITS_PER_UTF8_CONTINUATION_BYTE),
        UTF8_CONTINUATION_PREFIX | (codePoint & UTF8_PAYLOAD_MASK),
      );
    } else if (codePoint <= UTF8_THREE_BYTE_LIMIT) {
      bytes.push(
        UTF8_THREE_BYTE_PREFIX | (codePoint >> (BITS_PER_UTF8_CONTINUATION_BYTE * 2)),
        UTF8_CONTINUATION_PREFIX |
          ((codePoint >> BITS_PER_UTF8_CONTINUATION_BYTE) & UTF8_PAYLOAD_MASK),
        UTF8_CONTINUATION_PREFIX | (codePoint & UTF8_PAYLOAD_MASK),
      );
    } else {
      bytes.push(
        UTF8_FOUR_BYTE_PREFIX | (codePoint >> (BITS_PER_UTF8_CONTINUATION_BYTE * 3)),
        UTF8_CONTINUATION_PREFIX |
          ((codePoint >> (BITS_PER_UTF8_CONTINUATION_BYTE * 2)) & UTF8_PAYLOAD_MASK),
        UTF8_CONTINUATION_PREFIX |
          ((codePoint >> BITS_PER_UTF8_CONTINUATION_BYTE) & UTF8_PAYLOAD_MASK),
        UTF8_CONTINUATION_PREFIX | (codePoint & UTF8_PAYLOAD_MASK),
      );
    }
  }
  return bytes;
}

function base64UrlEncodeUtf8(value: string): string {
  const bytes = utf8Bytes(value);
  let encoded = "";
  for (let index = 0; index < bytes.length; index += BASE64_CHUNK_BYTE_COUNT) {
    const first = bytes[index];
    const second = bytes[index + 1];
    const third = bytes[index + 2];
    const chunk =
      (first << BASE64_CHUNK_FIRST_BYTE_SHIFT) |
      ((second ?? 0) << BASE64_CHUNK_SECOND_BYTE_SHIFT) |
      (third ?? 0);
    encoded += BASE64_URL_ALPHABET[(chunk >> BASE64_SEXTET_SHIFTS[0]) & BASE64_SEXTET_MASK];
    encoded += BASE64_URL_ALPHABET[(chunk >> BASE64_SEXTET_SHIFTS[1]) & BASE64_SEXTET_MASK];
    // Omit padding instead of writing "=" so the ID remains URL/path safe.
    if (second !== undefined) {
      encoded += BASE64_URL_ALPHABET[
        (chunk >> BASE64_SEXTET_SHIFTS[2]) & BASE64_SEXTET_MASK
      ];
    }
    if (third !== undefined) encoded += BASE64_URL_ALPHABET[chunk & BASE64_SEXTET_MASK];
  }
  return encoded;
}

export function encodeTunnelLinkId(
  link: Pick<GraphLink, "source" | "relationship" | "target" | "medium">,
): string {
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
  if (health?.icmp?.available === false || health?.icmp?.error || reason === "icmp_failed") {
    return "icmp_failed";
  }
  return null;
}

function warningLabel(warning: TunnelWarning): string | null {
  if (warning === "missing_public_ip") return "Missing public IP";
  if (warning === "icmp_poor_rtt") return "Poor ICMP RTT";
  if (warning === "icmp_failed") return "ICMP failed";
  return null;
}

export function buildTunnelTooltipRows(
  visual: Pick<
    TunnelVisualModel,
    "mediumLabel" | "authorityText" | "warning" | "stale" | "errorKind"
  >,
): TunnelTooltipRow[] {
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
  const medium = isTunnelMedium(health?.medium)
    ? health.medium
    : isTunnelMedium(link.medium)
      ? link.medium
      : null;
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
