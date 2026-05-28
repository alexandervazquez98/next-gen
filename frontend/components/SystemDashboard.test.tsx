import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import SystemDashboard from './SystemDashboard';

const mockUseSystemStatusQuery = vi.fn();

vi.mock('../hooks/queries/useSystemStatusQuery', () => ({
  useSystemStatusQuery: () => mockUseSystemStatusQuery(),
}));

describe('SystemDashboard', () => {
  it('shows the loading state while the shared status query is pending', () => {
    mockUseSystemStatusQuery.mockReturnValue({ data: null, isLoading: true });

    render(<SystemDashboard />);

    expect(screen.getByText('Initializing System Telemetry...')).toBeInTheDocument();
  });

  it('renders telemetry from the shared status query once available', () => {
    mockUseSystemStatusQuery.mockReturnValue({
      data: {
        cpu: 24,
        ram: 61,
        disk: 40,
        neo4j: 'CONNECTED',
        collector: {
          status: 'RUNNING',
          last_run: '2026-04-04T10:00:00.000Z',
          stats: {
            cis_monitored: 8,
            last_cycle_metrics_processed: 173,
            metrics_collected: 120,
            metrics_failed: 1,
            cycle_duration: 3,
            jobs_per_min: 44,
          },
        },
      },
      isLoading: false,
    });

    render(<SystemDashboard />);

    expect(screen.getByText('24%')).toBeInTheDocument();
    expect(screen.getByText('61%')).toBeInTheDocument();
    expect(screen.getByText('40%')).toBeInTheDocument();
    expect(screen.getByText('CONNECTED')).toBeInTheDocument();
    expect(screen.getByText('RUNNING')).toBeInTheDocument();
    expect(screen.getByText('Active Monitored CIs')).toBeInTheDocument();
    expect(screen.getByText('8')).toBeInTheDocument();
    expect(screen.queryByText('173')).not.toBeInTheDocument();
  });
});
