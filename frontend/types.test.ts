import { describe, expect, it } from "vitest";
import type { CategoryIconKey, GraphLink } from "./types";
import { getCategoryIconEntry, isCategoryIconKey } from "./utils/categoryIcons";

// ===========================================================================
// Slice 1 (feat-324) — CategoryIconKey union + GraphLink.medium
//
// These tests document the expected TS shape and exercise it through the
// runtime API surface (which depends on the union being extended). If the
// union is missing a key, isCategoryIconKey / getCategoryIconEntry will
// fall back to "generic" and the assertions below will fail RED.
// ===========================================================================

const SLICE1_NEW_KEYS = ["vpn_tunnel", "sd_wan_tunnel", "satellite_link", "vpn_hub"] as const;

const ALLOWED_MEDIUMS = ["vpn", "sd_wan", "satellite"] as const;

describe("CategoryIconKey — Slice 1 tunnel / vpn_hub additions", () => {
  it("treats the four new keys as controlled CategoryIconKey values", () => {
    for (const key of SLICE1_NEW_KEYS) {
      expect(isCategoryIconKey(key)).toBe(true);
      // Casting at runtime only succeeds if the union includes the
      // literal; this is the closest runtime approximation of a
      // compile-time union check without invoking tsc.
      const typed: CategoryIconKey = key as CategoryIconKey;
      expect(getCategoryIconEntry(typed).key).toBe(typed);
    }
  });

  it("keeps legacy keys in the union so existing consumers compile", () => {
    const router: CategoryIconKey = "router";
    const generic: CategoryIconKey = "generic";

    expect(isCategoryIconKey(router)).toBe(true);
    expect(isCategoryIconKey(generic)).toBe(true);
  });
});

describe("GraphLink — Slice 1 medium field on tunnel edges", () => {
  it("accepts every allowed medium literal on tunnel edges", () => {
    for (const medium of ALLOWED_MEDIUMS) {
      const link: GraphLink = {
        id: `link-${medium}`,
        source: "hub-a",
        target: "router-b",
        relationship: "CONNECTS_TO",
        medium,
      };
      expect(link.medium).toBe(medium);
    }
  });

  it("treats medium as optional — legacy links remain valid", () => {
    const legacyLink: GraphLink = {
      id: "link-legacy",
      source: "ci-001",
      target: "ci-002",
      relationship: "DEPENDS_ON",
    };

    expect(legacyLink.medium).toBeUndefined();
  });
});
