import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import React from 'react';
import { AuthProvider, useAuth } from '../context/AuthContext';

// Mock react-router-dom for the api.ts import chain
vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
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

describe('AuthContext', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    mocks.api.get.mockReset();
    mocks.api.post.mockReset();
    // Default: resolve with null user so hydration doesn't crash
    mocks.api.get.mockResolvedValue(null);
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
