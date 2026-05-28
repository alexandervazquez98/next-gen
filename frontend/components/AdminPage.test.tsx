import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import AdminPage from './AdminPage';

const { mockApiGet, mockApiPost } = vi.hoisted(() => ({
    mockApiGet: vi.fn(),
    mockApiPost: vi.fn(),
}));

vi.mock('../services/api', () => ({
    api: {
        get: mockApiGet,
        post: mockApiPost,
        delete: vi.fn(),
        download: vi.fn(),
        request: vi.fn(),
    },
}));

vi.mock('../context/AuthContext', () => ({
    useAuth: () => ({ hasPermission: () => true }),
}));

vi.mock('./MetricsManager', () => ({ default: () => <div>Metrics Manager</div> }));
vi.mock('./DictionaryManager', () => ({ default: () => <div>Dictionary Manager</div> }));
vi.mock('./CIEditor', () => ({ default: () => <div>CI Editor</div> }));
vi.mock('./RelationshipManager', () => ({ default: () => <div>Relationship Manager</div> }));
vi.mock('./MassLinkEditor', () => ({ default: () => <div>Mass Link Editor</div> }));
vi.mock('./CatalogManager', () => ({ default: () => <div>Catalog Manager</div> }));

const nodes = [
    { id: 'ci-a', label: 'Router A', type: 'Network', status: 'ACTIVE', ip: '10.0.0.1' },
    { id: 'ci-b', label: 'Switch B', type: 'Network', status: 'ACTIVE', ip: '10.0.0.2' },
    { id: 'ci-c', label: 'Server C', type: 'Server', status: 'MAINTENANCE', ip: '10.0.0.3' },
    { id: 'ci-d', label: 'Camera D', type: 'Camera', status: 'ACTIVE', ip: '10.0.0.4' },
];

const relationships = {
    'ci-a': {
        asSource: [{ otherId: 'ci-b', otherLabel: 'Switch B', type: 'CONNECTS_TO' }],
        asTarget: [],
    },
    'ci-b': {
        asSource: [],
        asTarget: [{ otherId: 'ci-a', otherLabel: 'Router A', type: 'CONNECTS_TO' }],
    },
    'ci-c': {
        asSource: [{ otherId: 'ci-d', otherLabel: 'Camera D', type: 'HOSTED_ON' }],
        asTarget: [{ otherId: 'ci-a', otherLabel: 'Router A', type: 'DEPENDS_ON' }],
    },
    'ci-d': { asSource: [], asTarget: [] },
};

describe('AdminPage inventory relationships', () => {
    beforeEach(() => {
        mockApiGet.mockReset();
        mockApiPost.mockReset();
        mockApiGet.mockImplementation((endpoint: string) => {
            if (endpoint === '/nodes') return Promise.resolve(nodes);
            return Promise.resolve([]);
        });
        mockApiPost.mockImplementation((endpoint: string) => {
            if (endpoint === '/cis/relationships') return Promise.resolve(relationships);
            return Promise.resolve({});
        });
    });

    it('fetches visible inventory relationships and renders none/incoming/outgoing/both indicators', async () => {
        render(<AdminPage />);

        fireEvent.click(screen.getByRole('button', { name: 'INVENTORY' }));

        expect(await screen.findByText('Router A')).toBeInTheDocument();
        await waitFor(() => {
            expect(mockApiPost).toHaveBeenCalledWith('/cis/relationships', {
                ci_ids: ['ci-a', 'ci-b', 'ci-c', 'ci-d'],
            });
        });

        expect(await screen.findByText('Outgoing')).toBeInTheDocument();
        expect(screen.getByText('Incoming')).toBeInTheDocument();
        expect(screen.getByText('Incoming + outgoing')).toBeInTheDocument();
        expect(screen.getByText('No correlations')).toBeInTheDocument();
    });

    it('shows selected CI relationship details with direction, type, related label, and id', async () => {
        render(<AdminPage />);

        fireEvent.click(screen.getByRole('button', { name: 'INVENTORY' }));
        fireEvent.click(await screen.findByText('Router A'));

        expect(await screen.findByText('CI Correlation Details')).toBeInTheDocument();
        expect(screen.getByText('OUTGOING')).toBeInTheDocument();
        expect(screen.getByText('CONNECTS_TO')).toBeInTheDocument();
        expect(screen.getAllByText('Switch B').length).toBeGreaterThan(0);
        expect(screen.getAllByText('ci-b').length).toBeGreaterThan(0);
    });
});
