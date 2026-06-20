import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import React from 'react';
import { AuthProvider, useAuth } from '../context/AuthContext';
import { publishAuthSessionEvent } from '../services/sessionBus';

// Mock react-router-dom for the api.ts import chain
vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
}));

// Mock sonner so the toast helper is trackable before the dependency is installed.
// PR2 (#287) installs `sonner` and AuthContext calls `toast(...)` from it.
const sonnerMocks = vi.hoisted(() => ({
  toast: vi.fn(),
}));
vi.mock('sonner', () => ({
  toast: sonnerMocks.toast,
}));

// Mock the api module - use vi.hoisted to avoid hoisting issues
const mocks = vi.hoisted(() => ({
  api: { get: vi.fn(), post: vi.fn() },
}));
vi.mock('../services/api', () => ({
  api: mocks.api,
}));

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <AuthProvider>{children}</AuthProvider>
);
const baseUser = { username: 'admin', role: 'USER', permissions: [], allowed_locations: [], tier: 'T1' };

describe('AuthContext', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    mocks.api.get.mockReset();
    mocks.api.post.mockReset();
    // Default: resolve with null user so hydration doesn't crash
    mocks.api.get.mockResolvedValue(null);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe('initial state', () => {
    it('starts loading and unauthenticated with no user', () => {
      const { result } = renderHook(() => useAuth(), { wrapper });
      expect(result.current.isAuthenticated).toBe(false);
      expect(result.current.user).toBeNull();
      expect(result.current.loading).toBe(true);
    });
  });

  describe('token hydration', () => {
    it('fetches user from /auth/users/me on mount', async () => {
      const mockUser = { username: 'admin', role: 'ADMIN', permissions: [], allowed_locations: [], tier: 'T3' };
      mocks.api.get.mockResolvedValue(mockUser);

      const { result } = renderHook(() => useAuth(), { wrapper });

      expect(mocks.api.get).toHaveBeenCalledWith('/auth/users/me');
      await waitFor(() => {
        expect(result.current.loading).toBe(false);
        expect(result.current.user).toEqual(mockUser);
        expect(result.current.isAuthenticated).toBe(true);
      });
    });

    it('preserves session policy metadata from /auth/users/me', async () => {
      const mockUser = {
        ...baseUser,
        session_id: 'session-123',
        session_policy: { profile: 'standard', idle_timeout_minutes: 30, persistent: false },
      };
      mocks.api.get.mockResolvedValue(mockUser);

      const { result } = renderHook(() => useAuth(), { wrapper });

      await waitFor(() => {
        expect(result.current.user?.session_id).toBe('session-123');
        expect(result.current.user?.session_policy).toEqual(mockUser.session_policy);
      });
    });

    it('sets user to null and loading to false if fetch fails', async () => {
      mocks.api.get.mockRejectedValue(new Error('Unauthorized'));

      const { result } = renderHook(() => useAuth(), { wrapper });

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
        expect(result.current.user).toBeNull();
        expect(result.current.isAuthenticated).toBe(false);
      });
    });
  });

  describe('login', () => {
    it('stores user in state and sets loading to false', () => {
      const { result } = renderHook(() => useAuth(), { wrapper });
      const user = { username: 'admin', role: 'ADMIN', permissions: [], allowed_locations: [], tier: 'T3' };

      act(() => {
        result.current.login(user);
      });

      expect(result.current.user).toEqual(user);
      expect(result.current.isAuthenticated).toBe(true);
      expect(result.current.loading).toBe(false);
    });
  });

  describe('logout', () => {
    it('calls api logout endpoint and clears user state', async () => {
      mocks.api.post.mockResolvedValue({ status: 'success' });
      const { result } = renderHook(() => useAuth(), { wrapper });

      act(() => {
        result.current.login({ username: 'admin', role: 'ADMIN', permissions: [], allowed_locations: [], tier: 'T3' });
      });
      expect(result.current.isAuthenticated).toBe(true);

      await act(async () => {
        await result.current.logout();
      });

      expect(mocks.api.post).toHaveBeenCalledWith('/auth/logout', {});
      expect(result.current.user).toBeNull();
      expect(result.current.isAuthenticated).toBe(false);
    });
  });

  describe('tier propagation', () => {
    it('stores tier from /auth/users/me response', async () => {
      const mockUser = { username: 'op', role: 'OPERATOR', permissions: [], allowed_locations: [], tier: 'T2' };
      mocks.api.get.mockResolvedValue(mockUser);

      const { result } = renderHook(() => useAuth(), { wrapper });

      await waitFor(() => {
        expect(result.current.user?.tier).toBe('T2');
      });
    });

    it('defaults tier to T1 when absent from /auth/users/me response', async () => {
      // Response without tier field
      const mockUser = { username: 'op', role: 'OPERATOR', permissions: [], allowed_locations: [] };
      mocks.api.get.mockResolvedValue(mockUser);

      const { result } = renderHook(() => useAuth(), { wrapper });

      await waitFor(() => {
        expect(result.current.user).not.toBeNull();
      });
      expect(result.current.user?.tier ?? 'T1').toBe('T1');
    });
  });

  describe('session policy and cross-tab behavior', () => {
    it('clears local state for standard non-persistent sessions after inactivity without calling /auth/logout', async () => {
      vi.useFakeTimers();
      const mockUser = {
        ...baseUser,
        session_id: 'session-123',
        session_policy: { profile: 'standard', idle_timeout_minutes: 1, persistent: false },
      };
      mocks.api.get.mockResolvedValue(mockUser);
      mocks.api.post.mockResolvedValue({ status: 'success' });

      const { result } = renderHook(() => useAuth(), { wrapper });

      await act(async () => {
        await Promise.resolve();
      });

      expect(result.current.user).toEqual(mockUser);
      expect(mocks.api.post).not.toHaveBeenCalled();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(60_000);
      });

      // PR2: inactivity expiry is local-only; it MUST NOT call /auth/logout.
      expect(mocks.api.post).not.toHaveBeenCalledWith('/auth/logout', {}, expect.anything());
      expect(mocks.api.post).not.toHaveBeenCalledWith('/auth/logout', {}, expect.objectContaining({ skipAuthRefresh: true }));
      expect(result.current.user).toBeNull();
      expect(result.current.isAuthenticated).toBe(false);
    });

    it('shows the Spanish idle-expired toast for 15s when inactivity fires', async () => {
      vi.useFakeTimers();
      const mockUser = {
        ...baseUser,
        session_id: 'session-123',
        session_policy: { profile: 'standard', idle_timeout_minutes: 1, persistent: false },
      };
      mocks.api.get.mockResolvedValue(mockUser);
      mocks.api.post.mockResolvedValue({ status: 'success' });

      const { result } = renderHook(() => useAuth(), { wrapper });

      await act(async () => {
        await Promise.resolve();
      });

      expect(sonnerMocks.toast).not.toHaveBeenCalled();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(60_000);
      });

      expect(sonnerMocks.toast).toHaveBeenCalledWith(
        'Tu sesión expiró por inactividad. Volvé a iniciar sesión.',
        { duration: 15_000 },
      );
      expect(result.current.user).toBeNull();
    });

    it('defers the redirect to /login by ~30s after inactivity fires', async () => {
      vi.useFakeTimers();
      const mockUser = {
        ...baseUser,
        session_id: 'session-123',
        session_policy: { profile: 'standard', idle_timeout_minutes: 1, persistent: false },
      };
      mocks.api.get.mockResolvedValue(mockUser);
      mocks.api.post.mockResolvedValue({ status: 'success' });
      // Use a hash route so redirectToLoginOnce() takes the hash branch (no full nav in jsdom).
      window.location.hash = '#/dashboard';

      const { result } = renderHook(() => useAuth(), { wrapper });

      await act(async () => {
        await Promise.resolve();
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(60_000);
      });

      // Right after inactivity: user cleared, toast shown, but NOT redirected yet.
      expect(result.current.user).toBeNull();
      expect(sonnerMocks.toast).toHaveBeenCalled();
      expect(window.location.hash).toBe('#/dashboard');

      // Advance another 29s (still under the 30s threshold).
      await act(async () => {
        await vi.advanceTimersByTimeAsync(29_000);
      });
      expect(window.location.hash).toBe('#/dashboard');

      // Cross the 30s threshold → redirect fires.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2_000);
      });
      expect(window.location.hash).toBe('#/login');
    });

    it('does not arm inactivity logout for persistent operational sessions', async () => {
      const mockUser = {
        ...baseUser,
        username: 'operator',
        role: 'OPERATOR',
        tier: 'T2',
        session_policy: { profile: 'operational', idle_timeout_minutes: null, persistent: true },
      };
      mocks.api.get.mockResolvedValue(mockUser);

      const { result } = renderHook(() => useAuth(), { wrapper });

      await waitFor(() => {
        expect(result.current.isAuthenticated).toBe(true);
      });

      await act(async () => {
        await new Promise(resolve => setTimeout(resolve, 0));
      });

      expect(mocks.api.post).not.toHaveBeenCalledWith('/auth/logout', {}, expect.anything());
      expect(result.current.user).toEqual(mockUser);
    });

    it('clears local authentication when another tab broadcasts session expiration', async () => {
      const mockUser = { ...baseUser, role: 'ADMIN', tier: 'T3' };
      mocks.api.get.mockResolvedValue(mockUser);

      const { result } = renderHook(() => useAuth(), { wrapper });

      await waitFor(() => {
        expect(result.current.isAuthenticated).toBe(true);
      });

      act(() => {
        publishAuthSessionEvent({ type: 'session-expired', reason: 'idle_timeout' });
      });

      await waitFor(() => {
        expect(result.current.user).toBeNull();
        expect(result.current.isAuthenticated).toBe(false);
      });
    });

    it('ignores stale session events for a previous session id', async () => {
      const mockUser = { ...baseUser, session_id: 'current-session' };
      mocks.api.get.mockResolvedValue(mockUser);

      const { result } = renderHook(() => useAuth(), { wrapper });

      await waitFor(() => {
        expect(result.current.isAuthenticated).toBe(true);
      });

      act(() => {
        publishAuthSessionEvent({ type: 'session-expired', reason: 'idle_timeout', sessionId: 'previous-session' });
      });

      expect(result.current.user).toEqual(mockUser);
      expect(result.current.isAuthenticated).toBe(true);
    });
  });

  describe('hasPermission', () => {
    it('returns false when no user', () => {
      const { result } = renderHook(() => useAuth(), { wrapper });
      expect(result.current.hasPermission('ADMIN')).toBe(false);
    });

    it('returns true for ADMIN role regardless of permissions', () => {
      const { result } = renderHook(() => useAuth(), { wrapper });
      const adminUser = { username: 'admin', role: 'ADMIN', permissions: [], allowed_locations: [], tier: 'T3' };

      act(() => {
        result.current.login(adminUser);
      });

      expect(result.current.hasPermission('ANYTHING')).toBe(true);
      expect(result.current.hasPermission('USER_MANAGE')).toBe(true);
    });

    it('checks permissions array for non-admin users', () => {
      const { result } = renderHook(() => useAuth(), { wrapper });
      const viewerUser = {
        username: 'viewer',
        role: 'VIEWER',
        permissions: ['METRICS_VIEW'],
        allowed_locations: [],
        tier: 'T1',
      };

      act(() => {
        result.current.login(viewerUser);
      });

      expect(result.current.hasPermission('METRICS_VIEW')).toBe(true);
      expect(result.current.hasPermission('ADMIN')).toBe(false);
    });
  });
});
