import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import NetworkVisualizer from './NetworkVisualizer';

vi.mock('react-force-graph-3d', async () => {
    const React = await vi.importActual<typeof import('react')>('react');

    return {
        default: React.forwardRef((props: any, ref) => {
            React.useImperativeHandle(ref, () => ({
                d3Force: () => ({
                    strength: vi.fn(),
                    distance: vi.fn(),
                }),
                zoomToFit: vi.fn(),
            }));

            return (
                <div data-testid="force-graph">
                    {props.graphData.nodes.map((node: any) => (
                        <div key={node.id} data-testid={`node-color-${node.id}`}>
                            {props.nodeColor(node)}
                        </div>
                    ))}
                </div>
            );
        }),
    };
});

const graphPayload = {
    nodes: [
        {
            id: 'router-1',
            label: 'Router 1',
            type: 'CI',
            status: 'CRITICAL',
            category: 'Network',
            category_icon_key: 'router',
        },
        {
            id: 'switch-1',
            label: 'Switch 1',
            type: 'CI',
            status: 'ACTIVE',
            category: 'Layer 2 switch',
        },
    ],
    links: [],
};

describe('NetworkVisualizer technology icons', () => {
    beforeEach(() => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
            json: async () => graphPayload,
        }));
    });

    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('renders the shared technology icon from category_icon_key while keeping status color separate', async () => {
        render(<NetworkVisualizer />);

        await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/graph/full'));
        fireEvent.click(screen.getByRole('button', { name: 'SHOW INFRASTRUCTURE (CIs)' }));

        const icon = await screen.findByRole('img', { name: 'Router technology icon' });

        expect(icon).toHaveTextContent('router');
        expect(icon).not.toHaveTextContent('CRITICAL');
        expect(screen.getByTestId('node-color-router-1')).toHaveTextContent('#ff0055');
    });

    it('falls back to category-derived technology icon when no explicit icon key exists', async () => {
        render(<NetworkVisualizer />);

        await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/graph/full'));
        fireEvent.click(screen.getByRole('button', { name: 'SHOW INFRASTRUCTURE (CIs)' }));

        const icon = await screen.findByRole('img', { name: 'Layer 2 Switch technology icon' });

        expect(icon).toHaveTextContent('lan');
        expect(screen.getByText('Switch 1')).toBeInTheDocument();
    });
});
