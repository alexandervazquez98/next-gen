// frontend/__tests__/graphContract.test.ts — REQ-1, REQ-2, REQ-7, REQ-9
//
// Vitest contract tests for the frontend LOD mirrors. The test:
//
// - Loads every fixture in ../../../fixtures/graph-contracts (the same
//   fixtures the backend tests validate against).
// - Asserts the fixture shape matches the TS DTOs in
//   ../types/graph (lock field names, null/omission rules).
// - Asserts the 5 sensitive fields NEVER appear in overview responses
//   and the public_ip field NEVER appears on detail nodes.
// - Asserts hidden and absent detail responses produce the same body
//   shape (REQ-7).
// - Asserts buildOverviewUrl / buildDetailUrl produce the expected
//   wire URLs.

import { describe, expect, it } from "vitest";

import {
  buildDetailUrl,
  buildOverviewUrl,
  isDetailResponse,
  isOverviewResponse,
} from "../services/graphContract";
import {
  DETAIL_NODE_FORBIDDEN_FIELDS,
  EMPTY_REASON_VALUES,
  OVERVIEW_FORBIDDEN_FIELDS,
  SAFE_GEO_PRECISION_VALUES,
  SEARCH_VOCABULARY_VALUES,
  SENSITIVE_SOURCE_VALUES,
  type DetailResponse,
  type OverviewResponse,
} from "../types/graph";

// ---------------------------------------------------------------------------
// Fixture loader — reads ../fixtures/graph-contracts/*.json relative to the
// repo root. Tests use Node's built-in fs.
// ---------------------------------------------------------------------------

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
// frontend/__tests__ -> repo root -> fixtures/graph-contracts
const FIXTURES_DIR = path.resolve(here, "..", "..", "fixtures", "graph-contracts");

function loadFixture(name: string): unknown {
  const p = path.join(FIXTURES_DIR, name);
  return JSON.parse(fs.readFileSync(p, "utf-8")) as unknown;
}

function listFixtures(): string[] {
  if (!fs.existsSync(FIXTURES_DIR)) return [];
  return fs.readdirSync(FIXTURES_DIR).filter((f) => f.endsWith(".json"));
}

// ---------------------------------------------------------------------------
// 1. Fixture shape parity — every fixture must round-trip through the TS
//    type guards so any future field drift trips the gate.
// ---------------------------------------------------------------------------

describe("graphContract fixtures", () => {
  it("has at least 12 fixtures (REQ-5/6 coverage)", () => {
    const files = listFixtures();
    expect(files.length).toBeGreaterThanOrEqual(12);
  });

  describe.each([
    "overview_authorized.json",
    "overview_empty_scope.json",
    "overview_single_cluster.json",
    "overview_hidden_present.json",
    "overview_low_cardinality.json",
    "overview_multi_page.json",
  ])("overview fixture: %s", (fname) => {
    const data = loadFixture(fname) as OverviewResponse;

    it("matches the OverviewResponse shape", () => {
      expect(isOverviewResponse(data)).toBe(true);
      expect(data.axis).toBe("location");
      expect(typeof data.generated_at).toBe("string");
      expect(typeof data.revision).toBe("string");
      expect(Array.isArray(data.clusters)).toBe(true);
      expect(Array.isArray(data.inter_cluster_links)).toBe(true);
    });

    it("never carries any forbidden sensitive field (REQ-9)", () => {
      const leaked = OVERVIEW_FORBIDDEN_FIELDS.filter(
        (k) => k in (data as unknown as Record<string, unknown>),
      );
      expect(leaked).toEqual([]);
      for (const c of data.clusters) {
        const clusterLeaks = OVERVIEW_FORBIDDEN_FIELDS.filter(
          (k) => k in (c as unknown as Record<string, unknown>),
        );
        expect(clusterLeaks).toEqual([]);
      }
    });

    it("safe_geo_precision is one of the allowed enum values", () => {
      expect(SAFE_GEO_PRECISION_VALUES).toContain(data.aggregate_policy.safe_geo_precision);
    });
  });

  describe.each([
    "detail_visible.json",
    "detail_no_visible_members.json",
    "detail_hidden.json",
    "detail_absent.json",
    "detail_boundary_stub.json",
  ])("detail fixture: %s", (fname) => {
    const data = loadFixture(fname) as DetailResponse;

    it("matches the DetailResponse shape", () => {
      expect(isDetailResponse(data)).toBe(true);
      expect(typeof data.generated_at).toBe("string");
      expect(typeof data.revision).toBe("string");
      expect(EMPTY_REASON_VALUES).toContain(data.empty_reason);
    });

    it("sensitive_source is one of the allowed enum values (REQ-9)", () => {
      expect(SENSITIVE_SOURCE_VALUES).toContain(data.projection_flags.sensitive_source);
    });

    it("show_sensitive_metadata defaults to false (REQ-9)", () => {
      expect(data.projection_flags.show_sensitive_metadata).toBe(false);
    });

    it("never exposes public_ip or metadata on a detail node (REQ-9)", () => {
      for (const n of data.nodes) {
        const leaked = DETAIL_NODE_FORBIDDEN_FIELDS.filter(
          (k) => k in (n as unknown as Record<string, unknown>),
        );
        expect(leaked).toEqual([]);
      }
    });
  });

  it("hidden and absent detail responses have the same body shape (REQ-7)", () => {
    const hidden = loadFixture("detail_hidden.json") as DetailResponse;
    const absent = loadFixture("detail_absent.json") as DetailResponse;

    expect(hidden.cluster).toBeNull();
    expect(absent.cluster).toBeNull();
    expect(hidden.nodes).toEqual([]);
    expect(absent.nodes).toEqual([]);
    expect(hidden.links).toEqual([]);
    expect(absent.links).toEqual([]);
    expect(hidden.boundary_stubs).toEqual([]);
    expect(absent.boundary_stubs).toEqual([]);
    expect(hidden.empty_reason).toBe("unavailable");
    expect(absent.empty_reason).toBe("unavailable");
    // Body shape: identical top-level keys.
    expect(Object.keys(hidden).sort()).toEqual(Object.keys(absent).sort());
  });

  it("low-cardinality overview marks clusters redacted with reason (REQ-9)", () => {
    const data = loadFixture("overview_low_cardinality.json") as OverviewResponse;
    const redacted = data.clusters.find((c) => c.aggregate_redacted);
    expect(redacted).toBeDefined();
    expect(redacted?.suppression_reason).toBe("low_cardinality");
  });

  it("multi-page overview exposes next_cursor + has_more (REQ-5)", () => {
    const data = loadFixture("overview_multi_page.json") as OverviewResponse;
    expect(typeof data.page.next_cursor).toBe("string");
    expect(data.page.has_more).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// 2. URL builders — sanity check the request shape.
// ---------------------------------------------------------------------------

describe("graphContract URL builders", () => {
  it("buildOverviewUrl returns the canonical path with no params when empty", () => {
    expect(buildOverviewUrl({})).toBe("/api/graph/overview");
  });

  it("buildOverviewUrl serializes filters into the query string", () => {
    const url = buildOverviewUrl({
      ci_type: ["router", "switch"],
      status: "ACTIVE",
      text: "dc-1",
      limit: 100,
    });
    expect(url).toContain("/api/graph/overview?");
    expect(url).toContain("ci_type=router%2Cswitch");
    expect(url).toContain("status=ACTIVE");
    expect(url).toContain("text=dc-1");
    expect(url).toContain("limit=100");
  });

  it("buildDetailUrl rejects malformed cluster_ids with a structured error", () => {
    for (const bad of [
      "",
      "foo bar",
      ":",
      "tenant:dc-1",
      "location:dc 1",
      "location:" + "a".repeat(129),
    ]) {
      expect(() => buildDetailUrl(bad)).toThrow();
      try {
        buildDetailUrl(bad);
      } catch (e) {
        const body = JSON.parse((e as Error).message);
        expect(body.error).toBe("invalid_cluster_id");
        expect("cluster_id" in body).toBe(true);
        // No metadata leak in the error body.
        expect("label" in body).toBe(false);
        expect("count" in body).toBe(false);
        expect("geo" in body).toBe(false);
      }
    }
  });

  it("buildDetailUrl accepts the unassigned sentinel and a normal cluster_id", () => {
    expect(buildDetailUrl("location:__unassigned__")).toBe(
      "/api/graph/detail/location%3A__unassigned__",
    );
    expect(buildDetailUrl("location:dc-1")).toBe("/api/graph/detail/location%3Adc-1");
  });

  it("buildDetailUrl passes through sensitive=include only when explicitly requested", () => {
    expect(buildDetailUrl("location:dc-1", { sensitive: "include" })).toContain(
      "sensitive=include",
    );
    expect(buildDetailUrl("location:dc-1", {})).not.toContain("sensitive=");
  });
});

// ---------------------------------------------------------------------------
// 3. Type guard sanity — protects against accidental shape drift.
// ---------------------------------------------------------------------------

describe("graphContract type guards", () => {
  it("isOverviewResponse rejects null, primitives, and missing required keys", () => {
    expect(isOverviewResponse(null)).toBe(false);
    expect(isOverviewResponse(undefined)).toBe(false);
    expect(isOverviewResponse({})).toBe(false);
    expect(isOverviewResponse({ axis: "tenant" })).toBe(false);
  });

  it("isDetailResponse accepts the hidden/absent body shape", () => {
    expect(
      isDetailResponse({
        cluster: null,
        filters: {},
        generated_at: "2026-01-01T00:00:00Z",
        revision: "x",
        nodes: [],
        links: [],
        boundary_stubs: [],
        projection_flags: { show_sensitive_metadata: false, sensitive_source: "never" },
        empty_reason: "unavailable",
        page: { next_cursor: null, has_more: false },
      }),
    ).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// 4. Enum constant sanity.
// ---------------------------------------------------------------------------

describe("graphContract enum constants", () => {
  it("exposes exactly the spec-pinned SafeGeoPrecision values", () => {
    expect([...SAFE_GEO_PRECISION_VALUES].sort()).toEqual(["city", "none", "region"]);
  });

  it("exposes exactly the spec-pinned SearchVocabulary values (REQ-8)", () => {
    expect([...SEARCH_VOCABULARY_VALUES].sort()).toEqual([
      "ambiguous",
      "multiple_visible_clusters",
      "no_visible_cluster",
      "single_visible_cluster",
    ]);
  });

  it("exposes exactly the spec-pinned SensitiveSource values (REQ-9)", () => {
    expect([...SENSITIVE_SOURCE_VALUES].sort()).toEqual([
      "never",
      "principal_scope",
      "principal_with_permission",
    ]);
  });

  it("exposes exactly the spec-pinned EmptyReason values (REQ-7)", () => {
    expect([...EMPTY_REASON_VALUES].sort()).toEqual([
      "hidden_absent",
      "no_visible_members",
      "none",
      "unavailable",
    ]);
  });
});
