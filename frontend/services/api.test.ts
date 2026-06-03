import { describe, it, expect, beforeEach, vi } from 'vitest';
import { api, ApiError } from './api';
import { subscribeAuthSessionEvents } from './sessionBus';

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
      document.cookie = 'access_token=; Max-Age=0; path=/';
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
    const jsonResponse = (status: number, body: any, statusText = 'Unauthorized') => ({
      ok: status >= 200 && status < 300,
      status,
      statusText,
      headers: { get: () => 'application/json' },
      json: () => Promise.resolve(body),
    });

    it('coalesces parallel 401 requests into a single refresh and retries each original request once', async () => {
      const fetchMock = vi.fn(async (url: string) => {
        if (url === '/api/auth/refresh') return jsonResponse(200, { access_token: 'rotated' });
        const callsForUrl = fetchMock.mock.calls.filter(([calledUrl]) => calledUrl === url).length;
        return callsForUrl === 1 ? jsonResponse(401, { detail: 'Unauthorized' }) : jsonResponse(200, { url });
      });
      global.fetch = fetchMock;

      await expect(Promise.all([api.get('/nodes'), api.get('/devices')])).resolves.toEqual([
        { url: '/api/nodes' },
        { url: '/api/devices' },
      ]);
      expect(fetchMock.mock.calls.filter(([url]) => url === '/api/auth/refresh')).toHaveLength(1);
      expect(fetchMock.mock.calls.filter(([url]) => url === '/api/nodes')).toHaveLength(2);
      expect(fetchMock.mock.calls.filter(([url]) => url === '/api/devices')).toHaveLength(2);
    });

    it('bounds failed parallel refresh attempts and redirects only once', async () => {
      const originalLocation = window.location;
      delete (window as any).location;
      window.location = { pathname: '/', hash: '', href: '' } as any;
      const fetchMock = vi.fn(async (url: string) => (
        url === '/api/auth/refresh'
          ? jsonResponse(401, { detail: 'idle_timeout' })
          : jsonResponse(401, { detail: 'Unauthorized' })
      ));
      global.fetch = fetchMock;

      await expect(Promise.all([api.get('/nodes'), api.get('/devices')])).rejects.toThrow('idle_timeout');
      expect(fetchMock.mock.calls.filter(([url]) => url === '/api/auth/refresh')).toHaveLength(1);
      expect(window.location.href).toBe('/login');
      window.location = originalLocation;
    });

    it('does not recursively refresh refresh requests when skipAuthRefresh is set', async () => {
      const fetchMock = vi.fn().mockResolvedValue(jsonResponse(401, { detail: 'invalid_refresh_token' }));
      global.fetch = fetchMock;

      await expect(api.post('/auth/refresh', {}, { skipAuthRefresh: true } as RequestInit)).rejects.toThrow('invalid_refresh_token');
      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(fetchMock).toHaveBeenCalledWith('/api/auth/refresh', expect.objectContaining({ method: 'POST' }));
    });

    it('surfaces SSE refresh failures without redirecting unexpectedly', async () => {
      const originalLocation = window.location;
      delete (window as any).location;
      window.location = { pathname: '/', hash: '', href: '' } as any;
      global.fetch = vi.fn(async (url: string) => (
        url === '/api/auth/refresh'
          ? jsonResponse(401, { detail: 'session_expired' })
          : jsonResponse(401, { detail: 'Unauthorized' })
      ));

      await expect(api.getSSE('/events')).rejects.toThrow('session_expired');
      expect(window.location.href).toBe('');
      window.location = originalLocation;
    });

    it('redirects on 401 when refresh fails', async () => {
      const originalLocation = window.location;
      delete (window as any).location;
      window.location = { pathname: '/', hash: '', href: '' } as any;
      global.fetch = vi.fn().mockResolvedValue(jsonResponse(401, { detail: 'Session expired' }));

      await expect(api.get('/nodes')).rejects.toThrow('Session expired');
      expect(window.location.href).toBe('/login');
      window.location = originalLocation;
    });

    it('includes the current access-token session id on terminal refresh-failure events', async () => {
      const payload = btoa(JSON.stringify({ sid: 'session-from-token' }))
        .replace(/=/g, '')
        .replace(/\+/g, '-')
        .replace(/\//g, '_');
      document.cookie = `access_token=header.${payload}.signature; path=/`;
      const events: any[] = [];
      const unsubscribe = subscribeAuthSessionEvents(event => events.push(event));
      global.fetch = vi.fn(async (url: string) => (
        url === '/api/auth/refresh'
          ? jsonResponse(401, { detail: 'idle_timeout' })
          : jsonResponse(401, { detail: 'Unauthorized' })
      ));

      await expect(api.get('/nodes')).rejects.toThrow('idle_timeout');

      expect(events).toContainEqual(expect.objectContaining({
        type: 'session-expired',
        reason: 'idle_timeout',
        sessionId: 'session-from-token',
      }));
      unsubscribe();
    });

    it('omits session id on terminal refresh-failure events when the access token is unavailable or invalid', async () => {
      document.cookie = 'access_token=not-a-jwt; path=/';
      const events: any[] = [];
      const unsubscribe = subscribeAuthSessionEvents(event => events.push(event));
      global.fetch = vi.fn(async (url: string) => (
        url === '/api/auth/refresh'
          ? jsonResponse(401, { detail: 'session_expired' })
          : jsonResponse(401, { detail: 'Unauthorized' })
      ));

      await expect(api.get('/nodes')).rejects.toThrow('session_expired');

      expect(events).toContainEqual(expect.objectContaining({
        type: 'session-expired',
        reason: 'session_expired',
      }));
      expect(events.some(event => event.sessionId)).toBe(false);
      unsubscribe();
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
