
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { vi, describe, it, expect, beforeEach } from 'vitest';
import MassLinkEditor from '../MassLinkEditor';
import { api } from '../../services/api';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// Mock the api service
vi.mock('../../services/api', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn()
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

describe('MassLinkEditor', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    queryClient.clear();
    // Default responses
    (api.get as any).mockImplementation((url: string) => {
        if (url.includes('/categories')) return Promise.resolve([{ name: 'Server' }, { name: 'Network' }]);
        if (url.includes('/owners')) return Promise.resolve([{ name: 'NetOps' }]);
        return Promise.resolve([]);
    });
  });

  it('should render dual filters and relationship selector', async () => {
    render(<MassLinkEditor />, { wrapper });
    
    expect(screen.getByText(/Mass Relationship Editor/i)).toBeInTheDocument();
    expect(screen.getByText(/Source Set/i)).toBeInTheDocument();
    expect(screen.getByText(/Target Set/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Relationship Type/i)).toBeInTheDocument();
  });

  it('should call simulate API when clicking Simulate button', async () => {
    (api.post as any).mockResolvedValue({
        potential_links: 10,
        is_safe: true,
        message: 'Ready'
    });

    render(<MassLinkEditor />, { wrapper });

    const simulateBtn = screen.getByRole('button', { name: /Simulate/i });
    fireEvent.click(simulateBtn);

    await waitFor(() => {
        expect(api.post).toHaveBeenCalledWith('/links/mass/simulate', expect.anything());
    });
    
    expect(screen.getByText(/Potential Links/i)).toBeInTheDocument();
    expect(screen.getByText("10")).toBeInTheDocument();
  });
});
