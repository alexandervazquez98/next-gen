import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { ApiError, api } from '../services/api';

// Mock react-router-dom's useNavigate since api.ts imports it
vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
}));

describe('ApiError', () => {
  it('creates error with message and status', () => {
    const err = new ApiError('Not found', 404);
    expect(err.message).toBe('Not found');
    expect(err.status).toBe(404);
    expect(err).toBeInstanceOf(Error);
  });
});

describe('api client', () => {
  const originalFetch = global.fetch;
  const originalLocation = window.location;

  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    // Mock window.location.href for 401 redirect tests
    Object.defineProperty(window, 'location', {
      value: { href: '' },
      writable: true,
      configurable: true,
    });
  });

  afterEach(() => {
    global.fetch = originalFetch;
    Object.defineProperty(window, 'location', {
      value: originalLocation,
      writable: true,
      configurable: true,
    });
  });

  describe('get (successful)', () => {
    it('calls fetch with correct URL and headers', async () => {
      const mockData = { id: '1', name: 'test' };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: { get: () => 'application/json' },
        json: () => Promise.resolve(mockData),
      });

      const result = await api.get('/nodes');

      expect(global.fetch).toHaveBeenCalledWith('/api/nodes', {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
      });
      expect(result).toEqual(mockData);
    });

    it('adds Authorization header when token exists', async () => {
      localStorage.setItem('token', 'fake-token');
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: { get: () => 'application/json' },
        json: () => Promise.resolve({}),
      });

      await api.get('/nodes');

      expect(global.fetch).toHaveBeenCalledWith('/api/nodes', {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer fake-token',
        },
      });
    });

    it('throws ApiError for 404 responses', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        status: 404,
        ok: false,
        statusText: 'Not Found',
        headers: { get: () => 'application/json' },
        json: () => Promise.resolve({ detail: 'Not found' }),
      });

      await expect(api.get('/nonexistent')).rejects.toBeInstanceOf(ApiError);
      await expect(api.get('/nonexistent')).rejects.toMatchObject({
        status: 404,
        message: 'Not found',
      });
    });

    it('throws ApiError for non-2xx responses', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
        headers: { get: () => 'application/json' },
        json: () => Promise.resolve({ detail: 'DB error' }),
      });

      await expect(api.get('/nodes')).rejects.toThrow('DB error');
      await expect(api.get('/nodes')).rejects.toHaveProperty('status', 500);
    });

    it('throws ApiError with statusText when no detail in body', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
        headers: { get: () => 'application/json' },
        json: () => Promise.resolve({}),
      });

      await expect(api.get('/nodes')).rejects.toThrow('Internal Server Error');
    });
  });

  describe('post', () => {
    it('sends POST request with JSON body', async () => {
      const created = { id: 'new-1' };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 201,
        headers: { get: () => 'application/json' },
        json: () => Promise.resolve(created),
      });

      const result = await api.post('/nodes', { name: 'test' });

      expect(global.fetch).toHaveBeenCalledWith('/api/nodes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: 'test' }),
      });
      expect(result).toEqual(created);
    });

    it('forwards signal without dropping auth and json headers', async () => {
      const signal = new AbortController().signal;
      localStorage.setItem('token', 'fake-token');
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 201,
        headers: { get: () => 'application/json' },
        json: () => Promise.resolve({ ok: true }),
      });

      await api.post('/nodes', { name: 'test' }, { signal });

      expect(global.fetch).toHaveBeenCalledWith('/api/nodes', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer fake-token',
        },
        body: JSON.stringify({ name: 'test' }),
        signal,
      });
    });
  });

  describe('put', () => {
    it('sends PUT request with JSON body', async () => {
      const updated = { id: '1', name: 'updated' };
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: { get: () => 'application/json' },
        json: () => Promise.resolve(updated),
      });

      const result = await api.put('/nodes/1', { name: 'updated' });

      expect(global.fetch).toHaveBeenCalledWith('/api/nodes/1', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: 'updated' }),
      });
      expect(result).toEqual(updated);
    });

    it('forwards signal for put requests', async () => {
      const signal = new AbortController().signal;
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: { get: () => 'application/json' },
        json: () => Promise.resolve({ ok: true }),
      });

      await api.put('/nodes/1', { name: 'updated' }, { signal });

      expect(global.fetch).toHaveBeenCalledWith('/api/nodes/1', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: 'updated' }),
        signal,
      });
    });
  });

  describe('delete', () => {
    it('sends DELETE request without body by default', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 204,
        headers: { get: () => null },
        text: () => Promise.resolve(''),
      });

      await api.delete('/nodes/1');

      expect(global.fetch).toHaveBeenCalledWith('/api/nodes/1', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: undefined,
      });
    });

    it('sends DELETE request with body when provided', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: { get: () => 'application/json' },
        json: () => Promise.resolve({}),
      });

      await api.delete('/nodes/1', { force: true });

      expect(global.fetch).toHaveBeenCalledWith('/api/nodes/1', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force: true }),
      });
    });

    it('forwards signal for delete requests', async () => {
      const signal = new AbortController().signal;
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: { get: () => 'application/json' },
        json: () => Promise.resolve({}),
      });

      await api.delete('/nodes/1', { force: true }, { signal });

      expect(global.fetch).toHaveBeenCalledWith('/api/nodes/1', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force: true }),
        signal,
      });
    });
  });

  describe('request forwarding', () => {
    it('forwards signal for request and keeps caller headers', async () => {
      const signal = new AbortController().signal;
      localStorage.setItem('token', 'fake-token');
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: { get: () => 'application/json' },
        json: () => Promise.resolve({ ok: true }),
      });

      await api.request('/custom', {
        method: 'GET',
        signal,
        headers: { Accept: 'application/json' },
      });

      const [url, options] = global.fetch.mock.calls[0];
      expect(url).toBe('/api/custom');
      expect(options.method).toBe('GET');
      expect(options.signal).toBe(signal);
      expect(options.headers['Authorization']).toBe('Bearer fake-token');
      expect(options.headers['Accept']).toBe('application/json');
    });

    it('forwards signal for get requests', async () => {
      const signal = new AbortController().signal;
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: { get: () => 'application/json' },
        json: () => Promise.resolve({ ok: true }),
      });

      await api.get('/nodes', { signal });

      expect(global.fetch).toHaveBeenCalledWith('/api/nodes', {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
        signal,
      });
    });
  });

  describe('401 handling', () => {
    it('clears token and redirects on 401', async () => {
      localStorage.setItem('token', 'stale-token');
      global.fetch = vi.fn().mockResolvedValue({
        status: 401,
        ok: false,
      });

      await expect(api.get('/nodes')).rejects.toThrow('Unauthorized');

      expect(localStorage.getItem('token')).toBeNull();
      expect(window.location.href).toBe('/login');
    });
  });

  describe('endpoint normalization', () => {
    it('prepends /api and adds leading slash if missing', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: { get: () => 'application/json' },
        json: () => Promise.resolve({}),
      });

      await api.get('nodes'); // no leading slash

      expect(global.fetch).toHaveBeenCalledWith('/api/nodes', expect.any(Object));
    });

    it('does not double-slash when endpoint starts with /', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: { get: () => 'application/json' },
        json: () => Promise.resolve({}),
      });

      await api.get('/nodes');

      expect(global.fetch).toHaveBeenCalledWith('/api/nodes', expect.any(Object));
    });
  });

  describe('non-JSON responses', () => {
    it('returns text when content-type is not JSON', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: { get: () => 'text/plain' },
        text: () => Promise.resolve('ok'),
      });

      const result = await api.get('/health');
      expect(result).toBe('ok');
    });
  });
});
