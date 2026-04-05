import { cleanup, render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import GraphCMDB from '../GraphCMDB';

const mockUseGraphTopologyQuery = vi.fn();

vi.mock('../../hooks/queries/useGraphTopologyQuery', () => ({
  useGraphTopologyQuery: () => mockUseGraphTopologyQuery(),
}));

describe('GraphCMDB query ownership', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    mockUseGraphTopologyQuery.mockReset();
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

    render(<GraphCMDB onNodeClick={vi.fn()} />);

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

    const view = render(<GraphCMDB onNodeClick={vi.fn()} />);

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
