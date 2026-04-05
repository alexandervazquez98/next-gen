import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import GlobalInventory from './GlobalInventory';
import type { GraphNode } from '../types';

type MockResponse = {
  ok: boolean;
  statusText: string;
  json: () => Promise<unknown>;
};

const buildResponse = (data: unknown, ok = true, statusText = 'OK'): MockResponse => ({
  ok,
  statusText,
  json: vi.fn().mockResolvedValue(data),
});

const createDeferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
};

const makeNode = (overrides: Partial<GraphNode> = {}): GraphNode => ({
  id: overrides.id ?? 'node-1',
  label: overrides.label ?? 'Router-01',
  type: overrides.type ?? 'INFRASTRUCTURE',
  status: overrides.status ?? 'ACTIVE',
  metadata: overrides.metadata ?? {},
  ip: overrides.ip ?? '10.0.0.1',
  category: overrides.category ?? 'Network',
  metrics: overrides.metrics ?? [
    {
      name: 'CPU Load',
      protocol: 'SNMP',
      oid: '1.3.6.1.4.1.9',
      value: '42',
      status: 'OK',
      last_updated: '2026-04-04T10:00:00.000Z',
    },
  ],
  ...overrides,
});

const queueFetchResponses = (...responses: MockResponse[]) => {
  const fetchMock = global.fetch as ReturnType<typeof vi.fn>;
  responses.forEach((response) => {
    fetchMock.mockResolvedValueOnce(response);
  });
};

describe('GlobalInventory', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
    localStorage.clear();
    localStorage.setItem('token', 'test-token');
    global.fetch = vi.fn();
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders the initial inventory shell before requests resolve', () => {
    const nodesRequest = createDeferred<MockResponse>();
    const categoriesRequest = createDeferred<MockResponse>();
    const fetchMock = global.fetch as ReturnType<typeof vi.fn>;

    fetchMock
      .mockReturnValueOnce(nodesRequest.promise)
      .mockReturnValueOnce(categoriesRequest.promise);

    render(<GlobalInventory />);

    expect(screen.getByText('Global Inventory')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('SEARCH CI...')).toBeInTheDocument();
    expect(screen.getByText('Select a CI to view telemetry')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('fetches nodes and categories with the auth header', async () => {
    queueFetchResponses(buildResponse([]), buildResponse([{ name: 'Network' }]));

    render(<GlobalInventory />);

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith('/api/nodes', {
        headers: { Authorization: 'Bearer test-token' },
      });
      expect(global.fetch).toHaveBeenCalledWith('/api/categories', {
        headers: { Authorization: 'Bearer test-token' },
      });
    });
  });

  it('loads and renders nodes correctly', async () => {
    const router = makeNode();
    const server = makeNode({
      id: 'node-2',
      label: 'Server-01',
      ip: '10.0.0.2',
      category: 'Compute',
      type: 'APPLICATION',
    });

    queueFetchResponses(
      buildResponse([router, server]),
      buildResponse([{ name: 'Network' }, { name: 'Compute' }]),
    );

    render(<GlobalInventory />);

    expect(await screen.findByText('Router-01')).toBeInTheDocument();
    expect(screen.getByText('Server-01')).toBeInTheDocument();
    expect(screen.getByText('10.0.0.1')).toBeInTheDocument();
    expect(screen.getByText('10.0.0.2')).toBeInTheDocument();
  });

  it('logs an error and keeps the inventory empty when /api/nodes fails', async () => {
    queueFetchResponses(
      buildResponse(null, false, 'Internal Server Error'),
      buildResponse([{ name: 'Network' }]),
    );

    render(<GlobalInventory />);

    await waitFor(() => {
      expect(console.error).toHaveBeenCalledWith(
        'Failed to fetch inventory:',
        expect.any(Error),
      );
    });

    expect(screen.queryByText('Router-01')).not.toBeInTheDocument();
    expect(screen.getByText('Select a CI to view telemetry')).toBeInTheDocument();
  });

  it('filters nodes by category', async () => {
    queueFetchResponses(
      buildResponse([
        makeNode({ id: 'node-1', label: 'Router-01', category: 'Network' }),
        makeNode({ id: 'node-2', label: 'DB-01', category: 'Database', ip: '10.0.0.20' }),
      ]),
      buildResponse([{ name: 'Network' }, { name: 'Database' }]),
    );

    render(<GlobalInventory />);

    await screen.findByText('Router-01');

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'Database' } });

    expect(screen.queryByText('Router-01')).not.toBeInTheDocument();
    expect(screen.getByText('DB-01')).toBeInTheDocument();
  });

  it('filters nodes by type when category does not exist', async () => {
    queueFetchResponses(
      buildResponse([
        makeNode({ id: 'node-1', label: 'Router-01', type: 'INFRASTRUCTURE', category: 'Network' }),
        makeNode({ id: 'node-2', label: 'ERP-App', type: 'APPLICATION', category: 'Business', ip: '10.0.0.30' }),
      ]),
      buildResponse([{ name: 'APPLICATION' }, { name: 'Network' }]),
    );

    render(<GlobalInventory />);

    await screen.findByText('ERP-App');

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'APPLICATION' } });

    expect(screen.queryByText('Router-01')).not.toBeInTheDocument();
    expect(screen.getByText('ERP-App')).toBeInTheDocument();
  });

  it('filters nodes by search text using the label', async () => {
    queueFetchResponses(
      buildResponse([
        makeNode({ id: 'node-1', label: 'Router-01' }),
        makeNode({ id: 'node-2', label: 'Database-01', category: 'Database', ip: '10.0.0.11' }),
      ]),
      buildResponse([{ name: 'Network' }, { name: 'Database' }]),
    );

    render(<GlobalInventory />);

    await screen.findByText('Router-01');

    fireEvent.change(screen.getByPlaceholderText('SEARCH CI...'), {
      target: { value: 'database' },
    });

    expect(screen.queryByText('Router-01')).not.toBeInTheDocument();
    expect(screen.getByText('Database-01')).toBeInTheDocument();
  });

  it('filters nodes by search text using the ip address', async () => {
    queueFetchResponses(
      buildResponse([
        makeNode({ id: 'node-1', label: 'Router-01', ip: '10.0.0.1' }),
        makeNode({ id: 'node-2', label: 'Switch-01', ip: '192.168.50.10' }),
      ]),
      buildResponse([{ name: 'Network' }]),
    );

    render(<GlobalInventory />);

    await screen.findByText('Switch-01');

    fireEvent.change(screen.getByPlaceholderText('SEARCH CI...'), {
      target: { value: '192.168.50' },
    });

    expect(screen.queryByText('Router-01')).not.toBeInTheDocument();
    expect(screen.getByText('Switch-01')).toBeInTheDocument();
  });

  it('polls every 5 seconds and refetches both endpoints', async () => {
    vi.useFakeTimers();
    queueFetchResponses(
      buildResponse([makeNode({ id: 'node-1', label: 'Router-01' })]),
      buildResponse([{ name: 'Network' }]),
      buildResponse([makeNode({ id: 'node-1', label: 'Router-01' })]),
      buildResponse([{ name: 'Network' }]),
    );

    render(<GlobalInventory />);

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByText('Router-01')).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledTimes(2);

    await act(async () => {
      vi.advanceTimersByTime(5000);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(global.fetch).toHaveBeenCalledTimes(4);
  });

  it('clicking a node opens its detail panel', async () => {
    const node = makeNode({
      label: 'Router-01',
      metrics: [
        {
          name: 'CPU Load',
          protocol: 'SNMP',
          oid: '1.3.6.1.4.1.9',
          value: '64',
          status: 'CRITICAL',
          last_updated: '2026-04-04T10:00:00.000Z',
        },
      ],
    });

    queueFetchResponses(buildResponse([node]), buildResponse([{ name: 'Network' }]));

    render(<GlobalInventory />);

    const card = await screen.findByText('Router-01');
    fireEvent.click(card);

    expect(screen.getByText('ID: node-1')).toBeInTheDocument();
    expect(screen.getByText('CPU Load')).toBeInTheDocument();
    expect(screen.getByText('64')).toBeInTheDocument();
  });

  it('keeps the selected item synchronized with polling updates', async () => {
    vi.useFakeTimers();
    const initialNode = makeNode({
      id: 'node-1',
      label: 'Router-01',
      metrics: [
        {
          name: 'CPU Load',
          protocol: 'SNMP',
          oid: '1.3.6.1.4.1.9',
          value: '42',
          status: 'OK',
          last_updated: '2026-04-04T10:00:00.000Z',
        },
      ],
    });
    const updatedNode = makeNode({
      id: 'node-1',
      label: 'Router-01',
      metrics: [
        {
          name: 'CPU Load',
          protocol: 'SNMP',
          oid: '1.3.6.1.4.1.9',
          value: '95',
          status: 'CRITICAL',
          last_updated: '2026-04-04T10:05:00.000Z',
        },
      ],
    });

    queueFetchResponses(
      buildResponse([initialNode]),
      buildResponse([{ name: 'Network' }]),
      buildResponse([updatedNode]),
      buildResponse([{ name: 'Network' }]),
    );

    render(<GlobalInventory />);

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    fireEvent.click(screen.getByText('Router-01'));
    expect(screen.getByText('42')).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(5000);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByText('95')).toBeInTheDocument();
  });

  it('clears the selected item when polling no longer returns that CI', async () => {
    vi.useFakeTimers();

    queueFetchResponses(
      buildResponse([makeNode({ id: 'node-1', label: 'Router-01' })]),
      buildResponse([{ name: 'Network' }]),
      buildResponse([makeNode({ id: 'node-2', label: 'Switch-01', ip: '10.0.0.2' })]),
      buildResponse([{ name: 'Network' }]),
    );

    render(<GlobalInventory />);

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    fireEvent.click(screen.getByText('Router-01'));
    expect(screen.getByText('ID: node-1')).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(5000);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.queryByText('ID: node-1')).not.toBeInTheDocument();
    expect(screen.getByText('Select a CI to view telemetry')).toBeInTheDocument();
    expect(screen.getByText('Switch-01')).toBeInTheDocument();
  });

  it('shows the empty metrics state for a selected node without metrics', async () => {
    queueFetchResponses(
      buildResponse([makeNode({ id: 'node-1', label: 'Router-01', metrics: [] })]),
      buildResponse([{ name: 'Network' }]),
    );

    render(<GlobalInventory />);

    fireEvent.click(await screen.findByText('Router-01'));

    expect(screen.getByText('No Metrics Configured')).toBeInTheDocument();
  });

  it('renders an empty inventory list when the API returns no nodes', async () => {
    queueFetchResponses(buildResponse([]), buildResponse([{ name: 'Network' }]));

    render(<GlobalInventory />);

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledTimes(2);
    });

    expect(screen.queryByText('Router-01')).not.toBeInTheDocument();
    expect(screen.getByText('Select a CI to view telemetry')).toBeInTheDocument();
  });

  it('shows no list items when filters produce no results', async () => {
    queueFetchResponses(
      buildResponse([
        makeNode({ id: 'node-1', label: 'Router-01', category: 'Network' }),
        makeNode({ id: 'node-2', label: 'Server-01', category: 'Compute', ip: '10.0.0.50' }),
      ]),
      buildResponse([{ name: 'Network' }, { name: 'Compute' }]),
    );

    render(<GlobalInventory />);

    await screen.findByText('Router-01');

    fireEvent.change(screen.getByPlaceholderText('SEARCH CI...'), {
      target: { value: 'does-not-exist' },
    });

    expect(screen.queryByText('Router-01')).not.toBeInTheDocument();
    expect(screen.queryByText('Server-01')).not.toBeInTheDocument();
    expect(screen.getByText('Select a CI to view telemetry')).toBeInTheDocument();
  });
});
