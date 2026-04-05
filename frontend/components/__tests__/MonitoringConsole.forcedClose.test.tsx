/**
 * MonitoringConsole.forcedClose.test.tsx
 *
 * Behavioral tests — verify that handleStructuredClose sends { forced: true }
 * to the close endpoint when the user goes through the forced-close UI flow,
 * and { forced: false } for the standard structured-close flow.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// ---------------------------------------------------------------------------
// Mocks — must be declared before dynamic imports
// ---------------------------------------------------------------------------

const mockApiPost = vi.fn().mockResolvedValue({ message: 'ok' });
const mockApiGet = vi.fn().mockResolvedValue([]);

vi.mock('../../services/api', () => ({
    api: {
        get: mockApiGet,
        post: mockApiPost,
    },
}));

vi.mock('react-leaflet', () => ({
    MapContainer: ({ children }: any) => <div data-testid="map-container">{children}</div>,
    TileLayer: () => null,
    Polyline: () => null,
    CircleMarker: ({ children }: any) => <div>{children}</div>,
    Circle: () => null,
    Popup: ({ children }: any) => <div>{children}</div>,
    useMap: () => ({ fitBounds: vi.fn() }),
}));

vi.mock('leaflet', () => ({
    default: {
        icon: vi.fn(() => ({})),
        Marker: { prototype: { options: { icon: null } } },
        latLngBounds: vi.fn(() => ({ isValid: () => true })),
    },
    icon: vi.fn(() => ({})),
    Marker: { prototype: { options: { icon: null } } },
    latLngBounds: vi.fn(() => ({})),
}));

vi.mock('leaflet/dist/leaflet.css', () => ({}));

vi.mock('../DependencyMiniMap', () => ({
    default: () => <div data-testid="dependency-mini-map" />,
}));

vi.mock('../../hooks/useEventCorrelation', () => ({
    useEventCorrelation: (_events: any[], _links: any[]) => _events,
}));

// Auth context — user has both EVENT_CLOSE and EVENT_FORCED_CLOSE
vi.mock('../../context/AuthContext', () => ({
    useAuth: vi.fn(() => ({
        user: {
            username: 'admin',
            role: 'ADMIN',
            permissions: ['EVENT_CLOSE', 'EVENT_FORCED_CLOSE'],
            tier: 'T2',
            allowed_locations: [],
        },
        hasPermission: (_perm: string) => true,
        isAuthenticated: true,
        token: 'mock-token',
        login: vi.fn(),
        logout: vi.fn(),
    })),
}));

// ---------------------------------------------------------------------------
// Test data
// ---------------------------------------------------------------------------

const MOCK_EVENT = {
    id: 'evt-001',
    ci_id: 'ci-001',
    ci_node_id: 'ci-001',
    ci_name: 'Router-MX',
    ci_hostname: '192.168.1.1',
    ci_location_name: 'Madrid HQ',
    message: 'CPU High',
    severity: 'CRITICAL',
    status: 'OPEN',
    created_at: new Date().toISOString(),
    ack: false,
    ack_by: null,
    metric_name: 'CPU',
    metric_protocol: 'SNMP',
    comments: [],
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function renderConsoleWithEvent() {
    const { default: MonitoringConsole } = await import('../MonitoringConsole');

    // First GET call returns nodes=[], links=[], events=[MOCK_EVENT]
    mockApiGet.mockImplementation((url: string) => {
        if (url === '/nodes') return Promise.resolve([]);
        if (url === '/links') return Promise.resolve([]);
        if (url.includes('/events')) return Promise.resolve([MOCK_EVENT]);
        return Promise.resolve([]);
    });

    await act(async () => {
        const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
        render(
            <QueryClientProvider client={client}>
                <MonitoringConsole />
            </QueryClientProvider>
        );
    });

    return { MonitoringConsole };
}

async function openDetailModal() {
    // Wait for events to load and Details button to appear
    const detailsBtn = await screen.findByRole('button', { name: /details/i });
    await act(async () => {
        fireEvent.click(detailsBtn);
    });
}

async function openCloseFlow() {
    const closeEventBtn = await screen.findByRole('button', { name: /cerrar evento/i });
    await act(async () => {
        fireEvent.click(closeEventBtn);
    });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('MonitoringConsole — forced close API call', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockApiPost.mockResolvedValue({ message: 'ok' });
    });

    it('GIVEN forced close mode active WHEN handleStructuredClose is called THEN sends { forced: true } to close endpoint', async () => {
        await renderConsoleWithEvent();
        await openDetailModal();
        await openCloseFlow();

        // Enter forced close mode
        const forcedCloseBtn = await screen.findByRole('button', { name: /cierre forzado/i });
        await act(async () => {
            fireEvent.click(forcedCloseBtn);
        });

        // Fill in the forced reason (minimum non-empty)
        const reasonTextarea = await screen.findByPlaceholderText(/motivo del cierre forzado/i);
        await act(async () => {
            fireEvent.change(reasonTextarea, { target: { value: 'Mantenimiento de emergencia aprobado por CTO' } });
        });

        // Submit forced close
        const forceSubmitBtn = await screen.findByRole('button', { name: /forzar cierre/i });
        await act(async () => {
            fireEvent.click(forceSubmitBtn);
        });

        // Wait for the API call
        await waitFor(() => {
            const closeCalls = mockApiPost.mock.calls.filter(([url]) =>
                url === `/events/${MOCK_EVENT.id}/close`
            );
            expect(closeCalls.length).toBeGreaterThan(0);
            const lastCloseCall = closeCalls[closeCalls.length - 1];
            expect(lastCloseCall[1]).toEqual({ forced: true });
        });
    });

    it('GIVEN standard close mode WHEN handleStructuredClose is called THEN sends { forced: false } to close endpoint', async () => {
        await renderConsoleWithEvent();
        await openDetailModal();
        await openCloseFlow();

        // Standard close — select root cause
        // There may be multiple comboboxes (e.g. filter select), find the one with the root cause option
        const allComboboxes = await screen.findAllByRole('combobox');
        const rootCauseSelect = allComboboxes.find(el =>
            el.querySelector('option[value="Falla de hardware"]') !== null
        );
        if (!rootCauseSelect) throw new Error('Root cause select not found');
        await act(async () => {
            fireEvent.change(rootCauseSelect, { target: { value: 'Falla de hardware' } });
        });

        // Fill in close note (minimum 20 chars)
        const noteTextarea = await screen.findByPlaceholderText(/describe la resolución del incidente/i);
        await act(async () => {
            fireEvent.change(noteTextarea, { target: { value: 'Se reemplazó el módulo de CPU defectuoso' } });
        });

        // Submit standard close
        const confirmBtn = await screen.findByRole('button', { name: /confirmar cierre/i });
        await act(async () => {
            fireEvent.click(confirmBtn);
        });

        // Wait for the API call
        await waitFor(() => {
            const closeCalls = mockApiPost.mock.calls.filter(([url]) =>
                url === `/events/${MOCK_EVENT.id}/close`
            );
            expect(closeCalls.length).toBeGreaterThan(0);
            const lastCloseCall = closeCalls[closeCalls.length - 1];
            expect(lastCloseCall[1]).toEqual({ forced: false });
        });
    });

    it('GIVEN event table rows WHEN rendered THEN no close API call is possible without modal interaction', async () => {
        await renderConsoleWithEvent();

        // Verify no button in the table triggers a /close API call.
        // The only close path must go through the structured close modal.
        const allButtons = screen.getAllByRole('button');
        const closeRelatedButtons = allButtons.filter(btn => {
            const text = btn.textContent?.trim().toLowerCase() ?? '';
            return text === 'close' || text === 'cerrar' || text.includes('cerrar evento');
        });
        expect(closeRelatedButtons).toHaveLength(0);

        // Additionally verify no /close API call was made during render
        const closeCalls = mockApiPost.mock.calls.filter(([url]) =>
            typeof url === 'string' && url.includes('/close')
        );
        expect(closeCalls).toHaveLength(0);
    });
});
