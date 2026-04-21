
import { render, screen, fireEvent } from '@testing-library/react';
import { vi, describe, it, expect, beforeEach } from 'vitest';
import CIEditor from '../CIEditor';
import { api } from '../../services/api';

// Mock the api service
vi.mock('../../services/api', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn()
  }
}));

describe('CIEditor Thresholds', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (api.get as any).mockImplementation((url: string) => {
      if (url.includes('/categories')) return Promise.resolve([]);
      if (url.includes('/owners')) return Promise.resolve([]);
      if (url.includes('/hardware')) return Promise.resolve([]);
      return Promise.resolve([]);
    });
  });

  it('should render threshold fields for existing metrics when editing a node', async () => {
    const mockNode = {
      id: 'ci-01',
      label: 'Test Node',
      metrics: [
        { name: 'CPU', warning: 80, critical: 90, protocol: 'SNMP' }
      ]
    };

    render(<CIEditor node={mockNode as any} onSave={vi.fn()} onDelete={vi.fn()} onClose={vi.fn()} />);

    // Check if the threshold section for CPU appears
    expect(screen.getByText(/CPU/i)).toBeInTheDocument();
    expect(screen.getByText(/Metric Threshold Overrides/i)).toBeInTheDocument();
    
    const warningInput = screen.getByLabelText(/CPU Warning/i);
    expect(warningInput).toHaveValue(80);
    
    // Change value
    fireEvent.change(warningInput, { target: { value: '85' } });
    expect(warningInput).toHaveValue(85);
  });
});
