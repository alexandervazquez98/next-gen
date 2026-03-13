/**
 * MonitoringConsole.smoke.test.tsx
 *
 * Smoke tests for MonitoringConsole.
 * Verifies the component mounts without errors and that banned imports
 * (leaflet-ant-path) are not present.
 *
 * react-leaflet and leaflet are mocked because they require a real browser
 * DOM with canvas/SVG that jsdom does not fully support.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

// Mock api service — returns empty arrays to avoid fetch errors in jsdom
vi.mock('../../services/api', () => ({
    api: {
        get: vi.fn().mockResolvedValue([]),
        post: vi.fn().mockResolvedValue({ message: 'ok' }),
    },
}));

// Mock react-leaflet — components that need real Leaflet/canvas are stubbed
vi.mock('react-leaflet', () => ({
    MapContainer: ({ children }: any) => <div data-testid="map-container">{children}</div>,
    TileLayer: () => null,
    Polyline: () => null,
    CircleMarker: ({ children }: any) => <div>{children}</div>,
    Circle: () => null,
    Popup: ({ children }: any) => <div>{children}</div>,
    useMap: () => ({ fitBounds: vi.fn() }),
}));

// Mock leaflet itself to avoid window/document errors
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

// Mock leaflet CSS — not needed in tests
vi.mock('leaflet/dist/leaflet.css', () => ({}));

// Mock child components that have their own complex deps
vi.mock('../DependencyMiniMap', () => ({
    default: () => <div data-testid="dependency-mini-map" />,
}));

vi.mock('../../hooks/useEventCorrelation', () => ({
    useEventCorrelation: (_events: any[], _links: any[]) => [],
}));

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('MonitoringConsole smoke tests', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('GIVEN the component WHEN rendered with empty data THEN mounts without throwing', async () => {
        // Dynamic import after mocks are registered
        const { default: MonitoringConsole } = await import('../MonitoringConsole');

        expect(() => render(<MonitoringConsole />)).not.toThrow();
    });

    it('GIVEN the component WHEN rendered THEN Event Console header is visible', async () => {
        const { default: MonitoringConsole } = await import('../MonitoringConsole');

        render(<MonitoringConsole />);

        expect(screen.getByText('Event Console')).toBeDefined();
    });

    it('GIVEN the module WHEN imported THEN has no reference to leaflet-ant-path', async () => {
        // Read the source file as text and assert the banned import is absent.
        // This is a static analysis guard that runs at test time.
        const fs = await import('fs');
        const path = await import('path');
        const filePath = path.resolve(
            process.cwd(),
            'components/MonitoringConsole.tsx'
        );
        const source = fs.readFileSync(filePath, 'utf-8');

        expect(source).not.toContain('leaflet-ant-path');
        expect(source).not.toContain('AntPath');
    });

    it('GIVEN the module WHEN imported THEN has no animate-ping or animate-pulse on map markers', async () => {
        const fs = await import('fs');
        const path = await import('path');
        const filePath = path.resolve(
            process.cwd(),
            'components/MonitoringConsole.tsx'
        );
        const source = fs.readFileSync(filePath, 'utf-8');

        // These Tailwind classes caused the full-map red flash — must not appear
        // inside pathOptions of CircleMarker/Circle (map section)
        // We check that neither className: 'animate-ping' nor animate-pulse appears
        // in pathOptions objects (the map markers section)
        expect(source).not.toContain("className: 'animate-ping'");
        expect(source).not.toContain("className: 'animate-pulse'");
    });
});
