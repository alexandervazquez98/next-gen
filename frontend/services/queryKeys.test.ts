import { describe, expect, it } from 'vitest';
import { queryKeys } from './queryKeys';

describe('queryKeys', () => {
  it('returns stable keys for shared polled resources', () => {
    expect(queryKeys.systemStatus()).toEqual(['system-status']);
    expect(queryKeys.nodes()).toEqual(['nodes']);
    expect(queryKeys.links()).toEqual(['links']);
    expect(queryKeys.categories()).toEqual(['categories']);
    expect(queryKeys.activeEvents()).toEqual(['events', 'CONSOLE']);
    expect(queryKeys.graphTopology()).toEqual(['graph-topology']);
  });

  it('scopes related events by ci id', () => {
    expect(queryKeys.relatedEvents('ci-1')).toEqual(['events', 'related', 'ci-1']);
    expect(queryKeys.relatedEvents('ci-2')).toEqual(['events', 'related', 'ci-2']);
  });
});
