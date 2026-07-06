import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import GraphCMDB from '../GraphCMDB';

const mockUseGraphTopologyQuery = vi.fn();
const mockUseCategoriesQuery = vi.fn();
const mockUseOwnersQuery = vi.fn();

const topologySnapshot = {
  nodes: [
    { id: 'node-1', label: 'Router-01', status: 'OK', type: 'INFRASTRUCTURE', location_name: 'Core DC', metadata: {} },
    { id: 'node-2', label: 'Server-01', status: 'OK', type: 'INFRASTRUCTURE', location_name: 'Edge DC', metadata: {} },
  ],
  links: [],
};

vi.mock('../../hooks/queries/useGraphTopologyQuery', () => ({
  useGraphTopologyQuery: (...args: unknown[]) => mockUseGraphTopologyQuery(...args),
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

const getLastFilteredTopologyQuery = () => {
  const filteredCalls = mockUseGraphTopologyQuery.mock.calls
    .map(([params]) => params as Record<string, unknown>)
    .filter((params) => Object.prototype.hasOwnProperty.call(params, 'layer'));

  return filteredCalls[filteredCalls.length - 1];
};

describe('GraphCMDB query ownership', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    mockUseGraphTopologyQuery.mockReset();
    mockUseCategoriesQuery.mockReset();
    mockUseOwnersQuery.mockReset();
    mockUseCategoriesQuery.mockReturnValue({ data: [], isLoading: false });
    mockUseOwnersQuery.mockReturnValue({ data: [], isLoading: false });
    mockUseGraphTopologyQuery.mockReturnValue({ data: topologySnapshot, isLoading: false });

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

  it('keeps selected technology state when its filter section is collapsed and reopened', async () => {
    const user = userEvent.setup();
    mockUseCategoriesQuery.mockReturnValue({
      data: [{ name: 'Database' }, { name: 'Network' }],
      isLoading: false,
    });

    render(<GraphCMDB onNodeClick={vi.fn()} />, { wrapper: createWrapper() });

    await user.click(screen.getByRole('checkbox', { name: 'Database' }));
    expect(screen.getByLabelText('Selected graph filters')).toHaveTextContent('Tech: Database');

    await user.click(screen.getByRole('button', { name: /Technology/ }));
    expect(screen.queryByRole('checkbox', { name: 'Database' })).toBeNull();
    expect(screen.getByRole('button', { name: /Technology/ })).toHaveTextContent('Database');

    await user.click(screen.getByRole('button', { name: /Technology/ }));
    expect(screen.getByRole('checkbox', { name: 'Database' })).toBeChecked();
  });

  it('updates filter selections through per-section select all and clear controls', async () => {
    const user = userEvent.setup();
    mockUseCategoriesQuery.mockReturnValue({
      data: [{ name: 'Database' }, { name: 'Network' }],
      isLoading: false,
    });

    render(<GraphCMDB onNodeClick={vi.fn()} />, { wrapper: createWrapper() });

    const technologyFilters = within(screen.getByRole('region', { name: 'Technology filters' }));

    await user.click(technologyFilters.getByRole('button', { name: 'Select all' }));

    await waitFor(() => {
      expect(mockUseGraphTopologyQuery).toHaveBeenCalledWith(
        expect.objectContaining({ layer: ['Database', 'Network'] }),
      );
    });
    expect(screen.getByRole('checkbox', { name: 'Database' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Network' })).toBeChecked();

    await user.click(technologyFilters.getByRole('button', { name: 'Clear' }));

    await waitFor(() => {
      expect(getLastFilteredTopologyQuery()).toEqual(expect.objectContaining({ layer: [] }));
    });
    expect(screen.getByRole('checkbox', { name: 'Database' })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Network' })).not.toBeChecked();
  });

  it('filters the technology options with the section search field', async () => {
    const user = userEvent.setup();
    mockUseCategoriesQuery.mockReturnValue({
      data: [{ name: 'Database' }, { name: 'Network' }],
      isLoading: false,
    });

    render(<GraphCMDB onNodeClick={vi.fn()} />, { wrapper: createWrapper() });

    await user.type(screen.getByLabelText('Search technologies'), 'data');

    expect(screen.getByRole('checkbox', { name: 'Database' })).toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: 'Network' })).toBeNull();
  });

  it('filters and updates location selections from the location section controls', async () => {
    const user = userEvent.setup();

    render(<GraphCMDB onNodeClick={vi.fn()} />, { wrapper: createWrapper() });

    const locationFilters = within(screen.getByRole('region', { name: 'Location filters' }));

    await user.type(locationFilters.getByLabelText('Search locations'), 'core');

    expect(locationFilters.getByRole('checkbox', { name: 'Core DC' })).toBeInTheDocument();
    expect(locationFilters.queryByRole('checkbox', { name: 'Edge DC' })).toBeNull();

    await user.clear(locationFilters.getByLabelText('Search locations'));
    await user.click(locationFilters.getByRole('button', { name: 'Select all' }));

    await waitFor(() => {
      expect(mockUseGraphTopologyQuery).toHaveBeenCalledWith(
        expect.objectContaining({ location: ['Core DC', 'Edge DC'] }),
      );
    });

    await user.click(locationFilters.getByRole('button', { name: 'Clear' }));

    await waitFor(() => {
      expect(getLastFilteredTopologyQuery()).toEqual(expect.objectContaining({ location: [] }));
    });
  });

  it('keeps owner selections stable across search and collapse controls', async () => {
    const user = userEvent.setup();
    mockUseOwnersQuery.mockReturnValue({
      data: [{ name: 'Platform' }, { name: 'Security' }],
      isLoading: false,
    });

    render(<GraphCMDB onNodeClick={vi.fn()} />, { wrapper: createWrapper() });

    const ownerFilters = within(screen.getByRole('region', { name: 'Owner filters' }));

    await user.type(ownerFilters.getByLabelText('Search owners'), 'plat');
    expect(ownerFilters.getByRole('checkbox', { name: 'Platform' })).toBeInTheDocument();
    expect(ownerFilters.queryByRole('checkbox', { name: 'Security' })).toBeNull();

    await user.click(ownerFilters.getByRole('checkbox', { name: 'Platform' }));
    expect(screen.getByLabelText('Selected graph filters')).toHaveTextContent('Owner: Platform');
    await waitFor(() => {
      expect(getLastFilteredTopologyQuery()).toEqual(expect.objectContaining({ owner: ['Platform'] }));
    });

    await user.click(screen.getByRole('button', { name: /Owner/ }));
    expect(screen.queryByRole('checkbox', { name: 'Platform' })).toBeNull();
    expect(screen.getByRole('button', { name: /Owner/ })).toHaveTextContent('Platform');

    await user.click(screen.getByRole('button', { name: /Owner/ }));
    expect(screen.getByRole('checkbox', { name: 'Platform' })).toBeChecked();

    await user.clear(screen.getByLabelText('Search owners'));
    await user.click(within(screen.getByRole('region', { name: 'Owner filters' })).getByRole('button', { name: 'Clear' }));

    await waitFor(() => {
      expect(getLastFilteredTopologyQuery()).toEqual(expect.objectContaining({ owner: [] }));
    });
  });

  it('clears selected summaries and selections with Reset All', async () => {
    const user = userEvent.setup();
    mockUseCategoriesQuery.mockReturnValue({
      data: [{ name: 'Database' }, { name: 'Network' }],
      isLoading: false,
    });
    mockUseOwnersQuery.mockReturnValue({
      data: [{ name: 'Platform' }, { name: 'Security' }],
      isLoading: false,
    });

    render(<GraphCMDB onNodeClick={vi.fn()} />, { wrapper: createWrapper() });

    await user.click(screen.getByRole('checkbox', { name: 'Database' }));
    await user.click(screen.getByRole('checkbox', { name: 'Platform' }));
    expect(screen.getByLabelText('Selected graph filters')).toHaveTextContent('Tech: Database');
    expect(screen.getByLabelText('Selected graph filters')).toHaveTextContent('Owner: Platform');

    await user.click(screen.getByRole('button', { name: 'Reset All' }));

    await waitFor(() => {
      expect(screen.queryByLabelText('Selected graph filters')).toBeNull();
    });
    expect(screen.getByRole('checkbox', { name: 'Database' })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Platform' })).not.toBeChecked();
  });
});
