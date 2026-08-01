import React from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createQueryWrapper, createTestQueryClient } from '../../test/queryTestUtils';
import { useActiveEventsQuery } from './useActiveEventsQuery';
import { useCategoriesQuery } from './useCategoriesQuery';
import { useEventDetailQuery } from './useEventDetailQuery';
import { useGraphTopologyQuery } from './useGraphTopologyQuery';
import { useLinksQuery } from './useLinksQuery';
import { useNodesQuery } from './useNodesQuery';
import { useSystemStatusQuery } from './useSystemStatusQuery';
import { queryKeys } from '../../services/queryKeys';

const { mockApiGet } = vi.hoisted(() => ({
  mockApiGet: vi.fn(),
}));

vi.mock('../../services/api', () => ({
  api: {
    get: mockApiGet,
  },
}));

function HookProbe({
  resource,
  eventId,
  detailEnabled,
}: {
  resource: 'status' | 'nodes' | 'links' | 'categories' | 'events' | 'topology' | 'detail';
  eventId?: string;
  detailEnabled?: boolean;
}) {
  const result = (() => {
    switch (resource) {
      case 'status':
        return useSystemStatusQuery();
      case 'nodes':
        return useNodesQuery();
      case 'links':
        return useLinksQuery();
      case 'categories':
        return useCategoriesQuery();
      case 'events':
        return useActiveEventsQuery();
      case 'topology':
        return useGraphTopologyQuery();
      case 'detail':
        return useEventDetailQuery(eventId, detailEnabled);
    }
  })();

  return <span data-testid="fetch-status">{result.fetchStatus}</span>;
}

function DeferredNodesConsumer({ label }: { label: string }) {
  const { data, isLoading, error } = useNodesQuery();

  return (
    <section data-testid={`${label}-consumer`}>
      <span>{`${label}-loading:${String(isLoading)}`}</span>
      <span>{`${label}-nodes:${(data ?? []).map((node) => node.label).join(',') || 'none'}`}</span>
      <span>{`${label}-error:${error instanceof Error ? error.message : 'none'}`}</span>
    </section>
  );
}

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;

  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });

  return { promise, resolve, reject };
}

describe('resource query hooks', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockApiGet.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it.each([
    ['status', '/system/status', 3000, { cpu: 10 }],
    ['nodes', '/nodes', 5000, [{ id: 'node-1' }]],
    ['categories', '/categories', 5000, [{ name: 'Network' }]],
    ['links', '/links', 10000, [{ id: 'link-1' }]],
    ['events', '/events?status=CONSOLE', 10000, [{ id: 'evt-1' }]],
    ['topology', '/graph/full', 30000, { nodes: [], links: [] }],
  ] as const)('polls %s with its shared cadence', async (resource, endpoint, intervalMs, payload) => {
    mockApiGet.mockResolvedValue(payload);

    render(<HookProbe resource={resource} />, { wrapper: createQueryWrapper() });

    await act(async () => {
      await Promise.resolve();
    });

    expect(mockApiGet).toHaveBeenCalledWith(endpoint, expect.objectContaining({ signal: expect.any(AbortSignal) }));

    await act(async () => {
      vi.advanceTimersByTime(intervalMs);
      await Promise.resolve();
    });

    expect(mockApiGet).toHaveBeenCalledTimes(2);
  });

  it('reuses one nodes cache entry across concurrent consumers while loading and after success', async () => {
    vi.useRealTimers();
    const client = createTestQueryClient();
    const deferred = createDeferred<Array<{ id: string; label: string; type: 'INFRASTRUCTURE'; status: 'OK'; metadata: Record<string, never> }>>();
    mockApiGet.mockReturnValue(deferred.promise);

    render(
      <>
        <DeferredNodesConsumer label="alpha" />
        <DeferredNodesConsumer label="beta" />
      </>,
      { wrapper: createQueryWrapper(client) }
    );

    expect(screen.getByText('alpha-loading:true')).toBeInTheDocument();
    expect(screen.getByText('beta-loading:true')).toBeInTheDocument();
    expect(mockApiGet).toHaveBeenCalledTimes(1);

    await act(async () => {
      deferred.resolve([{ id: 'node-1', label: 'Router-01', type: 'INFRASTRUCTURE', status: 'OK', metadata: {} }]);
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(screen.getByText('alpha-loading:false')).toBeInTheDocument();
      expect(screen.getByText('beta-loading:false')).toBeInTheDocument();
    });

    expect(screen.getByText('alpha-nodes:Router-01')).toBeInTheDocument();
    expect(screen.getByText('beta-nodes:Router-01')).toBeInTheDocument();
  });

  it('reuses one nodes cache entry across concurrent consumers when the shared request fails', async () => {
    vi.useRealTimers();
    const client = createTestQueryClient();
    const deferred = createDeferred<never>();
    mockApiGet.mockReturnValue(deferred.promise);

    render(
      <>
        <DeferredNodesConsumer label="alpha" />
        <DeferredNodesConsumer label="beta" />
      </>,
      { wrapper: createQueryWrapper(client) }
    );

    await act(async () => {
      deferred.reject(new Error('nodes-down'));
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(screen.getByText('alpha-error:nodes-down')).toBeInTheDocument();
      expect(screen.getByText('beta-error:nodes-down')).toBeInTheDocument();
    });

    expect(mockApiGet).toHaveBeenCalledTimes(1);
    expect(screen.getByText('alpha-loading:false')).toBeInTheDocument();
    expect(screen.getByText('beta-loading:false')).toBeInTheDocument();
  });

  it('fetches event detail by id without background polling', async () => {
    mockApiGet.mockResolvedValue({
      event: { id: 'evt-1', ci_id: 'ci-1', metric_id: 'cpu-load', status: 'OPEN', severity: 'CRITICAL', message: 'boom', created_at: '2026-04-05T11:00:00Z', last_seen: '2026-04-05T11:00:00Z', ack: false, ci_ref: { id: 'ci-1' } },
      business_context: { source: 'unavailable', sla_remaining_minutes: null },
      itsm_context: { assignment_state: 'unassigned', opened_by: 'system' },
    });

    render(<HookProbe resource="detail" eventId="evt-1" />, { wrapper: createQueryWrapper() });

    await act(async () => {
      await Promise.resolve();
    });

    expect(mockApiGet).toHaveBeenCalledWith('/events/evt-1', expect.objectContaining({ signal: expect.any(AbortSignal) }));

    await act(async () => {
      vi.advanceTimersByTime(60000);
      await Promise.resolve();
    });

    expect(mockApiGet).toHaveBeenCalledTimes(1);
  });

  it('does not fetch event detail until an id exists', async () => {
    render(<HookProbe resource="detail" />, { wrapper: createQueryWrapper() });

    await act(async () => {
      await Promise.resolve();
    });

    expect(mockApiGet).not.toHaveBeenCalled();
  });

  it('does not fetch event detail when explicitly disabled', async () => {
    render(<HookProbe resource="detail" eventId="evt-1" detailEnabled={false} />, { wrapper: createQueryWrapper() });

    await act(async () => {
      await Promise.resolve();
    });

    expect(mockApiGet).not.toHaveBeenCalled();
  });

  // ---------------------------------------------------------------------------
  // P2 REQ-006 / SCN-007: include_children Boolean discriminates the cache.
  // Two concurrent React Query clients (one per mode) must see their own
  // rows in the same QueryClient — no cross-contamination.
  // ---------------------------------------------------------------------------

  it('SCN-007: two simultaneous useActiveEventsQuery consumers keep separate cache slots', async () => {
    vi.useRealTimers();
    const client = createTestQueryClient();

    mockApiGet.mockImplementation(async (url: string) => {
      if (url.includes('include_children=true')) {
        return [
          { id: 'evt-root' },
          { id: 'evt-child' },
        ];
      }
      return [{ id: 'evt-root' }];
    });

    function ConcurrentEventsProbe() {
      const rootOnly = useActiveEventsQuery(false);
      const withChildren = useActiveEventsQuery(true);
      return (
        <section>
          <span data-testid="root-data">{JSON.stringify(rootOnly.data ?? [])}</span>
          <span data-testid="root-status">{String(rootOnly.isLoading)}</span>
          <span data-testid="with-data">{JSON.stringify(withChildren.data ?? [])}</span>
          <span data-testid="with-status">{String(withChildren.isLoading)}</span>
        </section>
      );
    }

    render(<ConcurrentEventsProbe />, { wrapper: createQueryWrapper(client) });

    await waitFor(() => {
      expect(screen.getByTestId('root-status')).toHaveTextContent('false');
      expect(screen.getByTestId('with-status')).toHaveTextContent('false');
    });

    // Each consumer sees its own data — no cross-contamination.
    expect(screen.getByTestId('root-data')).toHaveTextContent(
      JSON.stringify([{ id: 'evt-root' }]),
    );
    expect(screen.getByTestId('with-data')).toHaveTextContent(
      JSON.stringify([{ id: 'evt-root' }, { id: 'evt-child' }]),
    );

    // Both queries fired exactly once — each cache key resolved separately.
    expect(mockApiGet).toHaveBeenCalledTimes(2);
    const calledUrls = mockApiGet.mock.calls.map((args) => args[0]);
    expect(calledUrls).toEqual(
      expect.arrayContaining([
        '/events?status=CONSOLE',
        '/events?status=CONSOLE&include_children=true',
      ]),
    );

    // The QueryClient cache holds both keys with their independent payloads.
    const rootKey = queryKeys.activeEvents({ includeChildren: false });
    const withKey = queryKeys.activeEvents({ includeChildren: true });
    expect(rootKey).not.toEqual(withKey);
    expect(client.getQueryData(rootKey)).toEqual([{ id: 'evt-root' }]);
    expect(client.getQueryData(withKey)).toEqual([
      { id: 'evt-root' },
      { id: 'evt-child' },
    ]);
  });
});
