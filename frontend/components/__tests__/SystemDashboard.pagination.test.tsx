import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import React from 'react';

const mockStatus = {
    cpu: 45,
    ram: 60,
    disk: 30,
    neo4j: 'CONNECTED' as const,
    disk_io: { supported: true, busy_percentage: 10, read_bytes_per_sec: 1024, write_bytes_per_sec: 2048 },
    collector: {
        status: 'RUNNING' as const,
        stats: { cis_monitored: 5, metrics_collected: 100, metrics_failed: 2, jobs_per_min: 10, cycle_duration: 3 },
    },
};

function makeRows(count: number) {
    return Array.from({ length: count }, (_, i) => ({
        recorded_at: new Date(Date.now() - i * 900_000).toISOString(),
        cpu: 40 + i,
        ram: 55 + i,
        disk: 25 + i,
        neo4j: 'CONNECTED',
        postgres: 'CONNECTED',
        disk_io: { supported: true, busy_percentage: 5, read_bytes_per_sec: 512, write_bytes_per_sec: 1024 },
        collector: {
            status: 'RUNNING',
            stats: { metrics_collected: 100 + i, metrics_failed: i, jobs_per_min: 10, cycle_duration: 2 },
        },
    }));
}

// Mock recharts
vi.mock('recharts', () => ({
    CartesianGrid: () => null,
    Legend: () => null,
    Line: () => null,
    LineChart: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
    Tooltip: () => null,
    XAxis: () => null,
    YAxis: () => null,
}));

vi.mock('../Tooltip', () => ({ default: () => null }));

const historyRows12 = makeRows(12);
const mockHistoryReturn = {
    data: { rows: historyRows12, latest_recorded_at: historyRows12[0].recorded_at },
    isLoading: false,
    error: null,
};

vi.mock('../../hooks/queries/useSystemStatusQuery', () => ({
    useSystemStatusQuery: vi.fn(() => ({ data: mockStatus, isLoading: false })),
}));

vi.mock('../../hooks/queries/useSystemStatusHistoryQuery', () => ({
    useSystemStatusHistoryQuery: vi.fn(() => mockHistoryReturn),
}));

import SystemDashboard from '../SystemDashboard';

describe('SystemDashboard pagination', () => {
    beforeEach(() => {
        cleanup();
    });

    it('shows only 5 rows per page and displays correct page count', () => {
        render(<SystemDashboard />);
        expect(screen.getByText(/Page 1 of 3/i)).toBeTruthy();
        expect((screen.getByText('Previous') as HTMLButtonElement).disabled).toBe(true);
    });

    it('navigates to next page', () => {
        render(<SystemDashboard />);
        fireEvent.click(screen.getByText('Next'));
        expect(screen.getByText(/Page 2 of 3/i)).toBeTruthy();
    });

    it('disables Previous on first page and Next on last page', () => {
        render(<SystemDashboard />);
        expect((screen.getByText('Previous') as HTMLButtonElement).disabled).toBe(true);
        expect((screen.getByText('Next') as HTMLButtonElement).disabled).toBe(false);

        fireEvent.click(screen.getByText('Next'));
        fireEvent.click(screen.getByText('Next'));
        expect(screen.getByText(/Page 3 of 3/i)).toBeTruthy();
        expect((screen.getByText('Next') as HTMLButtonElement).disabled).toBe(true);
        expect((screen.getByText('Previous') as HTMLButtonElement).disabled).toBe(false);
    });
});
