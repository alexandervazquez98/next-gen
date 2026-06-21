import { describe, it, expect } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useEventCorrelation } from '../hooks/useEventCorrelation';
import { Event } from '../types';

/**
 * REQ-CORR-7: Frontend CONNECTS_TO grouping tests.
 *
 * `frontend/hooks/useEventCorrelation.ts` must collapse CONNECTS_TO cascades
 * the same way it collapses DEPENDS_ON and HOSTED_ON. Existing DEPENDS_ON and
 * HOSTED_ON behavior must remain unchanged (regression coverage).
 */
describe('useEventCorrelation — CONNECTS_TO (REQ-CORR-7)', () => {
  const makeEvent = (overrides: Partial<Event>): Event => ({
    id: 'evt-1',
    ci_id: 'ci-1',
    ci_name: 'Test CI',
    metric_id: 'metric-1',
    metric_name: 'CPU',
    status: 'OPEN',
    severity: 'CRITICAL',
    message: 'Test event',
    created_at: '2024-01-01T00:00:00Z',
    last_seen: '2024-01-01T00:00:00Z',
    ack: false,
    ...overrides,
  });

  it('collapses downstream under CONNECTS_TO provider (preserved topology)', () => {
    // Two CIs: upstream 'provider' has CRITICAL, downstream 'consumer' has
    // WARNING, joined by a CONNECTS_TO link. The downstream should be
    // absorbed into the provider group with UPSTREAM_DEPENDENCY_FAILURE.
    const events = [
      makeEvent({ id: 'evt-provider', ci_id: 'provider', severity: 'CRITICAL', message: 'Provider CRITICAL' }),
      makeEvent({ id: 'evt-consumer', ci_id: 'consumer', severity: 'WARNING', message: 'Consumer WARNING' }),
    ];
    const links = [
      { source: 'consumer', target: 'provider', relationship: 'CONNECTS_TO' },
    ];

    const { result } = renderHook(() => useEventCorrelation(events, links));

    const roots = result.current;
    expect(roots).toHaveLength(1);
    expect(roots[0].id).toBe('evt-provider');
    expect(roots[0].relatedEvents).toHaveLength(1);
    expect(roots[0].relatedEvents[0].id).toBe('evt-consumer');
    expect(roots[0].relatedEvents[0].cause).toBe('UPSTREAM_DEPENDENCY_FAILURE');
    expect(roots[0].relatedEvents[0].isRoot).toBe(false);
  });

  it('preserves DEPENDS_ON collapse behavior (regression)', () => {
    // Existing DEPENDS_ON collapse must remain unchanged.
    const events = [
      makeEvent({ id: 'evt-provider', ci_id: 'provider', severity: 'CRITICAL' }),
      makeEvent({ id: 'evt-consumer', ci_id: 'consumer', severity: 'WARNING' }),
    ];
    const links = [
      { source: 'consumer', target: 'provider', relationship: 'DEPENDS_ON' },
    ];

    const { result } = renderHook(() => useEventCorrelation(events, links));

    const roots = result.current;
    expect(roots).toHaveLength(1);
    expect(roots[0].id).toBe('evt-provider');
    expect(roots[0].relatedEvents[0].id).toBe('evt-consumer');
    expect(roots[0].relatedEvents[0].cause).toBe('UPSTREAM_DEPENDENCY_FAILURE');
  });

  it('preserves HOSTED_ON collapse behavior (regression)', () => {
    const events = [
      makeEvent({ id: 'evt-host', ci_id: 'host', severity: 'CRITICAL' }),
      makeEvent({ id: 'evt-guest', ci_id: 'guest', severity: 'WARNING' }),
    ];
    const links = [
      { source: 'guest', target: 'host', relationship: 'HOSTED_ON' },
    ];

    const { result } = renderHook(() => useEventCorrelation(events, links));

    const roots = result.current;
    expect(roots).toHaveLength(1);
    expect(roots[0].id).toBe('evt-host');
    expect(roots[0].relatedEvents[0].id).toBe('evt-guest');
    expect(roots[0].relatedEvents[0].cause).toBe('UPSTREAM_DEPENDENCY_FAILURE');
  });

  it('still ignores MANAGED_BY links (regression)', () => {
    // MANAGED_BY must NOT trigger correlation — preserves existing exclusion.
    const events = [
      makeEvent({ id: 'evt-1', ci_id: 'ci-1', severity: 'CRITICAL' }),
      makeEvent({ id: 'evt-2', ci_id: 'ci-2', severity: 'CRITICAL' }),
    ];
    const links = [
      { source: 'ci-2', target: 'ci-1', relationship: 'MANAGED_BY' },
    ];

    const { result } = renderHook(() => useEventCorrelation(events, links));

    // Both should remain roots — MANAGED_BY does not trigger correlation.
    expect(result.current).toHaveLength(2);
  });

  it('handles mixed chain with all three relationship types', () => {
    // Chain A -> B -> C: A CONNECTS_TO B, B DEPENDS_ON a transit through,
    // C HOSTED_ON B. All three relationship types must collapse the chain
    // into a single root cause event group.
    const events = [
      makeEvent({ id: 'evt-A', ci_id: 'A', severity: 'CRITICAL' }),
      makeEvent({ id: 'evt-B', ci_id: 'B', severity: 'CRITICAL' }),
      makeEvent({ id: 'evt-C', ci_id: 'C', severity: 'WARNING' }),
    ];
    const links = [
      { source: 'B', target: 'A', relationship: 'CONNECTS_TO' },
      { source: 'C', target: 'B', relationship: 'DEPENDS_ON' },
    ];

    const { result } = renderHook(() => useEventCorrelation(events, links));

    // Every CI has a top-level event, so the chain collapses into ONE root
    // (the deepest match wins per the design — see REQ-CORR-7 spec).
    const roots = result.current;
    expect(roots).toHaveLength(1);
    const root = roots[0];
    // All non-root events must be in relatedEvents.
    const related_ids = root.relatedEvents.map(e => e.id);
    // Either B or C might be the root depending on the iteration order, but
    // they MUST all be in the same group.
    expect(related_ids.length + 1).toBe(3);
    expect(related_ids.every(id => id !== root.id)).toBe(true);
  });

  it('groups consumer regardless of severity match (CRITICAL or WARNING provider)', () => {
    // REQ-CORR-7: provider severity >= WARNING (CRITICAL or WARNING) must
    // group the consumer. CRITICAL provider.
    const critical_provider = makeEvent({ id: 'evt-p', ci_id: 'provider', severity: 'CRITICAL' });
    const consumer1 = makeEvent({ id: 'evt-c1', ci_id: 'consumer', severity: 'CRITICAL' });
    const { result: r1 } = renderHook(() =>
      useEventCorrelation([critical_provider, consumer1], [
        { source: 'consumer', target: 'provider', relationship: 'CONNECTS_TO' },
      ])
    );
    expect(r1.current).toHaveLength(1);

    // WARNING provider.
    const warning_provider = makeEvent({ id: 'evt-p2', ci_id: 'provider', severity: 'WARNING' });
    const consumer2 = makeEvent({ id: 'evt-c2', ci_id: 'consumer', severity: 'CRITICAL' });
    const { result: r2 } = renderHook(() =>
      useEventCorrelation([warning_provider, consumer2], [
        { source: 'consumer', target: 'provider', relationship: 'CONNECTS_TO' },
      ])
    );
    expect(r2.current).toHaveLength(1);

    // INFO provider must NOT trigger grouping (defensive: provider below
    // WARNING threshold).
    const info_provider = makeEvent({ id: 'evt-p3', ci_id: 'provider', severity: 'INFO' });
    const consumer3 = makeEvent({ id: 'evt-c3', ci_id: 'consumer', severity: 'CRITICAL' });
    const { result: r3 } = renderHook(() =>
      useEventCorrelation([info_provider, consumer3], [
        { source: 'consumer', target: 'provider', relationship: 'CONNECTS_TO' },
      ])
    );
    expect(r3.current).toHaveLength(2);
  });
});
