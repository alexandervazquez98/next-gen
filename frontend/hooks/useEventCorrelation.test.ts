import { describe, it, expect } from "vitest";
import { renderHook } from "@testing-library/react";
import { useEventCorrelation } from "../hooks/useEventCorrelation";
import { Event } from "../types";

describe("useEventCorrelation", () => {
  const makeEvent = (overrides: Partial<Event>): Event => ({
    id: "evt-1",
    ci_id: "ci-1",
    ci_name: "Test CI",
    metric_id: "metric-1",
    metric_name: "CPU",
    status: "OPEN",
    severity: "CRITICAL",
    message: "Test event",
    created_at: "2024-01-01T00:00:00Z",
    last_seen: "2024-01-01T00:00:00Z",
    ack: false,
    ...overrides,
  });

  it("returns empty array when no events", () => {
    const { result } = renderHook(() => useEventCorrelation([], []));
    expect(result.current).toEqual([]);
  });

  it("returns single event as root when no correlations", () => {
    const event = makeEvent({ id: "evt-1" });
    const { result } = renderHook(() => useEventCorrelation([event], []));
    expect(result.current).toHaveLength(1);
    expect(result.current[0].isRoot).toBe(true);
    expect(result.current[0].relatedEvents).toHaveLength(0);
  });

  it("groups same-host events with dominant as root", () => {
    const events = [
      makeEvent({ id: "evt-1", ci_id: "ci-1", severity: "CRITICAL", message: "CPU High" }),
      makeEvent({
        id: "evt-2",
        ci_id: "ci-1",
        severity: "WARNING",
        message: "Memory High",
        created_at: "2024-01-01T00:01:00Z",
      }),
    ];
    const { result } = renderHook(() => useEventCorrelation(events, []));

    const roots = result.current;
    expect(roots).toHaveLength(1);
    expect(roots[0].id).toBe("evt-1"); // CRITICAL is dominant
    expect(roots[0].relatedEvents).toHaveLength(1);
    expect(roots[0].relatedEvents[0].id).toBe("evt-2");
    expect(roots[0].relatedEvents[0].isRoot).toBe(false);
  });

  it("prioritizes Unreachable/Down messages as dominant", () => {
    const events = [
      makeEvent({ id: "evt-1", ci_id: "ci-1", severity: "WARNING", message: "Host Unreachable" }),
      makeEvent({ id: "evt-2", ci_id: "ci-1", severity: "CRITICAL", message: "CPU High" }),
    ];
    const { result } = renderHook(() => useEventCorrelation(events, []));

    const roots = result.current;
    expect(roots).toHaveLength(1);
    expect(roots[0].id).toBe("evt-1"); // Unreachable wins over severity
  });

  it("correlates topology dependencies (DEPENDS_ON)", () => {
    const events = [
      makeEvent({
        id: "evt-provider",
        ci_id: "provider",
        severity: "CRITICAL",
        message: "Provider Down",
      }),
      makeEvent({
        id: "evt-consumer",
        ci_id: "consumer",
        severity: "WARNING",
        message: "Consumer Warning",
      }),
    ];
    const links = [{ source: "consumer", target: "provider", relationship: "DEPENDS_ON" }];

    const { result } = renderHook(() => useEventCorrelation(events, links));

    const roots = result.current;
    expect(roots).toHaveLength(1);
    expect(roots[0].id).toBe("evt-provider");
    expect(roots[0].relatedEvents).toHaveLength(1);
    expect(roots[0].relatedEvents[0].id).toBe("evt-consumer");
    expect(roots[0].relatedEvents[0].cause).toBe("UPSTREAM_DEPENDENCY_FAILURE");
  });

  it("ignores links without DEPENDS_ON or HOSTED_ON", () => {
    const events = [
      makeEvent({ id: "evt-1", ci_id: "ci-1", severity: "CRITICAL", message: "Event 1" }),
      makeEvent({ id: "evt-2", ci_id: "ci-2", severity: "CRITICAL", message: "Event 2" }),
    ];
    const links = [{ source: "ci-1", target: "ci-2", relationship: "MANAGED_BY" }];

    const { result } = renderHook(() => useEventCorrelation(events, links));

    // Both should remain roots since MANAGED_BY doesn't trigger correlation
    expect(result.current).toHaveLength(2);
  });

  // P2 REQ-007 / SCN-009: CONNECTS_TO is now part of the upstream grouping
  // vocabulary alongside DEPENDS_ON and HOSTED_ON.
  it("SCN-009: CONNECTS_TO link suppresses consumer ROOT under provider", () => {
    const events = [
      makeEvent({
        id: "evt-provider",
        ci_id: "provider",
        severity: "CRITICAL",
        message: "Provider outage",
      }),
      makeEvent({
        id: "evt-consumer",
        ci_id: "consumer",
        severity: "CRITICAL",
        message: "Consumer unreachable",
      }),
    ];
    const links = [{ source: "consumer", target: "provider", relationship: "CONNECTS_TO" }];

    const { result } = renderHook(() => useEventCorrelation(events, links));

    const roots = result.current;
    expect(roots).toHaveLength(1);
    expect(roots[0].id).toBe("evt-provider");
    expect(roots[0].relatedEvents).toHaveLength(1);
    expect(roots[0].relatedEvents[0].id).toBe("evt-consumer");
    expect(roots[0].relatedEvents[0].isRoot).toBe(false);
    expect(roots[0].relatedEvents[0].cause).toBe("UPSTREAM_DEPENDENCY_FAILURE");
  });

  it("sorts roots by severity (CRITICAL first) then by date", () => {
    const events = [
      makeEvent({
        id: "evt-1",
        ci_id: "ci-1",
        severity: "WARNING",
        message: "Warning",
        created_at: "2024-01-01T00:00:00Z",
      }),
      makeEvent({
        id: "evt-2",
        ci_id: "ci-2",
        severity: "CRITICAL",
        message: "Critical",
        created_at: "2024-01-01T00:01:00Z",
      }),
      makeEvent({
        id: "evt-3",
        ci_id: "ci-3",
        severity: "CRITICAL",
        message: "Critical earlier",
        created_at: "2024-01-01T00:00:00Z",
      }),
    ];

    const { result } = renderHook(() => useEventCorrelation(events, []));

    const roots = result.current;
    expect(roots).toHaveLength(3);
    expect(roots[0].id).toBe("evt-2"); // CRITICAL + newest (date desc)
    expect(roots[1].id).toBe("evt-3"); // CRITICAL + older
    expect(roots[2].id).toBe("evt-1"); // WARNING
  });
});
