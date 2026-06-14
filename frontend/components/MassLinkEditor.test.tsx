import React from 'react';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import MassLinkEditor from './MassLinkEditor';

const mocks = vi.hoisted(() => ({
    mockUseCategoriesQuery: vi.fn(),
    mockUseQuery: vi.fn(),
}));

vi.mock('../hooks/queries/useCategoriesQuery', () => ({
    useCategoriesQuery: mocks.mockUseCategoriesQuery,
}));

vi.mock('@tanstack/react-query', () => ({
    useQuery: mocks.mockUseQuery,
}));

vi.mock('./RelationshipTooltip', () => ({
    default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock('./RelationshipBadge', () => ({
    default: () => null,
}));

const nodes = [
    {
        id: 'router-1',
        label: 'Router 1',
        type: 'INFRASTRUCTURE',
        status: 'ACTIVE',
        metadata: {},
        ip: '10.0.0.1',
        location_name: 'MDF',
        category: 'Network',
        category_icon_key: 'router',
    },
    {
        id: 'switch-1',
        label: 'Switch 1',
        type: 'INFRASTRUCTURE',
        status: 'ACTIVE',
        metadata: {},
        ip: '10.0.0.2',
        location_name: 'IDF',
        category: 'Layer 2 switch',
    },
];

describe('MassLinkEditor technology icons', () => {
    beforeEach(() => {
        mocks.mockUseCategoriesQuery.mockReset();
        mocks.mockUseQuery.mockReset();

        mocks.mockUseCategoriesQuery.mockReturnValue({
            data: [
                { name: 'Network', icon_key: 'router' },
                { name: 'Layer 2 switch', icon_key: 'switch_l2' },
            ],
        });
        mocks.mockUseQuery.mockImplementation(({ queryKey }: { queryKey: string[] }) => {
            if (queryKey[0] === 'nodes') return { data: nodes };
            if (queryKey[0] === 'metrics') return { data: [] };
            return { data: undefined };
        });
    });

    it('renders shared technology icons for CI candidates without using status as the icon', () => {
        render(<MassLinkEditor />);

        expect(screen.getAllByRole('img', { name: 'Router technology icon' })).toHaveLength(2);
        expect(screen.getAllByText('router')).toHaveLength(2);
        expect(screen.queryByText('ACTIVE')).not.toBeInTheDocument();
    });

    it('falls back to category name resolution when a candidate has no explicit icon key', () => {
        render(<MassLinkEditor />);

        expect(screen.getAllByRole('img', { name: 'Layer 2 Switch technology icon' })).toHaveLength(2);
        expect(screen.getAllByText('lan')).toHaveLength(2);
    });
});
