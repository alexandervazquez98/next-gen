import { describe, expect, it } from "vitest";
import {
  CATEGORY_ICON_CATALOG,
  findCategoryIcons,
  getCategoryIconEntry,
  normalizeCategoryName,
  isCategoryIconKey,
  resolveCategoryIconKey,
} from "./categoryIcons";

describe("categoryIcons utility", () => {
  it("resolves known icon keys to catalog entries", () => {
    const routerEntry = getCategoryIconEntry("router");
    const serverEntry = getCategoryIconEntry("server");

    expect(routerEntry.key).toBe("router");
    expect(routerEntry.label).toBe("Router");
    expect(routerEntry.materialSymbol).toBe("router");
    expect(routerEntry.materialSymbol).not.toBe("");

    expect(serverEntry.key).toBe("server");
    expect(serverEntry.label).toBe("Server");
    expect(serverEntry.materialSymbol).not.toBe("");
  });

  it("searches catalog entries by query", () => {
    const switches = findCategoryIcons("switch");
    const results = switches.map((entry) => entry.key);

    expect(results).toEqual(expect.arrayContaining(["switch_l2", "switch_l3"]));
    expect(switches).toHaveLength(2);

    const none = findCategoryIcons("non-existent-technology");
    expect(none).toHaveLength(0);
  });

  it("falls back to generic icon for invalid icon keys", () => {
    expect(resolveCategoryIconKey({ iconKey: "bad-key" })).toBe("generic");
    expect(resolveCategoryIconKey({ iconKey: "bad-key", categoryName: "Router" })).toBe("router");
    expect(resolveCategoryIconKey({ categoryName: "Unknown Category" })).toBe("generic");
    expect(isCategoryIconKey("bad-key")).toBe(false);
  });

  it("infers initial default icon by category name", () => {
    expect(resolveCategoryIconKey({ categoryName: "Layer 2 switch" })).toBe("switch_l2");
    expect(resolveCategoryIconKey({ categoryName: "Layer 3 switch" })).toBe("switch_l3");
    expect(resolveCategoryIconKey({ categoryName: "Video Analytics" })).toBe("video_analytics");
    expect(resolveCategoryIconKey({ categoryName: "", iconKey: "camera" })).toBe("camera");
  });

  it("normalizes category names consistently", () => {
    expect(normalizeCategoryName(" Layer-2 SWITCH  ")).toBe("layer2 switch");
    expect(normalizeCategoryName("Layer   3   switch")).toBe("layer3 switch");
    expect(normalizeCategoryName("Cameras")).toBe("cameras");
    expect(CATEGORY_ICON_CATALOG).toBeInstanceOf(Array);
    expect(CATEGORY_ICON_CATALOG.length).toBeGreaterThan(0);
  });

  it("guarantees no blank symbol for unknown lookup", () => {
    const unknownEntry = getCategoryIconEntry("mystery");
    expect(unknownEntry.key).toBe("generic");
    expect(unknownEntry.materialSymbol).toBe("category");
    expect(unknownEntry.materialSymbol).not.toBe("");
  });
});

// ===========================================================================
// Slice 1 (feat-324) — VPN/SD-WAN/satellite tunnel icon keys + vpn_hub
// ===========================================================================

describe("categoryIcons — VPN/SD-WAN/satellite tunnel entries", () => {
  it("exposes the four new keys in the catalog with non-empty fixed Material Symbols", () => {
    // Each new key resolves to a catalog entry with a fixed, non-empty
    // Material Symbol name (we never want to fall back to "category" or
    // the empty string for any tunnel technology).
    const expected: Array<{
      key: "vpn_tunnel" | "sd_wan_tunnel" | "satellite_link" | "vpn_hub";
      symbol: string;
    }> = [
      { key: "vpn_tunnel", symbol: "vpn_key" },
      { key: "sd_wan_tunnel", symbol: "hub" },
      { key: "satellite_link", symbol: "satellite_alt" },
      { key: "vpn_hub", symbol: "vpn_lock" },
    ];

    for (const { key, symbol } of expected) {
      const entry = getCategoryIconEntry(key);
      expect(entry.key).toBe(key);
      expect(entry.materialSymbol).toBe(symbol);
      expect(entry.materialSymbol).not.toBe("");
      expect(entry.materialSymbol).not.toBe("category");
    }

    // Sanity: the catalog really contains all four.
    const catalogKeys = CATEGORY_ICON_CATALOG.map((e) => e.key);
    for (const { key } of expected) {
      expect(catalogKeys).toContain(key);
    }
  });

  it("accepts the four new keys as controlled category icon keys", () => {
    // isCategoryIconKey is the membership gate used by every consumer
    // before reading catalog data; without these entries it would return
    // false and force the generic fallback.
    expect(isCategoryIconKey("vpn_tunnel")).toBe(true);
    expect(isCategoryIconKey("sd_wan_tunnel")).toBe(true);
    expect(isCategoryIconKey("satellite_link")).toBe(true);
    expect(isCategoryIconKey("vpn_hub")).toBe(true);
  });

  it("finds each new entry by English search terms", () => {
    const vpnResults = findCategoryIcons("vpn").map((e) => e.key);
    expect(vpnResults).toContain("vpn_tunnel");
    expect(vpnResults).toContain("vpn_hub");

    const sdwanResults = findCategoryIcons("sd-wan").map((e) => e.key);
    expect(sdwanResults).toContain("sd_wan_tunnel");

    const satResults = findCategoryIcons("satellite").map((e) => e.key);
    expect(satResults).toContain("satellite_link");
  });

  it("finds each new entry by Spanish search terms", () => {
    // Tildes / accents must survive normalization for Spanish aliases to
    // hit the catalog (matching the #325 diacritic-stripping change).
    const vpnEs = findCategoryIcons("Concentrador VPN").map((e) => e.key);
    expect(vpnEs).toContain("vpn_hub");

    const satEs = findCategoryIcons("Satélite").map((e) => e.key);
    expect(satEs).toContain("satellite_link");

    const sdwanEs = findCategoryIcons("Túnel SD-WAN").map((e) => e.key);
    expect(sdwanEs).toContain("sd_wan_tunnel");
  });

  it("infers default icon key from English vpn_hub category names", () => {
    expect(resolveCategoryIconKey({ categoryName: "VPN Hub" })).toBe("vpn_hub");
    expect(resolveCategoryIconKey({ categoryName: "vpn_hub" })).toBe("vpn_hub");
  });

  it("infers default icon key from Spanish vpn_hub category names", () => {
    expect(resolveCategoryIconKey({ categoryName: "Concentrador VPN" })).toBe("vpn_hub");
    expect(resolveCategoryIconKey({ categoryName: "Hub VPN" })).toBe("vpn_hub");
  });

  it("preserves the generic fallback for unrelated categories", () => {
    // Negative case: even with the new entries present, an unknown
    // category still falls back to "generic" so consumers can rely on
    // the existing contract.
    expect(resolveCategoryIconKey({ categoryName: "Mystery Category" })).toBe("generic");
    expect(resolveCategoryIconKey({ iconKey: "vpn_tunnel" })).toBe("vpn_tunnel");
    expect(resolveCategoryIconKey({ iconKey: "bogus-key", categoryName: "Mystery" })).toBe(
      "generic",
    );
  });
});

describe("categoryIcons — radio/trunk/access/distribution entries", () => {
  const NEW_KEYS = ["radio_telecom", "trunk_link", "access_ci", "distribution_ci"] as const;

  const FIXED_SYMBOLS: Record<(typeof NEW_KEYS)[number], string> = {
    radio_telecom: "settings_input_antenna",
    trunk_link: "linear_scale",
    access_ci: "input",
    distribution_ci: "layers",
  };

  it("exposes the four new keys in the catalog with non-empty fixed Material Symbols", () => {
    for (const key of NEW_KEYS) {
      const entry = CATEGORY_ICON_CATALOG.find((candidate) => candidate.key === key);
      expect(entry, `catalog should contain ${key}`).toBeDefined();
      expect(entry?.materialSymbol).toBe(FIXED_SYMBOLS[key]);
      expect(entry?.materialSymbol).not.toBe("");
      expect(entry?.label).not.toBe("");
    }
  });

  it("accepts the four new keys as controlled category icon keys", () => {
    for (const key of NEW_KEYS) {
      expect(isCategoryIconKey(key), `${key} should be a valid icon key`).toBe(true);
      const entry = getCategoryIconEntry(key);
      expect(entry.key).toBe(key);
      expect(entry.key).not.toBe("generic");
    }
  });

  it("falls back to generic for invalid icon keys even after the new entries exist", () => {
    expect(resolveCategoryIconKey({ iconKey: "bad-key" })).toBe("generic");
    expect(getCategoryIconEntry("bad-key").key).toBe("generic");
    expect(getCategoryIconEntry("mystery").materialSymbol).not.toBe("");
    expect(isCategoryIconKey("bad-key")).toBe(false);
  });

  it("finds each new entry by English search terms", () => {
    const cases: Array<{ query: string; expectedKey: (typeof NEW_KEYS)[number] }> = [
      { query: "radio", expectedKey: "radio_telecom" },
      { query: "trunk", expectedKey: "trunk_link" },
      { query: "access", expectedKey: "access_ci" },
      { query: "distribution", expectedKey: "distribution_ci" },
    ];

    for (const { query, expectedKey } of cases) {
      const results = findCategoryIcons(query);
      const keys = results.map((entry) => entry.key);
      expect(keys, `search for "${query}" should include ${expectedKey}`).toContain(expectedKey);
    }
  });

  it("finds each new entry by Spanish search terms", () => {
    const cases: Array<{ query: string; expectedKey: (typeof NEW_KEYS)[number] }> = [
      { query: "radio", expectedKey: "radio_telecom" },
      { query: "troncal", expectedKey: "trunk_link" },
      { query: "acceso", expectedKey: "access_ci" },
      { query: "distribución", expectedKey: "distribution_ci" },
    ];

    for (const { query, expectedKey } of cases) {
      const results = findCategoryIcons(query);
      const keys = results.map((entry) => entry.key);
      expect(keys, `search for "${query}" should include ${expectedKey}`).toContain(expectedKey);
    }
  });

  it("infers default icon key from English category names", () => {
    expect(resolveCategoryIconKey({ categoryName: "Radio" })).toBe("radio_telecom");
    expect(resolveCategoryIconKey({ categoryName: "Radio Telecom" })).toBe("radio_telecom");
    expect(resolveCategoryIconKey({ categoryName: "Trunk Link" })).toBe("trunk_link");
    expect(resolveCategoryIconKey({ categoryName: "Access CI" })).toBe("access_ci");
    expect(resolveCategoryIconKey({ categoryName: "Distribution CI" })).toBe("distribution_ci");
  });

  it("infers default icon key from Spanish category names", () => {
    expect(resolveCategoryIconKey({ categoryName: "Radio" })).toBe("radio_telecom");
    expect(resolveCategoryIconKey({ categoryName: "Troncal de Red" })).toBe("trunk_link");
    expect(resolveCategoryIconKey({ categoryName: "Acceso" })).toBe("access_ci");
    expect(resolveCategoryIconKey({ categoryName: "Distribución" })).toBe("distribution_ci");
  });

  it("keeps unsupported names falling back to generic", () => {
    expect(resolveCategoryIconKey({ categoryName: "BizTalk Adapter" })).toBe("generic");
    expect(resolveCategoryIconKey({ categoryName: "Random Category" })).toBe("generic");
    expect(resolveCategoryIconKey({})).toBe("generic");
  });
});
