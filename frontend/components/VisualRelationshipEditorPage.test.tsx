import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { createQueryWrapper } from '../test/queryTestUtils';
import VisualRelationshipEditorPage from './VisualRelationshipEditorPage';

const { mockApiGet, mockHasPermission } = vi.hoisted(() => ({
  mockApiGet: vi.fn(),
  mockHasPermission: vi.fn(),
}));

vi.mock('../services/api', () => ({
  api: {
    get: mockApiGet,
  },
}));

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ hasPermission: mockHasPermission }),
}));

vi.mock('./VisualRelationshipEditor', () => ({
  default: ({ nodes, links }: { nodes: unknown[]; links: unknown[] }) => (
    <div>
      Visual editor workspace {nodes.length} nodes {links.length} links
    </div>
  ),
}));

const renderPage = () =>
  render(
    <MemoryRouter>
      <VisualRelationshipEditorPage />
    </MemoryRouter>,
    { wrapper: createQueryWrapper() },
  );

describe('VisualRelationshipEditorPage', () => {
  beforeEach(() => {
    mockApiGet.mockReset();
    mockHasPermission.mockReset();
    mockHasPermission.mockReturnValue(true);
  });

  it('loads nodes and links for the full-page visual editor', async () => {
    mockApiGet.mockImplementation((endpoint: string) => {
      if (endpoint === '/nodes') {
        return Promise.resolve([
          { id: 'ci-a', label: 'Router A', type: 'INFRASTRUCTURE', status: 'OK', metadata: {} },
        ]);
      }
      if (endpoint === '/links') {
        return Promise.resolve([
          { source: 'ci-a', target: 'ci-b', relationship: 'CONNECTS_TO' },
        ]);
      }
      return Promise.resolve([]);
    });

    renderPage();

    expect(screen.getByLabelText('Loading visual relationship editor')).toBeInTheDocument();
    expect(await screen.findByText('Visual editor workspace 1 nodes 1 links')).toBeInTheDocument();
    await waitFor(() => {
      expect(mockApiGet).toHaveBeenCalledWith('/nodes', expect.objectContaining({ signal: expect.any(AbortSignal) }));
      expect(mockApiGet).toHaveBeenCalledWith('/links', expect.objectContaining({ signal: expect.any(AbortSignal) }));
    });
  });

  it('blocks direct access without CI edit permissions', () => {
    mockHasPermission.mockReturnValue(false);

    renderPage();

    expect(screen.getByLabelText('Visual relationship editor access denied')).toBeInTheDocument();
    expect(screen.getByText('Access denied')).toBeInTheDocument();
    expect(mockApiGet).not.toHaveBeenCalled();
  });

  it('shows an error state when visual editor data cannot load', async () => {
    mockApiGet.mockRejectedValue(new Error('down'));

    renderPage();

    expect(await screen.findByText('Could not load visual editor data')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Back to admin' })).toHaveAttribute('href', '/admin');
  });
});
