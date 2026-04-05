import React from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createQueryWrapper, createTestQueryClient } from '../../test/queryTestUtils';
import { useActiveEventsQuery } from './useActiveEventsQuery';
import { useCategoriesQuery } from './useCategoriesQuery';
import { useGraphTopologyQuery } from './useGraphTopologyQuery';
import { useLinksQuery } from './useLinksQuery';
import { useNodesQuery } from './useNodesQuery';
import { useSystemStatusQuery } from './useSystemStatusQuery';

const { mockApiGet } = vi.hoisted(() => ({
  mockApiGet: vi.fn(),
}));

vi.mock('../../services/api', () => ({
  api: {
    get: mockApiGet,
  },
}));

function HookProbe({ resource }: { resource: 'status' | 'nodes' | 'links' | 'categories' | 'events' | 'topology' }) {
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
    ['events', '/events?status=ACTIVE', 10000, [{ id: 'evt-1' }]],
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
});
