import { describe, it, expect, beforeEach, vi } from 'vitest';
import { api, ApiError } from './api';

describe('api client', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    // Default window.location mock setup for tests
    if (typeof window !== 'undefined') {
      window.location = {
        pathname: '/',
        hash: '',
        href: '',
      } as any;
    }
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
        credentials: 'include',
      });
      expect(result).toEqual(mockData);
    });

    it('does not add Authorization header automatically (relies on cookies)', async () => {
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
        },
        credentials: 'include',
      });
    });
  });

  describe('errors handling', () => {
    it('throws ApiError with detail from response body', async () => {
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
        credentials: 'include',
      });
      expect(result).toEqual(created);
    });

    it('forwards signal and preserves caller-provided headers', async () => {
      const signal = new AbortController().signal;
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 201,
        headers: { get: () => 'application/json' },
        json: () => Promise.resolve({ ok: true }),
      });

      await api.post('/nodes', { name: 'test' }, { 
        signal,
        headers: { 'Authorization': 'Bearer fake-token' }
      });

      expect(global.fetch).toHaveBeenCalledWith('/api/nodes', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer fake-token',
        },
        body: JSON.stringify({ name: 'test' }),
        signal,
        credentials: 'include',
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
        credentials: 'include',
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
        credentials: 'include',
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
        credentials: 'include',
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
        credentials: 'include',
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
        credentials: 'include',
      });
    });
  });

  describe('request forwarding', () => {
    it('forwards signal for request and keeps caller headers', async () => {
      const signal = new AbortController().signal;
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: { get: () => 'application/json' },
        json: () => Promise.resolve({ ok: true }),
      });

      await api.request('/custom', {
        method: 'GET',
        signal,
        headers: { 
          Accept: 'application/json',
          Authorization: 'Bearer fake-token'
        },
      });

      const [url, options] = global.fetch.mock.calls[0];
      expect(url).toBe('/api/custom');
      expect(options.method).toBe('GET');
      expect(options.signal).toBe(signal);
      expect(options.headers['Authorization']).toBe('Bearer fake-token');
      expect(options.headers['Accept']).toBe('application/json');
      expect(options.credentials).toBe('include');
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
        credentials: 'include',
      });
    });
  });

  describe('401 handling', () => {
    it('redirects on 401 when refresh fails', async () => {
      // Mock window.location
      const originalLocation = window.location;
      delete (window as any).location;
      window.location = {
        pathname: '/',
        hash: '',
        href: '',
      } as any;

      global.fetch = vi.fn().mockResolvedValue({
        status: 401,
        ok: false,
        headers: { get: () => 'application/json' },
        json: () => Promise.resolve({ detail: 'Session expired' }),
      });

      await expect(api.get('/nodes')).rejects.toThrow('Session expired');

      expect(window.location.href).toBe('/login');

      // Restore window.location
      window.location = originalLocation;
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
