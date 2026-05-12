import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { fetchNodesSearch } from './queryResources';

const { mockApiGet } = vi.hoisted(() => ({
  mockApiGet: vi.fn(),
}));

vi.mock('./api', () => ({
  api: {
    get: mockApiGet,
  },
}));

describe('fetchNodesSearch', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockApiGet.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('calls /nodes/search with q query param', async () => {
    mockApiGet.mockResolvedValue([
      { id: 'CI-001', label: 'Router', status: 'OK', ip: '192.168.1.1' }
    ]);

    await fetchNodesSearch({ q: 'router' });

    expect(mockApiGet).toHaveBeenCalledWith('/nodes/search', expect.objectContaining({ q: 'router' }));
  });

  it('forwards abort signal', async () => {
    mockApiGet.mockResolvedValue([]);
    const signal = new AbortController().signal;

    await fetchNodesSearch({ q: 'server', signal });

    expect(mockApiGet).toHaveBeenCalledWith('/nodes/search', expect.objectContaining({ signal }));
  });

  it('returns array of nodes on success', async () => {
    const mockNodes = [
      { id: 'CI-001', label: 'Core Router', ip: '192.168.1.1', status: 'OK', brand: 'Cisco', model: 'ASR-1000' },
      { id: 'CI-002', label: 'Backup Router', ip: '192.168.1.2', status: 'ACTIVE', brand: 'Juniper', model: 'MX204' },
    ];
    mockApiGet.mockResolvedValue(mockNodes);

    const result = await fetchNodesSearch({ q: 'router' });

    expect(result).toEqual(mockNodes);
    expect(mockApiGet).toHaveBeenCalledTimes(1);
  });

  it('throws ApiError for non-2xx responses', async () => {
    mockApiGet.mockRejectedValue(new Error('Query must be at least 2 characters'));

    await expect(fetchNodesSearch({ q: 'a' })).rejects.toThrow('Query must be at least 2 characters');
  });
});