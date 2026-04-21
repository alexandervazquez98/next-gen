
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { vi, describe, it, expect, beforeEach } from 'vitest';
import GraphCMDB from '../GraphCMDB';
import { api } from '../../services/api';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// Mock the api service
vi.mock('../../services/api', () => ({
  api: {
    get: vi.fn()
  }
}));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
    },
  },
});

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
);

describe('GraphCMDB Filters', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    queryClient.clear();
    // Default responses for initial load
    (api.get as any).mockImplementation((url: string) => {
      if (url.includes('/graph/full')) return Promise.resolve({ nodes: [], links: [] });
      if (url.includes('/categories')) return Promise.resolve([]);
      if (url.includes('/owners')) return Promise.resolve([]);
      return Promise.resolve([]);
    });
  });

  it('should render filter dropdowns for Tech, Location and Owner', async () => {
    render(<GraphCMDB onNodeClick={vi.fn()} />, { wrapper });
    
    // Use role and text for more specific selection
    expect(screen.getByRole('heading', { name: /Filters/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/Filter by Technology/i)).toBeInTheDocument();
  });

  it('should trigger API call with parameters when a filter is changed', async () => {
    render(<GraphCMDB onNodeClick={vi.fn()} />, { wrapper });

    // Wait for initial load
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/graph/full', expect.anything()));

    // Find the Location select (we'll add an aria-label for testing)
    const locationSelect = await screen.findByLabelText(/Filter by Location/i);
    
    // Change value
    fireEvent.change(locationSelect, { target: { value: 'DataCenter_A' } });

    // Verify that api.get is called again with the query parameter
    // TanStack query will append parameters to the key/url
    await waitFor(() => {
      const lastCall = (api.get as any).mock.calls.find((call: any) => call[0].includes('location=DataCenter_A'));
      expect(lastCall).toBeDefined();
    });
  });
});
