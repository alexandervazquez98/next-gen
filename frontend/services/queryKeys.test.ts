import { describe, expect, it } from "vitest";
import { queryKeys } from "./queryKeys";

describe("queryKeys", () => {
  it("returns stable keys for shared polled resources", () => {
    expect(queryKeys.systemStatus()).toEqual(["system-status"]);
    expect(queryKeys.systemStatusHistory()).toEqual([
      "system-status",
      "history",
      { hours: 168, limit: 24 },
    ]);
    expect(queryKeys.systemStatusHistory({ hours: 168, limit: 24 })).toEqual([
      "system-status",
      "history",
      { hours: 168, limit: 24 },
    ]);
    expect(queryKeys.nodes()).toEqual(["nodes"]);
    expect(queryKeys.links()).toEqual(["links"]);
    expect(queryKeys.categories()).toEqual(["categories"]);
    expect(queryKeys.activeEvents()).toEqual(["events", "CONSOLE", { includeChildren: false }]);
    expect(queryKeys.activeEvents({ includeChildren: true })).toEqual([
      "events",
      "CONSOLE",
      { includeChildren: true },
    ]);
    expect(queryKeys.activeEvents({ includeChildren: false })).toEqual([
      "events",
      "CONSOLE",
      { includeChildren: false },
    ]);
    expect(queryKeys.affectedCIs("evt-1")).toEqual(["events", "affected", "evt-1"]);
    expect(queryKeys.graphTopologyRoot()).toEqual(["graph-topology"]);
    expect(queryKeys.graphTopology()).toEqual(["graph-topology", {}]);
    expect(queryKeys.graphTopology({ location: "Moron" })).toEqual([
      "graph-topology",
      { location: "Moron" },
    ]);
    expect(
      queryKeys.graphTopology({
        layer: ["Network", "Compute"],
        location: ["Moron", "Pilar"],
      }),
    ).toEqual(["graph-topology", { layer: ["Network", "Compute"], location: ["Moron", "Pilar"] }]);
  });

  it("scopes SNMP no-response drilldown by pagination", () => {
    expect(queryKeys.availabilitySnmpNoResponse()).toEqual([
      "events",
      "availability-report",
      "snmp-no-response",
      {},
    ]);
    expect(queryKeys.availabilitySnmpNoResponse({ limit: 25, offset: 0 })).toEqual([
      "events",
      "availability-report",
      "snmp-no-response",
      { limit: 25, offset: 0 },
    ]);
  });

  it("scopes related events by ci id", () => {
    expect(queryKeys.relatedEvents("ci-1")).toEqual(["events", "related", "ci-1"]);
    expect(queryKeys.relatedEvents("ci-2")).toEqual(["events", "related", "ci-2"]);
  });
});
