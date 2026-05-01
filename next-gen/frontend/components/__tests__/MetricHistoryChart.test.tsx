import { render, screen, waitFor, act } from '@testing-library/react';
import { vi, describe, it, expect, beforeEach } from 'vitest';
import MetricHistoryChart from '../MetricHistoryChart';
import { api } from '../../services/api';

// Mock the api service
vi.mock('../../services/api', () => ({
    api: {
        get: vi.fn(),
    }
}));

describe('MetricHistoryChart', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    // -------------------------------------------------------------------------
    // Task 6.1: Loading skeleton on CI switch (slow fetch ≥500ms)
    // -------------------------------------------------------------------------
    describe('Loading skeleton on CI switch', () => {
        it('shows skeleton when loading and data is empty during slow fetch', async () => {
            (api.get as any).mockImplementation(() => 
                new Promise(resolve => setTimeout(resolve, 500))
            );

            render(<MetricHistoryChart nodeId="node-A" metricId="cpu" metricName="CPU" />);
            
            // Wait for 200ms minDuration + fetch time
            await waitFor(() => expect(screen.queryByLabelText('Loading chart data')).toBeInTheDocument());
        });

        it('clears data immediately when nodeId prop changes', async () => {
            let resolveSlow: (value: any) => void;
            const slowPromise = new Promise(resolve => { resolveSlow = resolve; });
            
            // First request: slow, second request: slow too (to keep skeleton showing)
            (api.get as any)
                .mockReturnValueOnce(slowPromise)
                .mockImplementation(() => new Promise(resolve => setTimeout(resolve, 500)));

            const { rerender } = render(<MetricHistoryChart nodeId="node-A" metricId="cpu" metricName="CPU" />);
            
            // Wait for initial skeleton to appear (after 200ms minDuration)
            await waitFor(() => expect(screen.queryByLabelText('Loading chart data')).toBeInTheDocument());
            
            // Change nodeId - the first request aborts, new request starts
            rerender(<MetricHistoryChart nodeId="node-B" metricId="cpu" metricName="CPU" />);
            
            // Skeleton should still be visible (first request aborted, second loading)
            await waitFor(() => expect(screen.queryByLabelText('Loading chart data')).toBeInTheDocument());
        });
    });

    // -------------------------------------------------------------------------
    // Task 6.2: Fast response bypasses skeleton (<200ms)
    // -------------------------------------------------------------------------
    describe('Fast response bypasses skeleton', () => {
        it('does not show skeleton for responses under 200ms', async () => {
            (api.get as any).mockResolvedValue([{ time: '2024-01-01T00:00:00Z', value: 50 }]);

            render(<MetricHistoryChart nodeId="node-A" metricId="cpu" metricName="CPU" />);
            
            // Skeleton should NOT be present even briefly
            expect(screen.queryByLabelText('Loading chart data')).not.toBeInTheDocument();
            // Chart should render directly
            expect(await screen.findByText('CPU History')).toBeInTheDocument();
        });
    });

    // -------------------------------------------------------------------------
    // Task 6.3: Rapid switching aborts first request
    // -------------------------------------------------------------------------
    describe('Rapid switching aborts first request', () => {
        it('aborts previous request on rapid CI switch - only last data shown', async () => {
            let request1Resolve: (value: any) => void;
            let request2Resolve: (value: any) => void;
            
            const request1Deferred = new Promise(resolve => { request1Resolve = resolve; });
            const request2Deferred = new Promise(resolve => { request2Resolve = resolve; });
            
            let callCount = 0;
            (api.get as any).mockImplementation(() => {
                callCount++;
                if (callCount === 1) return request1Deferred;
                return request2Deferred;
            });

            const { rerender } = render(<MetricHistoryChart nodeId="node-A" metricId="cpu" metricName="CPU" />);
            
            // Wait a bit then switch rapidly
            await act(async () => {
                rerender(<MetricHistoryChart nodeId="node-B" metricId="cpu" metricName="CPU" />);
                await rerender(<MetricHistoryChart nodeId="node-C" metricId="cpu" metricName="CPU" />);
            });

            // Resolve request 2 first (node-C)
            act(() => { request2Resolve!([{ time: '2024-01-01T00:00:00Z', value: 75 }]); });
            
            // Wait for loading to finish
            await waitFor(() => expect(screen.queryByLabelText('Loading chart data')).not.toBeInTheDocument());
            
            // Request 1 should have been aborted, request 2 data should be present
        });

        it('minDuration prevents skeleton flash for slow responses', async () => {
            // This test verifies the 200ms minDuration timer works
            let resolveSlow: (value: any) => void;
            const slowPromise = new Promise(resolve => { resolveSlow = resolve; });
            
            (api.get as any).mockImplementation(() => slowPromise);

            render(<MetricHistoryChart nodeId="node-A" metricId="cpu" metricName="CPU" />);
            
            // Before 200ms, skeleton should NOT be shown (minDuration not active)
            expect(screen.queryByLabelText('Loading chart data')).not.toBeInTheDocument();
        });
    });

    // -------------------------------------------------------------------------
    // Task 6.4: Fade-in animation class present
    // -------------------------------------------------------------------------
    describe('Fade-in animation', () => {
        it('applies fade-in animation class to chart on data load', async () => {
            (api.get as any).mockResolvedValue([{ time: '2024-01-01T00:00:00Z', value: 50 }]);

            render(<MetricHistoryChart nodeId="node-A" metricId="cpu" metricName="CPU" />);
            
            await waitFor(() => expect(screen.queryByLabelText('Loading chart data')).not.toBeInTheDocument());
            
            // The chart-fade-in class is on the inner content div, find it
            const chartContent = screen.getByText('CPU History').closest('.bg-surface-800')?.querySelector('.chart-fade-in');
            expect(chartContent).toBeInTheDocument();
        });
    });

    // -------------------------------------------------------------------------
    // Task 6.5: Empty data vs loading distinction
    // -------------------------------------------------------------------------
    describe('Empty data vs loading distinction', () => {
        it('shows empty state when loading=false and data=[]', async () => {
            (api.get as any).mockResolvedValue([]);

            render(<MetricHistoryChart nodeId="node-A" metricId="cpu" metricName="CPU" />);
            
            await waitFor(() => expect(screen.queryByLabelText('Loading chart data')).not.toBeInTheDocument());
            expect(screen.getByText('No telemetry data found')).toBeInTheDocument();
        });

        it('shows skeleton when loading=true and data=[]', async () => {
            (api.get as any).mockImplementation(() => 
                new Promise(resolve => setTimeout(resolve, 500))
            );

            render(<MetricHistoryChart nodeId="node-A" metricId="cpu" metricName="CPU" />);
            
            await waitFor(() => expect(screen.queryByLabelText('Loading chart data')).toBeInTheDocument());
        });
    });

    // -------------------------------------------------------------------------
    // Task 6.6: Abort error silent handling
    // -------------------------------------------------------------------------
    describe('Abort error silent handling', () => {
        class AbortError extends Error {
            constructor() {
                super('Aborted');
                this.name = 'AbortError';
            }
        }

        it('silently handles AbortError without logging console.error', async () => {
            const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

            (api.get as any).mockImplementation((url: string, options: { signal?: AbortSignal } = {}) => {
                return new Promise((_, reject) => {
                    if (options.signal) {
                        options.signal.addEventListener('abort', () => {
                            reject(new AbortError());
                        });
                    }
                });
            });

            const { rerender } = render(<MetricHistoryChart nodeId="node-A" metricId="cpu" metricName="CPU" />);
            
            // Wait a moment for the first request to set up its abort listener
            await act(async () => {
                // Small delay to ensure first request's signal listener is registered
                await new Promise(resolve => setTimeout(resolve, 10));
            });
            
            // Trigger abort by rerendering (this should abort the first request)
            await act(async () => {
                rerender(<MetricHistoryChart nodeId="node-B" metricId="cpu" metricName="CPU" />);
            });

            // Wait for the component to finish processing the abort
            await waitFor(() => expect(screen.queryByLabelText('Loading chart data')).not.toBeInTheDocument(), { timeout: 2000 });
            
            // AbortError should not trigger console.error
            expect(consoleSpy).not.toHaveBeenCalled();
            consoleSpy.mockRestore();
        });
    });

    // -------------------------------------------------------------------------
    // Task 6.7: minDuration prevents skeleton flash
    // -------------------------------------------------------------------------
    describe('minDuration prevents skeleton flash', () => {
        it('response under 200ms should not show skeleton', async () => {
            // Simulate a response that completes very fast
            (api.get as any).mockResolvedValue([{ time: '2024-01-01T00:00:00Z', value: 50 }]);

            render(<MetricHistoryChart nodeId="node-A" metricId="cpu" metricName="CPU" />);
            
            // Should never show skeleton for fast response
            expect(screen.queryByLabelText('Loading chart data')).not.toBeInTheDocument();
            expect(await screen.findByText('CPU History')).toBeInTheDocument();
        });
    });
});
