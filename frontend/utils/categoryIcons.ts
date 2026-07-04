import type { CategoryIconKey } from "../types";

export type CategoryIconEntry = {
  key: CategoryIconKey;
  label: string;
  materialSymbol: string;
  aliases?: string[];
};

const CATEGORY_ICON_KEY_SET = new Set<string>([
  "generic",
  "switch_l2",
  "switch_l3",
  "router",
  "server",
  "saas",
  "storage",
  "camera",
  "video_analytics",
  "radio_telecom",
  "trunk_link",
  "access_ci",
  "distribution_ci",
  "vpn_tunnel",
  "sd_wan_tunnel",
  "satellite_link",
  "vpn_hub",
]);

export const CATEGORY_ICON_CATALOG: CategoryIconEntry[] = [
  {
    key: "generic",
    label: "Generic",
    materialSymbol: "category",
    aliases: ["default", "default icon", "general"],
  },
  {
    key: "switch_l2",
    label: "Layer 2 Switch",
    materialSymbol: "lan",
    aliases: ["l2", "layer 2", "switch"],
  },
  {
    key: "switch_l3",
    label: "Layer 3 Switch",
    materialSymbol: "hub",
    aliases: ["l3", "layer 3", "router switch", "layer3"],
  },
  {
    key: "router",
    label: "Router",
    materialSymbol: "router",
    aliases: ["gateway", "routing"],
  },
  {
    key: "server",
    label: "Server",
    materialSymbol: "dns",
    aliases: ["compute", "host"],
  },
  {
    key: "saas",
    label: "SaaS",
    materialSymbol: "cloud",
    aliases: ["software as a service", "managed service"],
  },
  {
    key: "storage",
    label: "Storage",
    materialSymbol: "storage",
    aliases: ["nas", "san", "backup"],
  },
  {
    key: "camera",
    label: "Cameras",
    materialSymbol: "videocam",
    aliases: ["cctv", "video"],
  },
  {
    key: "video_analytics",
    label: "Video Analytics",
    materialSymbol: "analytics",
    aliases: ["analytics", "video analysis", "ai video"],
  },
  {
    key: "radio_telecom",
    label: "Radio (Telecom)",
    materialSymbol: "settings_input_antenna",
    aliases: ["radio", "antenna", "wireless", "telecom radio", "radioenlace"],
  },
  {
    key: "trunk_link",
    label: "Trunk Link",
    materialSymbol: "linear_scale",
    aliases: ["trunk", "backbone", "uplink", "troncal", "troncal de red"],
  },
  {
    key: "access_ci",
    label: "Access CI",
    materialSymbol: "input",
    aliases: ["access", "access ci", "access node", "acceso", "nodo de acceso"],
  },
  {
    key: "distribution_ci",
    label: "Distribution CI",
    materialSymbol: "layers",
    aliases: [
      "distribution",
      "distribution ci",
      "distribution layer",
      "distribucion",
      "distribución",
      "capa distribucion",
    ],
  },
  {
    // Slice 1 (feat-324) — tunnel technology icons. These icons identify
    // the transport only; health/state styling is rendered separately by
    // the visual layer so an UP tunnel keeps showing the technology icon.
    key: "vpn_tunnel",
    label: "VPN Tunnel",
    materialSymbol: "vpn_key",
    aliases: ["vpn", "ipsec", "tls tunnel", "tunel vpn", "red privada virtual"],
  },
  {
    key: "sd_wan_tunnel",
    label: "SD-WAN Tunnel",
    materialSymbol: "hub",
    aliases: ["sd-wan", "sdwan", "wan", "overlay", "tunel sd-wan"],
  },
  {
    key: "satellite_link",
    label: "Satellite Link",
    materialSymbol: "satellite_alt",
    aliases: ["satellite", "sat link", "satcom", "satelite", "enlace satelital"],
  },
  {
    key: "vpn_hub",
    label: "VPN Hub",
    materialSymbol: "vpn_lock",
    aliases: ["vpn hub", "hub vpn", "vpn concentrator", "concentrador vpn", "hub concentrator"],
  },
];

const DEFAULT_ICON_KEY: CategoryIconKey = "generic";

const CATEGORY_NAME_TO_ICON: Record<string, CategoryIconKey> = {
  "layer2 switch": "switch_l2",
  "l2 switch": "switch_l2",
  "switch l2": "switch_l2",
  "layer3 switch": "switch_l3",
  "l3 switch": "switch_l3",
  "switch l3": "switch_l3",
  router: "router",
  server: "server",
  saas: "saas",
  storage: "storage",
  camera: "camera",
  cameras: "camera",
  "video analytics": "video_analytics",
  video_analytics: "video_analytics",
  radio: "radio_telecom",
  "radio telecom": "radio_telecom",
  radioenlace: "radio_telecom",
  trunk: "trunk_link",
  "trunk link": "trunk_link",
  troncal: "trunk_link",
  access: "access_ci",
  "access ci": "access_ci",
  acceso: "access_ci",
  distribution: "distribution_ci",
  "distribution ci": "distribution_ci",
  distribucion: "distribution_ci",
  // Slice 1 (feat-324) — default icon inference for tunnel categories.
  // Both English and Spanish spellings are accepted; the normalize pass
  // (with diacritic stripping) collapses accented Spanish input to its
  // ASCII dictionary form before this lookup runs.
  "vpn hub": "vpn_hub",
  vpn_hub: "vpn_hub",
  "hub vpn": "vpn_hub",
  "concentrador vpn": "vpn_hub",
  "vpn concentrator": "vpn_hub",
};

const INDEXED_CATALOG = new Map<string, CategoryIconEntry>(
  CATEGORY_ICON_CATALOG.map((entry) => [entry.key, entry]),
);

export const isCategoryIconKey = (value?: string | null): value is CategoryIconKey =>
  typeof value === "string" && CATEGORY_ICON_KEY_SET.has(value);

export const getCategoryIconEntry = (iconKey: string): CategoryIconEntry => {
  if (isCategoryIconKey(iconKey)) {
    return INDEXED_CATALOG.get(iconKey) ?? INDEXED_CATALOG.get(DEFAULT_ICON_KEY)!;
  }
  return INDEXED_CATALOG.get(DEFAULT_ICON_KEY)!;
};

export const normalizeCategoryName = (categoryName: string): string => {
  return (
    categoryName
      .trim()
      .toLowerCase()
      // Strip combining diacritics first so accented Spanish input
      // (e.g. "Concentrador VPN" or "Distribución") collapses to its
      // ASCII dictionary form before the [^a-z0-9]+ normalization below.
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^a-z0-9]+/g, " ")
      .replace(/\blayer\s+2\b/g, "layer2")
      .replace(/\blayer\s+3\b/g, "layer3")
      .replace(/\s+/g, " ")
      .trim()
  );
};

export const resolveCategoryIconKey = ({
  iconKey,
  categoryName,
}: {
  iconKey?: string | null;
  categoryName?: string | null;
}): CategoryIconKey => {
  if (isCategoryIconKey(iconKey)) {
    return iconKey;
  }

  if (categoryName) {
    const normalized = normalizeCategoryName(categoryName);
    if (CATEGORY_NAME_TO_ICON[normalized]) {
      return CATEGORY_NAME_TO_ICON[normalized];
    }

    for (const [name, key] of Object.entries(CATEGORY_NAME_TO_ICON)) {
      if (name.includes(normalized) || normalized.includes(name)) {
        return key;
      }
    }
  }

  return DEFAULT_ICON_KEY;
};

const includesQuery = (value: string, query: string): boolean => {
  const normalizedValue = normalizeCategoryName(value);
  const normalizedQuery = normalizeCategoryName(query);
  return normalizedValue.includes(normalizedQuery);
};

export const findCategoryIcons = (query: string): CategoryIconEntry[] => {
  const normalizedQuery = normalizeCategoryName(query);
  if (!normalizedQuery) {
    return CATEGORY_ICON_CATALOG;
  }

  return CATEGORY_ICON_CATALOG.filter((entry) => {
    const aliasText = (entry.aliases ?? []).join(" ");
    return (
      includesQuery(entry.label, normalizedQuery) ||
      includesQuery(entry.key, normalizedQuery) ||
      includesQuery(aliasText, normalizedQuery)
    );
  });
};

export type ResolveCategoryIconArgs = {
  iconKey?: string | null;
  categoryName?: string | null;
};
