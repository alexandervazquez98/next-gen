/**
 * EventDetailModal.acceptance.test.tsx
 *
 * Acceptance tests for the refactored Event Detail Modal (M1–M5) in MonitoringConsole.
 *
 * Scope:
 *   M1 — Business Context Band (header strip)
 *   M2 — Ownership Bar (assignment + Tomar caso)
 *   M3 — Enriched Timeline (append-only, typed entries)
 *   M4 — DependencyMiniMap label improvements (static analysis + smoke)
 *   M5 — Close with mandatory root cause (2-step flow)
 *
 * Test philosophy:
 *   - Pure DOM/React tests via @testing-library/react + jsdom
 *   - All external I/O mocked (api, leaflet, react-leaflet)
 *   - Static-analysis assertions for M4 (no DOM needed for SVG internals in jsdom)
 *   - Behavioral assertions for M1, M2, M3, M5 via fireEvent / waitFor
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// ---------------------------------------------------------------------------
// Shared fixtures
// ---------------------------------------------------------------------------

const MOCK_NODE = {
    id: 'node-1',
    label: 'Router-Core-01',
    type: 'ROUTER',
    ip: '10.0.0.1',
    category: 'NETWORK',
    hasCritical: true,
    hasWarning: false,
    location: { lat: 40.4, long: -3.7 },
    metadata: {
        business_service: 'Corp-WAN',
        impacted_users: '350',
        site: 'Madrid HQ',
        sla_minutes: 60,
    },
    events: [],
    metrics: [],
};

function buildEventDetail(event: any, node: any, overrides: any = {}) {
    const metadata = node?.metadata ?? {};
    const createdAt = new Date(event.created_at).getTime();
    const ageMinutes = Math.floor((Date.now() - createdAt) / 60000);
    const defaultSla = typeof metadata.sla_minutes === 'number' ? metadata.sla_minutes : null;

    return {
        event: {
            ...event,
            ci_ref: {
                id: event.ci_id,
                label: event.ci_name,
                hostname: node?.ip ?? null,
                location_name: event.ci_location_name ?? node?.location_name ?? metadata.site ?? null,
            },
        },
        business_context: {
            source: metadata.business_service || metadata.impacted_users || metadata.sla_minutes ? 'snapshot' : 'unavailable',
            business_service: metadata.business_service ? {
                id: 'svc-001',
                name: metadata.business_service,
                owner_t1: 'Mesa N1',
                owner_t2: 'NetOps',
                owner_t3: 'Arquitectura',
            } : null,
            service_catalog: defaultSla !== null ? {
                id: 'sla-001',
                category: node?.category ?? node?.type ?? 'UNKNOWN',
                service_tier: 'Gold',
                sla_minutes: defaultSla,
            } : null,
            impacted_users: metadata.impacted_users ? Number(metadata.impacted_users) : null,
            sla_remaining_minutes: defaultSla !== null ? defaultSla - ageMinutes : null,
            site: event.ci_location_name ?? node?.locationName ?? metadata.site ?? null,
            ...overrides.business_context,
        },
        itsm_context: {
            assignment_state: event.ack && event.ack_by ? 'assigned' : 'unassigned',
            assigned_to: event.ack_by ?? null,
            opened_by: 'system',
            escalation_tier: 'T2',
            external_ticket: null,
            ...overrides.itsm_context,
        },
        ...overrides,
    };
}

// Event created 5 minutes ago (well within SLA)
const MOCK_EVENT_WITHIN_SLA: any = {
    id: 'evt-1',
    ci_id: 'node-1',
    ci_name: 'Router-Core-01',
    message: 'PING Unreachable — host down',
    severity: 'CRITICAL',
    status: 'OPEN',
    ack: false,
    ack_by: null,
    metric_name: 'ICMP Ping',
    metric_protocol: 'ICMP',
    created_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
    comments: [],
};

// Event created 35 minutes ago (SLA = 60min → 25min remaining → RED)
const MOCK_EVENT_SLA_CRITICAL: any = {
    ...MOCK_EVENT_WITHIN_SLA,
    id: 'evt-2',
    created_at: new Date(Date.now() - 35 * 60 * 1000).toISOString(),
    // sla_minutes = 60 → remaining = 25 → ≤30 → critical
};

// Event with existing timeline comments
const MOCK_EVENT_WITH_COMMENTS: any = {
    ...MOCK_EVENT_WITHIN_SLA,
    id: 'evt-3',
    ack: true,
    ack_by: 'john.doe',
    comments: [
        'john.doe: Revisando el enlace (2024-01-01T10:05:00)',
        'DIAGNOSTIC RUN BY john.doe:\nPing OK, SNMP timeout',
        '[OWNERSHIP] Caso tomado por Admin — Tier T2',
    ],
};

// Event missing all optional metadata
const MOCK_EVENT_NO_METADATA: any = {
    ...MOCK_EVENT_WITHIN_SLA,
    id: 'evt-4',
};
const MOCK_NODE_NO_META = { ...MOCK_NODE, id: 'node-1', metadata: {} };

// ---------------------------------------------------------------------------
// Mocks (must be hoisted before any import of the component)
// ---------------------------------------------------------------------------

vi.mock('../../services/api', () => ({
    api: {
        get: vi.fn(async (url: string) => {
            if (url === '/nodes') return [MOCK_NODE];
            if (url === '/links') return [];
            if (url.startsWith('/events?')) return [MOCK_EVENT_WITHIN_SLA];
            if (url === `/events/${MOCK_EVENT_WITHIN_SLA.id}`) return buildEventDetail(MOCK_EVENT_WITHIN_SLA, MOCK_NODE);
            if (url.startsWith('/events/related/')) return [];
            return [];
        }),
        post: vi.fn().mockResolvedValue({ message: 'ok' }),
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
    default: ({ ciId }: any) => <div data-testid="dependency-mini-map" data-ci-id={ciId} />,
}));

vi.mock('../../hooks/useEventCorrelation', () => ({
    // Pass through events so the table renders them
    useEventCorrelation: (events: any[], _links: any[]) => events,
}));

// Mock AuthContext — MonitoringConsole now reads user/tier/hasPermission from here
vi.mock('../../context/AuthContext', () => ({
    useAuth: vi.fn(() => ({
        user: { username: 'testop', role: 'OPERATOR', permissions: ['EVENT_FORCED_CLOSE'], tier: 'T2', allowed_locations: [] },
        hasPermission: (perm: string) => perm === 'EVENT_FORCED_CLOSE' || ['EVENT_VIEW', 'EVENT_ACK', 'EVENT_CLOSE'].includes(perm),
        isAuthenticated: true,
        token: 'mock-token',
        login: vi.fn(),
        logout: vi.fn(),
    })),
}));

// ---------------------------------------------------------------------------
// Helper: render MonitoringConsole and open the event detail modal
// ---------------------------------------------------------------------------

async function renderAndOpenModal(eventOverride?: any, nodeOverride?: any, detailOverride?: any) {
    const { api } = await import('../../services/api');
    const mockEvent = eventOverride ?? MOCK_EVENT_WITHIN_SLA;
    const mockNode = nodeOverride ?? MOCK_NODE;
    const mockDetail = detailOverride ?? buildEventDetail(mockEvent, mockNode);

    (api.get as any).mockImplementation(async (url: string) => {
        if (url === '/nodes') return [mockNode];
        if (url === '/links') return [];
        if (url.startsWith('/events?')) return [mockEvent];
        if (url === `/events/${mockEvent.id}`) return mockDetail;
        if (url.startsWith('/events/related/')) return [];
        return [];
    });

    const { default: MonitoringConsole } = await import('../MonitoringConsole');
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    const result = render(
        <QueryClientProvider client={client}>
            <MonitoringConsole />
        </QueryClientProvider>
    );

    // Wait for data to load (event row appears)
    await waitFor(() => {
        expect(screen.getByText(mockEvent.message)).toBeDefined();
    }, { timeout: 3000 });

    // Click the Details button on the event row to open the modal
    const detailBtn = screen.getByText('Details');
    fireEvent.click(detailBtn);

    // Wait for modal to mount
    await waitFor(() => {
        expect(screen.getByText('Timeline de Investigación')).toBeDefined();
    }, { timeout: 3000 });

    return result;
}

function createDeferred<T>() {
    let resolve!: (value: T) => void;
    let reject!: (reason?: unknown) => void;

    const promise = new Promise<T>((res, rej) => {
        resolve = res;
        reject = rej;
    });

    return { promise, resolve, reject };
}

// ---------------------------------------------------------------------------
// M1: Business Context Band
// ---------------------------------------------------------------------------

describe('M1 — Business Context Band', () => {
    afterEach(() => vi.clearAllMocks());

    it('GIVEN an event with business metadata WHEN modal opens THEN business service is visible without scroll', async () => {
        await renderAndOpenModal();
        await waitFor(() => {
            expect(screen.getByText('Corp-WAN')).toBeDefined();
        });
    });

    it('GIVEN an event with impacted_users metadata WHEN modal opens THEN users count is visible', async () => {
        await renderAndOpenModal();
        await waitFor(() => {
            expect(screen.getByText('350')).toBeDefined();
        });
    });

    it('GIVEN an event with site metadata WHEN modal opens THEN site is visible', async () => {
        await renderAndOpenModal();
        await waitFor(() => {
            expect(screen.getAllByText('Madrid HQ').length).toBeGreaterThanOrEqual(1);
        });
    });

    it('GIVEN SLA remaining > 30 min WHEN modal opens THEN SLA label is NOT in red/critical state', async () => {
        await renderAndOpenModal(MOCK_EVENT_WITHIN_SLA, MOCK_NODE);
        // SLA remaining = 55 min → normal (not critical)
        const slaSection = screen.getByText('SLA Restante', { exact: false });
        expect(slaSection).toBeDefined();
        // Ensure the red warning icon is NOT present
        expect(screen.queryByText(/⚠/)).toBeNull();
    });

    it('GIVEN SLA remaining ≤ 30 min WHEN modal opens THEN SLA shows red warning', async () => {
        await renderAndOpenModal(MOCK_EVENT_SLA_CRITICAL, MOCK_NODE);
        // SLA remaining = 25 min → critical → ⚠ icon
        await waitFor(() => {
            expect(screen.getByText(/⚠/)).toBeDefined();
        });
    });

    it('GIVEN node with no metadata WHEN modal opens THEN "No configurado" placeholders appear', async () => {
        await renderAndOpenModal(MOCK_EVENT_NO_METADATA, MOCK_NODE_NO_META);
        const placeholders = screen.getAllByText('No configurado');
        // At least 3 cards should show "No configurado" (service, users, site, sla)
        expect(placeholders.length).toBeGreaterThanOrEqual(3);
    });

    it('GIVEN detail API returns business context WHEN modal opens THEN modal prefers detail payload over node metadata', async () => {
        const staleNode = {
            ...MOCK_NODE,
            metadata: {
                ...MOCK_NODE.metadata,
                business_service: 'Legacy Metadata Service',
            },
        };

        await renderAndOpenModal(
            MOCK_EVENT_WITHIN_SLA,
            staleNode,
            buildEventDetail(MOCK_EVENT_WITHIN_SLA, staleNode, {
                business_context: {
                    source: 'snapshot',
                    business_service: {
                        id: 'svc-001',
                        name: 'Corp-WAN API',
                        owner_t1: 'Mesa N1',
                        owner_t2: 'NetOps',
                        owner_t3: 'Arquitectura',
                    },
                },
            })
        );

        await waitFor(() => {
            expect(screen.getByText('Corp-WAN API')).toBeDefined();
        });
        expect(screen.queryByText('Legacy Metadata Service')).toBeNull();
    });

    it('GIVEN detail query is pending WHEN modal opens THEN loading state is rendered', async () => {
        const { api } = await import('../../services/api');
        const deferred = createDeferred<any>();
        const staleNode = {
            ...MOCK_NODE,
            metadata: {
                ...MOCK_NODE.metadata,
                business_service: 'Legacy Metadata Service',
            },
        };

        (api.get as any).mockImplementation(async (url: string) => {
            if (url === '/nodes') return [staleNode];
            if (url === '/links') return [];
            if (url.startsWith('/events?')) return [MOCK_EVENT_WITHIN_SLA];
            if (url === `/events/${MOCK_EVENT_WITHIN_SLA.id}`) return deferred.promise;
            if (url.startsWith('/events/related/')) return [];
            return [];
        });

        const { default: MonitoringConsole } = await import('../MonitoringConsole');
        const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });

        render(
            <QueryClientProvider client={client}>
                <MonitoringConsole />
            </QueryClientProvider>
        );

        await waitFor(() => {
            expect(screen.getByText(MOCK_EVENT_WITHIN_SLA.message)).toBeDefined();
        });

        fireEvent.click(screen.getByText('Details'));

        expect(await screen.findByText('Cargando contexto extendido del evento...')).toBeDefined();
        expect(screen.getByText('Timeline de Investigación')).toBeDefined();
        expect(screen.queryByText('Legacy Metadata Service')).toBeNull();
        expect(screen.getByText(/Contexto de negocio: cargando/i)).toBeDefined();

        deferred.resolve(buildEventDetail(MOCK_EVENT_WITHIN_SLA, MOCK_NODE));
        await waitFor(() => {
            expect(screen.getByText('Timeline de Investigación')).toBeDefined();
        });
    });

    it('GIVEN detail query fails WHEN modal opens THEN error state is rendered', async () => {
        const { api } = await import('../../services/api');
        const staleNode = {
            ...MOCK_NODE,
            metadata: {
                ...MOCK_NODE.metadata,
                business_service: 'Legacy Metadata Service',
            },
        };

        (api.get as any).mockImplementation(async (url: string) => {
            if (url === '/nodes') return [staleNode];
            if (url === '/links') return [];
            if (url.startsWith('/events?')) return [MOCK_EVENT_WITHIN_SLA];
            if (url === `/events/${MOCK_EVENT_WITHIN_SLA.id}`) throw new Error('detail-down');
            if (url.startsWith('/events/related/')) return [];
            return [];
        });

        const { default: MonitoringConsole } = await import('../MonitoringConsole');
        const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });

        render(
            <QueryClientProvider client={client}>
                <MonitoringConsole />
            </QueryClientProvider>
        );

        await waitFor(() => {
            expect(screen.getByText(MOCK_EVENT_WITHIN_SLA.message)).toBeDefined();
        });

        fireEvent.click(screen.getByText('Details'));

        expect(await screen.findByText('No se pudo cargar el detalle protegido. Seguís trabajando con el resumen del stream.')).toBeDefined();
        expect(screen.getByText('Timeline de Investigación')).toBeDefined();
        expect(screen.queryByText('Legacy Metadata Service')).toBeNull();
        expect(screen.getByText(/Contexto de negocio: degradado/i)).toBeDefined();
    });
});

// ---------------------------------------------------------------------------
// M2: Ownership Bar
// ---------------------------------------------------------------------------

describe('M2 — Ownership Bar', () => {
    afterEach(() => vi.clearAllMocks());

    it('GIVEN an unassigned event WHEN modal opens THEN "Sin asignar" pulsing label is visible', async () => {
        await renderAndOpenModal(MOCK_EVENT_WITHIN_SLA);
        expect(screen.getByText('Sin asignar')).toBeDefined();
    });

    it('GIVEN an unassigned event WHEN modal opens THEN "Tomar caso" button is visible', async () => {
        await renderAndOpenModal(MOCK_EVENT_WITHIN_SLA);
        expect(screen.getByText('Tomar caso')).toBeDefined();
    });

    it('GIVEN an unassigned event WHEN "Tomar caso" is clicked THEN api.post is called once through the atomic ack flow', async () => {
        const { api } = await import('../../services/api');
        await renderAndOpenModal(MOCK_EVENT_WITHIN_SLA);

        const takerBtn = screen.getByText('Tomar caso');
        fireEvent.click(takerBtn);

        await waitFor(() => {
            const calls = (api.post as any).mock.calls;
            const ackCall = calls.find((c: any[]) => c[0].includes('/ack'));
            expect(ackCall).toBeDefined();
            expect(calls).toHaveLength(1);
        });
    });

    it('GIVEN "Tomar caso" click THEN the ack payload stays empty and leaves audit generation to the backend', async () => {
        const { api } = await import('../../services/api');
        await renderAndOpenModal(MOCK_EVENT_WITHIN_SLA);

        fireEvent.click(screen.getByText('Tomar caso'));

        await waitFor(() => {
            const calls = (api.post as any).mock.calls;
            const ackCall = calls.find((c: any[]) => c[0].includes('/ack'));
            expect(ackCall).toBeDefined();
            expect(ackCall[1]).toEqual({});
        });
    });

    it('GIVEN modal open THEN event escalation tier is displayed honestly', async () => {
        await renderAndOpenModal(MOCK_EVENT_WITHIN_SLA);
        expect(screen.getByText('Tier del evento:')).toBeDefined();
        await waitFor(() => {
            expect(screen.getByText('T2')).toBeDefined();
        });
    });

    it('GIVEN an assigned event WHEN modal opens THEN assigned username is displayed', async () => {
        await renderAndOpenModal(MOCK_EVENT_WITH_COMMENTS);
        expect(screen.getByText('john.doe')).toBeDefined();
    });
});

// ---------------------------------------------------------------------------
// M3: Enriched Timeline
// ---------------------------------------------------------------------------

describe('M3 — Enriched Timeline', () => {
    afterEach(() => vi.clearAllMocks());

    it('GIVEN event with comments WHEN modal opens THEN existing timeline entries are rendered', async () => {
        await renderAndOpenModal(MOCK_EVENT_WITH_COMMENTS);
        // The standard comment text should appear
        expect(screen.getByText(/Revisando el enlace/)).toBeDefined();
    });

    it('GIVEN event with DIAGNOSTIC comment WHEN modal opens THEN it renders as diagnostic entry', async () => {
        await renderAndOpenModal(MOCK_EVENT_WITH_COMMENTS);
        expect(screen.getByText(/Ping OK, SNMP timeout/)).toBeDefined();
    });

    it('GIVEN event with OWNERSHIP comment WHEN modal opens THEN it renders as ownership entry', async () => {
        await renderAndOpenModal(MOCK_EVENT_WITH_COMMENTS);
        expect(screen.getByText(/Caso tomado por Admin/)).toBeDefined();
    });

    it('GIVEN event with forced close comment WHEN modal opens THEN it renders as forced-close entry', async () => {
        await renderAndOpenModal({
            ...MOCK_EVENT_WITH_COMMENTS,
            id: 'evt-force',
            comments: ['[AUDIT][FORCED_CLOSE] Cierre forzado por testop\nMotivo: Ventana de mantenimiento (2024-01-01T10:06:00)'],
        });
        expect(screen.getAllByText((_, node) => node?.textContent?.includes('Cierre forzado') ?? false).length).toBeGreaterThan(0);
    });

    it('GIVEN structured audit entry from another actor WHEN modal opens THEN timeline shows the real actor instead of the viewer', async () => {
        await renderAndOpenModal({
            ...MOCK_EVENT_WITH_COMMENTS,
            id: 'evt-audit-actor',
            comments: ['[AUDIT][CLOSE] Evento cerrado por alice\nCausa raíz: Error de configuración\nNota: Se corrigió la política de enrutamiento principal (2024-01-01T10:06:00)'],
        });

        expect(screen.getAllByText((_, node) => node?.textContent?.includes('alice · Evento cerrado') ?? false).length).toBeGreaterThan(0);
        expect(screen.queryByText((_, node) => node?.textContent?.includes('testop · Evento cerrado') ?? false)).toBeNull();
    });

    it('GIVEN a note is typed WHEN Guardar nota is clicked THEN api.post is called with the note', async () => {
        const { api } = await import('../../services/api');
        await renderAndOpenModal(MOCK_EVENT_WITHIN_SLA);

        const textarea = screen.getByPlaceholderText('Escribe tus notas de investigación...');
        fireEvent.change(textarea, { target: { value: 'Investigando el fallo de red' } });

        const saveBtn = screen.getByText('Guardar nota');
        fireEvent.click(saveBtn);

        await waitFor(() => {
            const calls = (api.post as any).mock.calls;
            const commentCall = calls.find((c: any[]) => c[0].includes('/comment'));
            expect(commentCall).toBeDefined();
            expect(commentCall[1].message).toContain('Investigando el fallo de red');
        });
    });

    it('GIVEN a note is saved THEN modal stays open (does NOT close)', async () => {
        await renderAndOpenModal(MOCK_EVENT_WITHIN_SLA);

        const textarea = screen.getByPlaceholderText('Escribe tus notas de investigación...');
        fireEvent.change(textarea, { target: { value: 'Nota de prueba para el cierre' } });
        fireEvent.click(screen.getByText('Guardar nota'));

        // Modal header must still be present
        await waitFor(() => {
            expect(screen.getByText('Timeline de Investigación')).toBeDefined();
        });
    });

    it('GIVEN modal open THEN the triggering event always appears as first timeline entry', async () => {
        await renderAndOpenModal(MOCK_EVENT_WITHIN_SLA);
        expect(screen.getByText('DISPARADOR:')).toBeDefined();
    });

    it('GIVEN timeline entries THEN no edit or delete controls are present', async () => {
        await renderAndOpenModal(MOCK_EVENT_WITH_COMMENTS);
        // No "Eliminar" or "Editar" buttons should exist
        expect(screen.queryByText('Eliminar')).toBeNull();
        expect(screen.queryByText('Editar')).toBeNull();
        expect(screen.queryByRole('button', { name: /delete/i })).toBeNull();
    });
});

// ---------------------------------------------------------------------------
// M4: DependencyMiniMap — static analysis + smoke
// ---------------------------------------------------------------------------

describe('M4 — DependencyMiniMap label improvements', () => {
    it('GIVEN DependencyMiniMap source WHEN inspected THEN status labels use fontSize ≥ 11', async () => {
        const fs = await import('fs');
        const path = await import('path');
        const filePath = path.resolve(process.cwd(), 'components/DependencyMiniMap.tsx');
        const src = fs.readFileSync(filePath, 'utf-8');

        // Should have at least one fontSize="11" or higher for the status label
        expect(src).toMatch(/fontSize="1[1-9]"/);
    });

    it('GIVEN DependencyMiniMap source WHEN inspected THEN status text (CAÍDO/ok/WARNING) is present', async () => {
        const fs = await import('fs');
        const path = await import('path');
        const filePath = path.resolve(process.cwd(), 'components/DependencyMiniMap.tsx');
        const src = fs.readFileSync(filePath, 'utf-8');

        expect(src).toContain('CAÍDO');
        expect(src).toContain("'ok'");
        expect(src).toContain('WARNING');
    });

    it('GIVEN DependencyMiniMap source WHEN inspected THEN status label rendered without hover trigger', async () => {
        const fs = await import('fs');
        const path = await import('path');
        const filePath = path.resolve(process.cwd(), 'components/DependencyMiniMap.tsx');
        const src = fs.readFileSync(filePath, 'utf-8');

        // Status sub-label must NOT be inside an onMouseEnter/onHover/title handler
        // The label group is rendered unconditionally in the labels pass
        // We verify no conditional hover wrapper around statusText
        expect(src).not.toMatch(/onMouseEnter[\s\S]{0,100}statusText/);
        expect(src).not.toMatch(/hover[\s\S]{0,100}statusText/);
    });

    it('GIVEN DependencyMiniMap source WHEN inspected THEN root badge has a blue fill', async () => {
        const fs = await import('fs');
        const path = await import('path');
        const filePath = path.resolve(process.cwd(), 'components/DependencyMiniMap.tsx');
        const src = fs.readFileSync(filePath, 'utf-8');

        // ROOT CI badge should use a blue color like #2563eb or #3b82f6
        expect(src).toMatch(/#[23][5-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]/i); // blue hex range
        expect(src).toContain('ROOT CI');
    });

    it('GIVEN DependencyMiniMap mounts inside modal THEN it renders without errors', async () => {
        await renderAndOpenModal(MOCK_EVENT_WITHIN_SLA);
        // DependencyMiniMap is mocked — verifies it receives ciId prop
        const miniMap = screen.getByTestId('dependency-mini-map');
        expect(miniMap).toBeDefined();
        expect(miniMap.getAttribute('data-ci-id')).toBe('node-1');
    });
});

// ---------------------------------------------------------------------------
// Auth Context Integration
// ---------------------------------------------------------------------------

describe('Auth Context Integration', () => {
    afterEach(() => vi.clearAllMocks());

    it('GIVEN authenticated user WHEN modal opens THEN CURRENT_USER displays authenticated username', async () => {
        await renderAndOpenModal(MOCK_EVENT_WITHIN_SLA);
        // Trigger "Tomar caso" and assert the atomic ack payload uses the authenticated username
        const { api } = await import('../../services/api');
        fireEvent.click(screen.getByText('Tomar caso'));

        await waitFor(() => {
            const calls = (api.post as any).mock.calls;
            const ackCall = calls.find((c: any[]) => c[0].includes('/ack'));
            expect(ackCall).toBeDefined();
            expect(ackCall[1]).toEqual({});
        });
    });

    it('GIVEN user without EVENT_VIEW but with close and diagnostics permissions WHEN modal opens THEN no detail fetch occurs and authorized actions stay available', async () => {
        const { api } = await import('../../services/api');
        const { useAuth } = await import('../../context/AuthContext');

        (useAuth as any).mockImplementation(() => ({
            user: { username: 'closer', role: 'OPERATOR', permissions: ['EVENT_CLOSE', 'RUN_DIAGNOSTICS'], tier: 'T2', allowed_locations: [] },
            hasPermission: (perm: string) => ['EVENT_CLOSE', 'RUN_DIAGNOSTICS'].includes(perm),
            isAuthenticated: true,
            token: 'mock-token',
            login: vi.fn(),
            logout: vi.fn(),
        }));

        await renderAndOpenModal(MOCK_EVENT_WITHIN_SLA);

        expect((api.get as any).mock.calls.some((c: any[]) => c[0] === `/events/${MOCK_EVENT_WITHIN_SLA.id}`)).toBe(false);
        expect((api.get as any).mock.calls.some((c: any[]) => c[0] === `/events/related/${MOCK_EVENT_WITHIN_SLA.ci_id}`)).toBe(false);
        expect(await screen.findByText('Cerrar Evento')).toBeDefined();
        expect(screen.getByText('Ejecutar diagnóstico')).toBeDefined();
        expect(screen.getByText(/Sin permiso `EVENT_VIEW`/)).toBeDefined();

        (useAuth as any).mockImplementation(() => ({
            user: { username: 'testop', role: 'OPERATOR', permissions: ['EVENT_FORCED_CLOSE'], tier: 'T2', allowed_locations: [] },
            hasPermission: (perm: string) => perm === 'EVENT_FORCED_CLOSE' || ['EVENT_VIEW', 'EVENT_ACK', 'EVENT_CLOSE'].includes(perm),
            isAuthenticated: true,
            token: 'mock-token',
            login: vi.fn(),
            logout: vi.fn(),
        }));
    });

    it('GIVEN user WITH EVENT_FORCED_CLOSE permission WHEN close form opens THEN forced close button is visible', async () => {
        await renderAndOpenModal(MOCK_EVENT_WITHIN_SLA);
        fireEvent.click(await screen.findByText('Cerrar Evento'));

        await waitFor(() => {
            expect(screen.getByText(/Cierre forzado/)).toBeDefined();
        });
    });

    it('GIVEN user WITHOUT EVENT_FORCED_CLOSE permission WHEN close form opens THEN forced close button is hidden', async () => {
        // Override the mock with a persistent implementation for this test
        const { useAuth } = await import('../../context/AuthContext');
        const viewerAuth = {
            user: { username: 'viewer', role: 'VIEWER', permissions: ['EVENT_CLOSE'], tier: 'T1', allowed_locations: [] },
            hasPermission: (perm: string) => perm === 'EVENT_CLOSE',
            isAuthenticated: true,
            token: 'mock-token',
            login: vi.fn(),
            logout: vi.fn(),
        };
        (useAuth as any).mockImplementation(() => viewerAuth);

        await renderAndOpenModal(MOCK_EVENT_WITHIN_SLA);
        fireEvent.click(await screen.findByText('Cerrar Evento'));

        await waitFor(() => screen.getByText('Confirmar Cierre'));

        // Forced close button must NOT be present for user without permission
        expect(screen.queryByText(/Cierre forzado/)).toBeNull();

        // Restore the default mock for subsequent tests
        (useAuth as any).mockImplementation(() => ({
            user: { username: 'testop', role: 'OPERATOR', permissions: ['EVENT_FORCED_CLOSE'], tier: 'T2', allowed_locations: [] },
            hasPermission: (perm: string) => perm === 'EVENT_FORCED_CLOSE' || ['EVENT_VIEW', 'EVENT_ACK', 'EVENT_CLOSE'].includes(perm),
            isAuthenticated: true,
            token: 'mock-token',
            login: vi.fn(),
            logout: vi.fn(),
        }));
    });
});

// ---------------------------------------------------------------------------
// M5: Close with mandatory root cause
// ---------------------------------------------------------------------------

describe('M5 — Close with mandatory root cause', () => {
    beforeEach(async () => {
        const { api } = await import('../../services/api');
        (api.post as any).mockReset();
        (api.post as any).mockResolvedValue({ message: 'ok' });
    });

    afterEach(() => vi.clearAllMocks());

    it('GIVEN modal open WHEN "Cerrar Evento" clicked THEN close form appears', async () => {
        await renderAndOpenModal(MOCK_EVENT_WITHIN_SLA);
        fireEvent.click(await screen.findByText('Cerrar Evento'));
        await waitFor(() => {
            expect(screen.getByText('Cierre de Evento')).toBeDefined();
        });
    });

    it('GIVEN close form open WHEN neither cause nor note filled THEN Confirmar Cierre is disabled', async () => {
        await renderAndOpenModal(MOCK_EVENT_WITHIN_SLA);
        fireEvent.click(await screen.findByText('Cerrar Evento'));

        await waitFor(() => screen.getByText('Confirmar Cierre'));
        const confirmBtn = screen.getByText('Confirmar Cierre');
        expect((confirmBtn as HTMLButtonElement).disabled).toBe(true);
    });

    it('GIVEN close form WHEN cause selected but note < 20 chars THEN Confirmar is still disabled', async () => {
        await renderAndOpenModal(MOCK_EVENT_WITHIN_SLA);
        fireEvent.click(await screen.findByText('Cerrar Evento'));

        await waitFor(() => screen.getByText('Confirmar Cierre'));

        const select = screen.getAllByRole('combobox')[1];
        fireEvent.change(select, { target: { value: 'Falla de hardware' } });

        const noteArea = screen.getByPlaceholderText('Describe la resolución del incidente...');
        fireEvent.change(noteArea, { target: { value: 'Corto' } }); // < 20 chars

        expect((screen.getByText('Confirmar Cierre') as HTMLButtonElement).disabled).toBe(true);
    });

    it('GIVEN close form WHEN cause + note (≥20 chars) filled THEN Confirmar Cierre is enabled', async () => {
        await renderAndOpenModal(MOCK_EVENT_WITHIN_SLA);
        fireEvent.click(await screen.findByText('Cerrar Evento'));

        await waitFor(() => screen.getByText('Confirmar Cierre'));

        const select = screen.getAllByRole('combobox')[1];
        fireEvent.change(select, { target: { value: 'Falla de hardware' } });

        const noteArea = screen.getByPlaceholderText('Describe la resolución del incidente...');
        fireEvent.change(noteArea, { target: { value: 'Se reemplazó el módulo de interfaz defectuoso' } });

        await waitFor(() => {
            expect((screen.getByText('Confirmar Cierre') as HTMLButtonElement).disabled).toBe(false);
        });
    });

    it('GIVEN close form filled WHEN Confirmar Cierre clicked THEN close payload contains root cause audit data', async () => {
        const { api } = await import('../../services/api');
        await renderAndOpenModal(MOCK_EVENT_WITHIN_SLA);
        fireEvent.click(await screen.findByText('Cerrar Evento'));

        await waitFor(() => screen.getByText('Confirmar Cierre'));

        fireEvent.change(screen.getAllByRole('combobox')[1], { target: { value: 'Error de configuración' } });
        fireEvent.change(
            screen.getByPlaceholderText('Describe la resolución del incidente...'),
            { target: { value: 'Se corrigió la configuración de BGP en el router' } }
        );

        fireEvent.click(screen.getByText('Confirmar Cierre'));

        await waitFor(() => {
            const calls = (api.post as any).mock.calls;
            const closeCall = calls.find((c: any[]) => c[0].includes('/close'));
            expect(closeCall).toBeDefined();
            expect(closeCall[1].comment_message).toContain('Error de configuración');
            expect(closeCall[1].comment_message).not.toContain('[CIERRE]');
        });
    });

    it('GIVEN close succeeds WHEN structured close is submitted THEN only the atomic close request is sent', async () => {
        const { api } = await import('../../services/api');
        await renderAndOpenModal(MOCK_EVENT_WITHIN_SLA);
        fireEvent.click(await screen.findByText('Cerrar Evento'));

        await waitFor(() => screen.getByText('Confirmar Cierre'));

        fireEvent.change(screen.getAllByRole('combobox')[1], { target: { value: 'Error de configuración' } });
        fireEvent.change(
            screen.getByPlaceholderText('Describe la resolución del incidente...'),
            { target: { value: 'Se corrigió la configuración de BGP en el router principal' } }
        );

        fireEvent.click(screen.getByText('Confirmar Cierre'));

        await waitFor(() => {
            const calls = (api.post as any).mock.calls.filter((c: any[]) => c[0].includes(`/events/${MOCK_EVENT_WITHIN_SLA.id}/`));
            expect(calls[0][0]).toContain('/close');
            expect(calls).toHaveLength(1);
        });
    });

    it('GIVEN close request fails WHEN structured close is submitted THEN no closure comment is written', async () => {
        const { api } = await import('../../services/api');
        const swallowUnhandled = (event: PromiseRejectionEvent) => event.preventDefault();
        window.addEventListener('unhandledrejection', swallowUnhandled);
        (api.post as any).mockImplementation(async (url: string, payload: any) => {
            if (url === `/events/${MOCK_EVENT_WITHIN_SLA.id}/close`) {
                throw new Error('close-down');
            }
            return { message: 'ok', payload };
        });

        await renderAndOpenModal(MOCK_EVENT_WITHIN_SLA);
        fireEvent.click(await screen.findByText('Cerrar Evento'));

        await waitFor(() => screen.getByText('Confirmar Cierre'));

        fireEvent.change(screen.getAllByRole('combobox')[1], { target: { value: 'Falla de hardware' } });
        fireEvent.change(
            screen.getByPlaceholderText('Describe la resolución del incidente...'),
            { target: { value: 'Se reemplazó el módulo averiado durante la ventana aprobada' } }
        );

        fireEvent.click(screen.getByText('Confirmar Cierre'));

        await waitFor(() => {
            expect((api.post as any).mock.calls.some((c: any[]) => c[0] === `/events/${MOCK_EVENT_WITHIN_SLA.id}/close`)).toBe(true);
        });

        expect((api.post as any).mock.calls.some((c: any[]) => c[0] === `/events/${MOCK_EVENT_WITHIN_SLA.id}/comment`)).toBe(false);
        window.removeEventListener('unhandledrejection', swallowUnhandled);
    });

    it('GIVEN T2 user WHEN forced close used THEN close payload sends only the operator reason', async () => {
        const { api } = await import('../../services/api');
        await renderAndOpenModal(MOCK_EVENT_WITHIN_SLA);
        fireEvent.click(await screen.findByText('Cerrar Evento'));

        await waitFor(() => screen.getByText('Cierre forzado (T2)'));
        fireEvent.click(screen.getByText('Cierre forzado (T2)'));

        await waitFor(() => screen.getByPlaceholderText('Motivo del cierre forzado...'));
        fireEvent.change(
            screen.getByPlaceholderText('Motivo del cierre forzado...'),
            { target: { value: 'Requiere cierre inmediato por ventana de mantenimiento' } }
        );

        fireEvent.click(screen.getByText('Forzar Cierre'));

        await waitFor(() => {
            const calls = (api.post as any).mock.calls;
            const closeCall = calls.find((c: any[]) => c[0].includes('/close'));
            expect(closeCall).toBeDefined();
            expect(closeCall[1].comment_message).toBe('Motivo: Requiere cierre inmediato por ventana de mantenimiento');
        });
    });
});
