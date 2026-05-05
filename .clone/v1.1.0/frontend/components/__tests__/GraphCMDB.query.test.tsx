import { cleanup, render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import GraphCMDB from '../GraphCMDB';

const mockUseGraphTopologyQuery = vi.fn();
const mockUseCategoriesQuery = vi.fn();
const mockUseOwnersQuery = vi.fn();

vi.mock('../../hooks/queries/useGraphTopologyQuery', () => ({
  useGraphTopologyQuery: () => mockUseGraphTopologyQuery(),
}));

vi.mock('../../hooks/queries/useCategoriesQuery', () => ({
  useCategoriesQuery: () => mockUseCategoriesQuery(),
}));

vi.mock('../../hooks/queries/useOwnersQuery', () => ({
  useOwnersQuery: () => mockUseOwnersQuery(),
}));

const createWrapper = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
};

describe('GraphCMDB query ownership', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    mockUseGraphTopologyQuery.mockReset();
    mockUseCategoriesQuery.mockReset();
    mockUseOwnersQuery.mockReset();
    mockUseCategoriesQuery.mockReturnValue({ data: [], isLoading: false });
    mockUseOwnersQuery.mockReturnValue({ data: [], isLoading: false });

    // Mock SVGAnimatedLength for d3-zoom in jsdom
    // jsdom doesn't implement SVGAnimatedLength.baseVal
    const mockBaseVal = {
      value: 800,
      valueAsString: '800',
      valueAsNumber: 800,
      unitType: 1,
      convertToSpecifiedUnits: () => {},
      newValueSpecifiedUnits: () => {},
    };
    const mockAnimVal = { value: 800, valueAsString: '800' };
    Object.defineProperty(SVGElement.prototype, 'width', {
      writable: true,
      configurable: true,
      value: { baseVal: mockBaseVal, animVal: mockAnimVal },
    });
    Object.defineProperty(SVGElement.prototype, 'height', {
      writable: true,
      configurable: true,
      value: { baseVal: { ...mockBaseVal, value: 600, valueAsString: '600' }, animVal: { ...mockAnimVal, value: 600, valueAsString: '600' } },
    });
    SVGElement.prototype.getBoundingClientRect = vi.fn(() => ({
      left: 0, top: 0, width: 800, height: 600, right: 800, bottom: 600,
    }));
  });

  afterEach(() => {
    cleanup();
  });

  it('renders graph node labels from the shared topology query snapshot', async () => {
    mockUseGraphTopologyQuery.mockReturnValue({
      data: {
        nodes: [{ id: 'node-1', label: 'Router-01', status: 'OK', type: 'INFRASTRUCTURE', metadata: {} }],
        links: [],
      },
      isLoading: false,
    });

    render(<GraphCMDB onNodeClick={vi.fn()} />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText('Router-01')).toBeInTheDocument();
    });
  });

  it('refreshes rendered topology when the shared query snapshot changes', async () => {
    const snapshots = [
      {
        data: {
          nodes: [{ id: 'node-1', label: 'Router-01', status: 'OK', type: 'INFRASTRUCTURE', metadata: {} }],
          links: [],
        },
        isLoading: false,
      },
      {
        data: {
          nodes: [{ id: 'node-1', label: 'Router-02', status: 'OK', type: 'INFRASTRUCTURE', metadata: {} }],
          links: [],
        },
        isLoading: false,
      },
    ];

    let snapshotIndex = 0;
    mockUseGraphTopologyQuery.mockImplementation(() => snapshots[snapshotIndex]);

    const view = render(<GraphCMDB onNodeClick={vi.fn()} />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText('Router-01')).toBeInTheDocument();
    });

    snapshotIndex = 1;
    view.rerender(<GraphCMDB onNodeClick={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText('Router-02')).toBeInTheDocument();
    });

    expect(screen.queryByText('Router-01')).toBeNull();
  });

  it('keeps the component source free from local topology polling', async () => {
    const fs = await import('fs');
    const path = await import('path');
    const filePath = path.resolve(process.cwd(), 'components/GraphCMDB.tsx');
    const source = fs.readFileSync(filePath, 'utf-8');

    expect(source).toContain('useGraphTopologyQuery');
    expect(source).not.toContain('setInterval(');
    expect(source).not.toContain("api.get<TopologyResponse>('/graph/full')");
  });
});
