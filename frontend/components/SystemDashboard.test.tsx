import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import SystemDashboard from './SystemDashboard';

const mockUseSystemStatusQuery = vi.fn();
const mockUseSystemStatusHistoryQuery = vi.fn();

vi.mock('../hooks/queries/useSystemStatusQuery', () => ({
  useSystemStatusQuery: () => mockUseSystemStatusQuery(),
}));

vi.mock('../hooks/queries/useSystemStatusHistoryQuery', () => ({
  useSystemStatusHistoryQuery: () => mockUseSystemStatusHistoryQuery(),
}));

const historyResponse = {
  generated_at: '2026-04-04T10:05:00.000Z',
  hours: 168,
  limit: 24,
  retention_days: 7,
  rows: [
    {
      recorded_at: '2026-04-04T10:05:00.000Z',
      cpu: 24,
      ram: 61,
      disk: 40,
      disk_io: {
        supported: true,
        read_bytes_per_sec: 1048576,
        write_bytes_per_sec: 524288,
        busy_percentage: 12.5,
      },
      neo4j: 'CONNECTED',
      postgres: 'CONNECTED',
      collector: {
        status: 'RUNNING',
        stats: {
          cis_monitored: 8,
          metrics_collected: 120,
          metrics_failed: 1,
          cycle_duration: 3,
          jobs_per_min: 44,
        },
      },
    },
  ],
};

describe('SystemDashboard', () => {
  beforeEach(() => {
    mockUseSystemStatusHistoryQuery.mockReturnValue({ data: historyResponse, isLoading: false, error: null });
  });

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
        disk_io: {
          supported: true,
          read_bytes_total: 10485760,
          write_bytes_total: 5242880,
          read_bytes_per_sec: 1048576,
          write_bytes_per_sec: 524288,
          busy_percentage: 12.5,
          sampled_at: '2026-04-04T10:00:03.000Z',
        },
        neo4j: 'CONNECTED',
        postgres: 'CONNECTED',
        startup_time: '2026-04-04T09:00:00.000Z',
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
    expect(screen.getByText('Disk I/O Throughput')).toBeInTheDocument();
    expect(screen.getByText('12.5%')).toBeInTheDocument();
    expect(screen.getAllByText('1.0 MB/s read / 512.0 KB/s write').length).toBeGreaterThan(0);
    expect(screen.getAllByText('CONNECTED').length).toBeGreaterThan(0);
    expect(screen.getAllByText('RUNNING').length).toBeGreaterThan(0);
    expect(screen.getByText('7-Day Operational History')).toBeInTheDocument();
    expect(screen.getByText(/Persisted system health snapshots/i)).toBeInTheDocument();
    expect(screen.getAllByText('1.0 MB/s read / 512.0 KB/s write').length).toBeGreaterThan(0);
    expect(screen.getByText(/120 metrics · 1 failed/i)).toBeInTheDocument();
    expect(screen.getByText('Active Monitored CIs')).toBeInTheDocument();
    expect(screen.getByText('8')).toBeInTheDocument();
    expect(screen.queryByText('173')).not.toBeInTheDocument();
  });

  it('shows persisted history empty and error states', () => {
    const statusData = {
      cpu: 24,
      ram: 61,
      disk: 40,
      disk_io: null,
      neo4j: 'CONNECTED',
      postgres: 'CONNECTED',
      collector: {
        status: 'RUNNING',
        last_run: null,
        stats: {
          cis_monitored: 8,
          metrics_collected: 120,
          metrics_failed: 1,
          cycle_duration: 3,
          jobs_per_min: 44,
        },
      },
    };

    mockUseSystemStatusQuery.mockReturnValue({ data: statusData, isLoading: false });
    mockUseSystemStatusHistoryQuery.mockReturnValueOnce({
      data: { ...historyResponse, rows: [] },
      isLoading: false,
      error: null,
    });
    const { rerender } = render(<SystemDashboard />);
    expect(screen.getByText(/No persisted operational snapshots yet/i)).toBeInTheDocument();

    mockUseSystemStatusHistoryQuery.mockReturnValueOnce({ data: undefined, isLoading: false, error: new Error('boom') });
    rerender(<SystemDashboard />);
    expect(screen.getByText(/Operational history unavailable/i)).toBeInTheDocument();
  });

  it('shows a graceful fallback when disk I/O is unsupported', () => {
    mockUseSystemStatusQuery.mockReturnValue({
      data: {
        cpu: 24,
        ram: 61,
        disk: 40,
        disk_io: {
          supported: false,
          read_bytes_total: null,
          write_bytes_total: null,
          read_bytes_per_sec: null,
          write_bytes_per_sec: null,
          busy_percentage: null,
          sampled_at: null,
        },
        neo4j: 'CONNECTED',
        postgres: 'CONNECTED',
        collector: {
          status: 'RUNNING',
          last_run: null,
          stats: {
            cis_monitored: 8,
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

    expect(screen.getByText('Disk I/O Throughput')).toBeInTheDocument();
    expect(screen.getByText('N/A')).toBeInTheDocument();
    expect(screen.getByText('Disk I/O unsupported on this host')).toBeInTheDocument();
  });
});
