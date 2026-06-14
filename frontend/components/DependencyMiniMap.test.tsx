import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import DependencyMiniMap from './DependencyMiniMap';
import type { Event, GraphLink, GraphNode } from '../types';

const baseEvent: Event = {
    id: 'event-1',
    ci_id: 'router-1',
    ci_name: 'Router 1',
    metric_id: 'metric-1',
    metric_name: 'Ping',
    status: 'OPEN',
    severity: 'CRITICAL',
    message: 'PING Down',
    created_at: '2026-06-14T00:00:00Z',
    last_seen: '2026-06-14T00:00:00Z',
    ack: false,
};

const renderMiniMap = (nodes: GraphNode[], links: GraphLink[] = [], event = baseEvent) =>
    render(<DependencyMiniMap ciId={nodes[0].id} nodes={nodes} links={links} event={event} />);

describe('DependencyMiniMap technology icons', () => {
    it('renders the shared technology icon from category_icon_key while keeping status separate', async () => {
        renderMiniMap([
            {
                id: 'router-1',
                label: 'Router 1',
                type: 'INFRASTRUCTURE',
                status: 'ACTIVE',
                metadata: {},
                category: 'Network',
                category_icon_key: 'router',
                hasCritical: true,
            },
        ]);

        const icon = await screen.findByRole('img', { name: 'Router technology icon' });

        expect(icon).toHaveTextContent('router');
        expect(screen.getByText('CAÍDO')).toBeInTheDocument();
        expect(icon).not.toHaveTextContent('CAÍDO');
    });

    it('falls back to category-derived technology icon when no explicit icon key exists', async () => {
        renderMiniMap([
            {
                id: 'switch-1',
                label: 'Switch 1',
                type: 'INFRASTRUCTURE',
                status: 'ACTIVE',
                metadata: {},
                category: 'Layer 2 switch',
                hasWarning: true,
            },
        ], [], { ...baseEvent, ci_id: 'switch-1', severity: 'WARNING', message: 'CPU Threshold' });

        await waitFor(() => {
            expect(screen.getByRole('img', { name: 'Layer 2 Switch technology icon' })).toHaveTextContent('lan');
        });
        expect(screen.getByText('WARNING')).toBeInTheDocument();
    });
});
