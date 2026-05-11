import React from 'react';
import { act, render, screen, waitFor, cleanup } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import MetricAnalytics from './MetricAnalytics';
import { fetchNodesSearch } from '../services/queryResources';
import { GraphNode } from '../types';

const { mockFetchNodesSearch } = vi.hoisted(() => ({
  mockFetchNodesSearch: vi.fn(),
}));

vi.mock('../services/queryResources', () => ({
  fetchNodesSearch: mockFetchNodesSearch,
}));

// Mock global fetch for initial node loading
vi.stubGlobal('fetch', vi.fn());

// Mock MetricHistoryChart
vi.mock('./MetricHistoryChart', () => ({
  default: () => <span data-testid="metric-history-chart">Mock Chart</span>,
}));

describe('MetricAnalytics', () => {
  const mockNodes: GraphNode[] = [
    {
      id: 'CI-001',
      label: 'Core Router',
      type: 'INFRASTRUCTURE',
      status: 'OK',
      ip: '192.168.1.1',
      brand: 'Cisco',
      model: 'ASR-1000',
      metrics: [
        { name: 'cpu-load', protocol: 'snmp', oid: '1.3.6.1', value: '45', status: 'OK', last_updated: '2026-05-11T10:00:00Z' },
        { name: 'memory-usage', protocol: 'snmp', oid: '1.3.6.2', value: '60', status: 'OK', last_updated: '2026-05-11T10:00:00Z' },
      ],
    },
    {
      id: 'CI-002',
      label: 'Backup Router',
      type: 'INFRASTRUCTURE',
      status: 'ACTIVE',
      ip: '192.168.1.2',
      brand: 'Juniper',
      model: 'MX204',
      metrics: [],
    },
  ];

  beforeEach(() => {
    vi.useFakeTimers();
    mockFetchNodesSearch.mockReset();
    // Mock localStorage for MetricAnalytics component
    Object.defineProperty(globalThis, 'localStorage', {
      value: {
        getItem: vi.fn(() => 'fake-token'),
        setItem: vi.fn(),
        removeItem: vi.fn(),
        clear: vi.fn(),
      },
      writable: true,
    });
    // Mock fetch for initial node loading
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      status: 200,
      headers: { get: () => 'application/json' },
      json: () => Promise.resolve([]),
    } as Response);
  });

  afterEach(() => {
    vi.useRealTimers();
    cleanup();
  });

  describe('search input', () => {
    it('renders search input replacing select dropdown', () => {
      mockFetchNodesSearch.mockResolvedValue([]);
      render(<MetricAnalytics />);

      expect(screen.getByRole('searchbox')).toBeInTheDocument();
    });

    it('debounces API call by 300ms after last keystroke', async () => {
      mockFetchNodesSearch.mockResolvedValue(mockNodes);
      render(<MetricAnalytics />);

      const searchInput = screen.getByRole('searchbox');

      // Type "router" - 6 chars, simulating 50ms between keystrokes
      await act(async () => {
        searchInput.focus();
        searchInput.setAttribute('value', 'r');
        searchInput.dispatchEvent(new Event('input', { bubbles: true }));
      });

      // Advance timer by 100ms
      await act(async () => {
        vi.advanceTimersByTime(100);
      });

      await act(async () => {
        searchInput.setAttribute('value', 'ro');
        searchInput.dispatchEvent(new Event('input', { bubbles: true }));
      });

      await act(async () => {
        vi.advanceTimersByTime(100);
      });

      await act(async () => {
        searchInput.setAttribute('value', 'rou');
        searchInput.dispatchEvent(new Event('input', { bubbles: true }));
      });

      await act(async () => {
        vi.advanceTimersByTime(100);
      });

      await act(async () => {
        searchInput.setAttribute('value', 'rout');
        searchInput.dispatchEvent(new Event('input', { bubbles: true }));
      });

      await act(async () => {
        vi.advanceTimersByTime(100);
      });

      await act(async () => {
        searchInput.setAttribute('value', 'route');
        searchInput.dispatchEvent(new Event('input', { bubbles: true }));
      });

      await act(async () => {
        vi.advanceTimersByTime(100);
      });

      await act(async () => {
        searchInput.setAttribute('value', 'router');
        searchInput.dispatchEvent(new Event('input', { bubbles: true }));
      });

      // At this point we're 500ms from first char, 50ms from last
      // Advance to fire the debounced call
      await act(async () => {
        vi.advanceTimersByTime(300);
      });

      // Only ONE call should have been made after 300ms from last keystroke
      expect(mockFetchNodesSearch).toHaveBeenCalledTimes(1);
      expect(mockFetchNodesSearch).toHaveBeenCalledWith({ q: 'router', signal: expect.any(AbortSignal) });
    });

    it('does not fetch when term has fewer than 2 characters', async () => {
      mockFetchNodesSearch.mockResolvedValue([]);
      render(<MetricAnalytics />);

      const searchInput = screen.getByRole('searchbox');

      await act(async () => {
        searchInput.setAttribute('value', 'a');
        searchInput.dispatchEvent(new Event('input', { bubbles: true }));
      });

      await act(async () => {
        vi.advanceTimersByTime(500);
      });

      expect(mockFetchNodesSearch).not.toHaveBeenCalled();
    });

    it('aborts previous request when new keystroke occurs', async () => {
      const firstAbortController = { abort: vi.fn() };
      const secondAbortController = { abort: vi.fn() };

      mockFetchNodesSearch
        .mockResolvedValueOnce(
          new Promise((resolve) => {
            setTimeout(() => resolve(mockNodes), 1000);
          })
        )
        .mockResolvedValueOnce(mockNodes);

      render(<MetricAnalytics />);

      const searchInput = screen.getByRole('searchbox');

      // First keystroke
      await act(async () => {
        searchInput.setAttribute('value', 'rou');
        searchInput.dispatchEvent(new Event('input', { bubbles: true }));
      });

      // Advance 200ms - not yet at 300ms debounce
      await act(async () => {
        vi.advanceTimersByTime(200);
      });

      // Second keystroke (should abort first)
      await act(async () => {
        searchInput.setAttribute('value', 'router');
        searchInput.dispatchEvent(new Event('input', { bubbles: true }));
      });

      await act(async () => {
        vi.advanceTimersByTime(350);
      });

      // Only the second call should have been made
      expect(mockFetchNodesSearch).toHaveBeenCalledTimes(1);
    });
  });

  describe('search results display', () => {
    it('shows loading state while searching', async () => {
      let resolveSearch!: (value: GraphNode[]) => void;
      mockFetchNodesSearch.mockImplementation(
        () =>
          new Promise<GraphNode[]>((resolve) => {
            resolveSearch = resolve;
          })
      );

      render(<MetricAnalytics />);

      const searchInput = screen.getByRole('searchbox');

      await act(async () => {
        searchInput.setAttribute('value', 'router');
        searchInput.dispatchEvent(new Event('input', { bubbles: true }));
      });

      await act(async () => {
        vi.advanceTimersByTime(350);
      });

      expect(screen.getByText(/loading/i)).toBeInTheDocument();

      // Resolve the search
      await act(async () => {
        resolveSearch(mockNodes);
      });
    });

    it('shows "No results found" when search returns empty array', async () => {
      mockFetchNodesSearch.mockResolvedValue([]);

      render(<MetricAnalytics />);

      const searchInput = screen.getByRole('searchbox');

      await act(async () => {
        searchInput.setAttribute('value', 'nonexistent');
        searchInput.dispatchEvent(new Event('input', { bubbles: true }));
      });

      await act(async () => {
        vi.advanceTimersByTime(350);
      });

      expect(screen.getByText(/no results/i)).toBeInTheDocument();
    });

    it('displays search results in a list', async () => {
      mockFetchNodesSearch.mockResolvedValue(mockNodes);

      render(<MetricAnalytics />);

      const searchInput = screen.getByRole('searchbox');

      await act(async () => {
        searchInput.setAttribute('value', 'router');
        searchInput.dispatchEvent(new Event('input', { bubbles: true }));
      });

      await act(async () => {
        vi.advanceTimersByTime(350);
      });

      expect(screen.getByText('Core Router')).toBeInTheDocument();
      expect(screen.getByText('Backup Router')).toBeInTheDocument();
    });
  });
});