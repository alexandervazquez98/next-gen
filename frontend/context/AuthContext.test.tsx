import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act, render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { AuthProvider, useAuth } from '../context/AuthContext';

// Mock react-router-dom for the api.ts import chain
vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
}));

// Mock the api module - use vi.hoisted to avoid hoisting issues
const mocks = vi.hoisted(() => ({
  api: { get: vi.fn() },
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
    // Default: resolve with null user so hydration doesn't crash
    mocks.api.get.mockResolvedValue(null);
  });

  describe('initial state', () => {
    it('starts unauthenticated with no user or token', () => {
      const { result } = renderHook(() => useAuth(), { wrapper });
      expect(result.current.isAuthenticated).toBe(false);
      expect(result.current.user).toBeNull();
      expect(result.current.token).toBeNull();
    });

    it('reads token from localStorage on mount', () => {
      localStorage.setItem('token', 'stored-token');
      const { result } = renderHook(() => useAuth(), { wrapper });
      expect(result.current.token).toBe('stored-token');
    });
  });

  describe('token hydration', () => {
    it('fetches user from /auth/users/me when token exists', async () => {
      localStorage.setItem('token', 'valid-token');
      const mockUser = { username: 'admin', role: 'ADMIN', permissions: [], allowed_locations: [] };
      mocks.api.get.mockResolvedValue(mockUser);

      const { result } = renderHook(() => useAuth(), { wrapper });

      expect(mocks.api.get).toHaveBeenCalledWith('/auth/users/me');
      await waitFor(() => {
        expect(result.current.user).toEqual(mockUser);
      });
    });

    it('logs out if user fetch fails (invalid token)', async () => {
      localStorage.setItem('token', 'expired-token');
      mocks.api.get.mockRejectedValue(new Error('Unauthorized'));

      const { result } = renderHook(() => useAuth(), { wrapper });

      await waitFor(() => {
        expect(result.current.user).toBeNull();
        expect(result.current.token).toBeNull();
      });
      expect(localStorage.getItem('token')).toBeNull();
    });
  });

  describe('login', () => {
    it('stores token and user in state and localStorage', () => {
      const { result } = renderHook(() => useAuth(), { wrapper });
      const user = { username: 'admin', role: 'ADMIN', permissions: [], allowed_locations: [] };

      act(() => {
        result.current.login('new-token', user);
      });

      expect(result.current.token).toBe('new-token');
      expect(result.current.user).toEqual(user);
      expect(result.current.isAuthenticated).toBe(true);
      expect(localStorage.getItem('token')).toBe('new-token');
    });
  });

  describe('logout', () => {
    it('clears token, user, and localStorage', () => {
      const { result } = renderHook(() => useAuth(), { wrapper });

      act(() => {
        result.current.login('token', { username: 'admin', role: 'ADMIN', permissions: [], allowed_locations: [] });
      });
      expect(result.current.isAuthenticated).toBe(true);

      act(() => {
        result.current.logout();
      });

      expect(result.current.token).toBeNull();
      expect(result.current.user).toBeNull();
      expect(result.current.isAuthenticated).toBe(false);
      expect(localStorage.getItem('token')).toBeNull();
    });
  });

  describe('hasPermission', () => {
    it('returns false when no user', () => {
      const { result } = renderHook(() => useAuth(), { wrapper });
      expect(result.current.hasPermission('ADMIN')).toBe(false);
    });

    it('returns true for ADMIN role regardless of permissions', () => {
      const { result } = renderHook(() => useAuth(), { wrapper });
      const adminUser = { username: 'admin', role: 'ADMIN', permissions: [], allowed_locations: [] };

      act(() => {
        result.current.login('t', adminUser);
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
      };

      act(() => {
        result.current.login('t', viewerUser);
      });

      expect(result.current.hasPermission('METRICS_VIEW')).toBe(true);
      expect(result.current.hasPermission('ADMIN')).toBe(false);
    });
  });
});
