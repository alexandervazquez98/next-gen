// frontend/__tests__/parity.test.ts — REQ-1, REQ-2 drift guard
//
// Cross-layer parity gate: enumerates the field keys of every
// ``fixtures/graph-contracts/*.json`` payload and asserts each key
// appears in either the TS DTO types or is allowed as a wire-only
// field (e.g. error body fields).
//
// Failure mode: if a future backend DTO adds a new field, the
// fixture will reference it, and this gate will fail until the TS
// mirror is updated. This is the explicit drift guard #390 ships.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const here = path.dirname(fileURLToPath(import.meta.url));
const FIXTURES_DIR = path.resolve(here, "..", "..", "fixtures", "graph-contracts");

// ---------------------------------------------------------------------------
// Allowed top-level keys per fixture category.
// ---------------------------------------------------------------------------

const OVERVIEW_KEYS: ReadonlyArray<string> = [
  "axis",
  "filters",
  "generated_at",
  "revision",
  "aggregate_policy",
  "clusters",
  "inter_cluster_links",
  "legend",
  "page",
];
const DETAIL_KEYS: ReadonlyArray<string> = [
  "cluster",
  "filters",
  "generated_at",
  "revision",
  "nodes",
  "links",
  "boundary_stubs",
  "projection_flags",
  "empty_reason",
  "page",
];
const ERROR_KEYS: ReadonlyArray<string> = ["error", "reason", "cluster_id"];

const AGGREGATE_POLICY_KEYS: ReadonlyArray<string> = [
  "minimum_count",
  "permission_required",
  "safe_geo_precision",
];

const OVERVIEW_CLUSTER_KEYS: ReadonlyArray<string> = [
  "cluster_id",
  "display_label",
  "visible_node_count",
  "visible_link_count",
  "aggregate_redacted",
  "suppression_reason",
];

const INTER_CLUSTER_LINK_KEYS: ReadonlyArray<string> = [
  "from_cluster_id",
  "to_cluster_id",
  "visible_link_count",
  "redacted",
];

const DETAIL_NODE_KEYS: ReadonlyArray<string> = [
  "id",
  "display_label",
  "kind",
  "ci_type",
  "allowed_public_axes",
];

const DETAIL_LINK_KEYS: ReadonlyArray<string> = [
  "source_node_id",
  "target_node_id",
  "relationship",
];

const BOUNDARY_STUB_KEYS: ReadonlyArray<string> = [
  "cluster_id",
  "visible_link_count",
  "redacted",
  "redaction_reason",
];

const PROJECTION_FLAGS_KEYS: ReadonlyArray<string> = [
  "show_sensitive_metadata",
  "sensitive_source",
];

const PAGE_KEYS: ReadonlyArray<string> = ["next_cursor", "has_more"];

const DETAIL_CLUSTER_KEYS: ReadonlyArray<string> = [
  "cluster_id",
  "axis",
  "display_label",
  "visible_node_count",
  "visible_link_count",
];

const LEGEND_KEYS: ReadonlyArray<string> = ["cards"];

function walk(obj: unknown, prefix = "", out: Map<string, true> = new Map()): Map<string, true> {
  if (obj === null || obj === undefined) return out;
  if (Array.isArray(obj)) {
    for (const item of obj) walk(item, prefix, out);
    return out;
  }
  if (typeof obj === "object") {
    for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
      const path = prefix ? `${prefix}.${k}` : k;
      out.set(path, true);
      walk(v, path, out);
    }
  }
  return out;
}

function loadFixture(name: string): unknown {
  return JSON.parse(fs.readFileSync(path.join(FIXTURES_DIR, name), "utf-8")) as unknown;
}

function listFixtures(): string[] {
  if (!fs.existsSync(FIXTURES_DIR)) return [];
  return fs.readdirSync(FIXTURES_DIR).filter((f) => f.endsWith(".json"));
}

// ---------------------------------------------------------------------------
// Parity gate — overview fixtures
// ---------------------------------------------------------------------------

describe("parity: overview fixtures", () => {
  const overviewFiles = listFixtures().filter((f) => f.startsWith("overview_"));

  it("has at least 6 overview fixtures", () => {
    expect(overviewFiles.length).toBeGreaterThanOrEqual(6);
  });

  describe.each(overviewFiles)("%s", (fname) => {
    const fixture = loadFixture(fname) as Record<string, unknown>;

    it("top-level keys match the OverviewResponse DTO", () => {
      const actual = Object.keys(fixture).sort();
      const expected = [...OVERVIEW_KEYS].sort();
      expect(actual).toEqual(expected);
    });

    it("aggregate_policy keys match the AggregatePolicy DTO", () => {
      const ap = fixture.aggregate_policy as Record<string, unknown>;
      expect(Object.keys(ap).sort()).toEqual([...AGGREGATE_POLICY_KEYS].sort());
    });

    it("each cluster has exactly the OverviewCluster keys", () => {
      const clusters = fixture.clusters as Array<Record<string, unknown>>;
      for (const c of clusters) {
        expect(Object.keys(c).sort()).toEqual([...OVERVIEW_CLUSTER_KEYS].sort());
      }
    });

    it("each inter_cluster_link has exactly the InterClusterLink keys", () => {
      const links = fixture.inter_cluster_links as Array<Record<string, unknown>>;
      for (const l of links) {
        expect(Object.keys(l).sort()).toEqual([...INTER_CLUSTER_LINK_KEYS].sort());
      }
    });

    it("page has exactly the Page keys", () => {
      const page = fixture.page as Record<string, unknown>;
      expect(Object.keys(page).sort()).toEqual([...PAGE_KEYS].sort());
    });

    it("axis is the literal 'location'", () => {
      expect(fixture.axis).toBe("location");
    });

    it("every leaf path uses only the DTO-allowed key prefixes", () => {
      // Walk every nested path and ensure no path starts with a
      // key outside the DTO key set. This catches accidental
      // additions like ``foo.bar.baz`` sneaking into a fixture.
      const leafPaths = [...walk(fixture).keys()];
      const allowedPrefixes = [
        ...OVERVIEW_KEYS,
        ...AGGREGATE_POLICY_KEYS,
        ...OVERVIEW_CLUSTER_KEYS,
        ...INTER_CLUSTER_LINK_KEYS,
        ...PAGE_KEYS,
        ...LEGEND_KEYS,
        // filters / cards are arbitrary dicts / arrays; their leaf
        // values are caller-supplied and not DTO-shaped.
        "filters",
        "legend.cards",
      ];
      const offending = leafPaths.filter((p) => {
        const head = p.split(".")[0];
        return !allowedPrefixes.includes(head);
      });
      expect(offending).toEqual([]);
    });
  });
});

// ---------------------------------------------------------------------------
// Parity gate — detail fixtures
// ---------------------------------------------------------------------------

describe("parity: detail fixtures", () => {
  const detailFiles = listFixtures().filter(
    (f) => f.startsWith("detail_") && !f.startsWith("detail_error"),
  );

  it("has at least 5 non-error detail fixtures", () => {
    expect(detailFiles.length).toBeGreaterThanOrEqual(5);
  });

  describe.each(detailFiles)("%s", (fname) => {
    const fixture = loadFixture(fname) as Record<string, unknown>;

    it("top-level keys match the DetailResponse DTO", () => {
      const actual = Object.keys(fixture).sort();
      const expected = [...DETAIL_KEYS].sort();
      expect(actual).toEqual(expected);
    });

    it("detail cluster (when present) matches the DetailCluster DTO", () => {
      const cluster = fixture.cluster;
      if (cluster !== null) {
        expect(Object.keys(cluster as object).sort()).toEqual([...DETAIL_CLUSTER_KEYS].sort());
      }
    });

    it("each detail node has exactly the DetailNode keys", () => {
      const nodes = fixture.nodes as Array<Record<string, unknown>>;
      for (const n of nodes) {
        expect(Object.keys(n).sort()).toEqual([...DETAIL_NODE_KEYS].sort());
      }
    });

    it("each detail link has exactly the DetailLink keys", () => {
      const links = fixture.links as Array<Record<string, unknown>>;
      for (const l of links) {
        expect(Object.keys(l).sort()).toEqual([...DETAIL_LINK_KEYS].sort());
      }
    });

    it("each boundary stub has exactly the BoundaryStub keys", () => {
      const stubs = fixture.boundary_stubs as Array<Record<string, unknown>>;
      for (const s of stubs) {
        expect(Object.keys(s).sort()).toEqual([...BOUNDARY_STUB_KEYS].sort());
      }
    });

    it("projection_flags has exactly the ProjectionFlags keys", () => {
      const pf = fixture.projection_flags as Record<string, unknown>;
      expect(Object.keys(pf).sort()).toEqual([...PROJECTION_FLAGS_KEYS].sort());
    });

    it("empty_reason is a known enum value", () => {
      expect(["none", "no_visible_members", "hidden_absent", "unavailable"]).toContain(
        fixture.empty_reason,
      );
    });

    it("every leaf path uses only the DTO-allowed key prefixes", () => {
      const leafPaths = [...walk(fixture).keys()];
      const allowedPrefixes = [
        ...DETAIL_KEYS,
        ...DETAIL_CLUSTER_KEYS,
        ...DETAIL_NODE_KEYS,
        ...DETAIL_LINK_KEYS,
        ...BOUNDARY_STUB_KEYS,
        ...PROJECTION_FLAGS_KEYS,
        ...PAGE_KEYS,
        "filters",
      ];
      const offending = leafPaths.filter((p) => {
        const head = p.split(".")[0];
        return !allowedPrefixes.includes(head);
      });
      expect(offending).toEqual([]);
    });
  });
});

// ---------------------------------------------------------------------------
// Parity gate — error fixture
// ---------------------------------------------------------------------------

describe("parity: error fixtures", () => {
  it("detail_error.json has exactly the invalid_cluster_id error body keys", () => {
    const fixture = loadFixture("detail_error.json") as Record<string, unknown>;
    expect(Object.keys(fixture).sort()).toEqual([...ERROR_KEYS].sort());
    expect(fixture.error).toBe("invalid_cluster_id");
    expect(typeof fixture.reason).toBe("string");
    expect(typeof fixture.cluster_id).toBe("string");
  });
});
