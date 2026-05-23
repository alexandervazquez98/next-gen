import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { MemoryRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { AuthProvider, useAuth } from '../context/AuthContext';

// Mock react-router-dom's useNavigate for the api.ts import chain
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return {
    ...actual,
    useNavigate: () => vi.fn(),
  };
});

// Mock the api module - use vi.hoisted to avoid hoisting issues
const mocks = vi.hoisted(() => ({
  api: { get: vi.fn() },
}));
vi.mock('../services/api', () => ({
  api: mocks.api,
}));

// --- Replicate the ProtectedRoute logic from App.tsx for isolated testing ---
const ProtectedRoute = ({ children }: { children: React.ReactElement }) => {
  const { isAuthenticated, loading, user } = useAuth();
  const location = useLocation();

  if (loading) {
    return <span>Loading...</span>;
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  if (user?.force_password_change && location.pathname !== '/change-password') {
    return <Navigate to="/change-password" replace />;
  }

  return children;
};

describe('ProtectedRoute', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    mocks.api.get.mockReset();
    // Default: resolve with null user so hydration doesn't crash
    mocks.api.get.mockResolvedValue(null);
  });

  describe('unauthenticated access', () => {
    it('redirects to /login when no user', async () => {
      render(
        <MemoryRouter initialEntries={['/dashboard']}>
          <AuthProvider>
            <Routes>
              <Route path="/login" element={<span>Login Page</span>} />
              <Route path="/*" element={
                <ProtectedRoute>
                  <span>Protected Content</span>
                </ProtectedRoute>
              } />
            </Routes>
          </AuthProvider>
        </MemoryRouter>
      );

      // Initially shows Loading
      expect(screen.getByText('Loading...')).toBeInTheDocument();

      // After hydration resolves to null, redirects to login page
      await waitFor(() => {
        expect(screen.getByText('Login Page')).toBeInTheDocument();
      });
      expect(screen.queryByText('Protected Content')).not.toBeInTheDocument();
    });

    it('renders protected content when hydration succeeds', async () => {
      const mockUser = { username: 'admin', role: 'ADMIN', permissions: [], allowed_locations: [], tier: 'T3' };
      mocks.api.get.mockResolvedValue(mockUser);

      render(
        <MemoryRouter initialEntries={['/dashboard']}>
          <AuthProvider>
            <Routes>
              <Route path="/login" element={<span>Login Page</span>} />
              <Route path="/*" element={
                <ProtectedRoute>
                  <span>Protected Content</span>
                </ProtectedRoute>
              } />
            </Routes>
          </AuthProvider>
        </MemoryRouter>
      );

      // Initially shows Loading
      expect(screen.getByText('Loading...')).toBeInTheDocument();

      // Resolves to protected content once user is fetched
      await waitFor(() => {
        expect(screen.getByText('Protected Content')).toBeInTheDocument();
      });
      expect(screen.queryByText('Login Page')).not.toBeInTheDocument();
    });
  });

  describe('force password change', () => {
    it('redirects to /change-password when force_password_change is true', async () => {
      const TestLogin = () => {
        const { login } = useAuth();
        React.useEffect(() => {
          login({
            username: 'admin',
            role: 'USER',
            permissions: [],
            allowed_locations: [],
            force_password_change: true,
            tier: 'T1',
          });
        }, []);
        return null;
      };

      render(
        <MemoryRouter initialEntries={['/dashboard']}>
          <AuthProvider>
            <TestLogin />
            <Routes>
              <Route path="/change-password" element={<span>Change Password</span>} />
              <Route path="/dashboard" element={
                <ProtectedRoute>
                  <span>Dashboard</span>
                </ProtectedRoute>
              } />
            </Routes>
          </AuthProvider>
        </MemoryRouter>
      );

      await waitFor(() => {
        expect(screen.getByText('Change Password')).toBeInTheDocument();
      });
      expect(screen.queryByText('Dashboard')).not.toBeInTheDocument();
    });

    it('allows access to /change-password when force_password_change is true', async () => {
      const TestLogin = () => {
        const { login } = useAuth();
        React.useEffect(() => {
          login({
            username: 'admin',
            role: 'USER',
            permissions: [],
            allowed_locations: [],
            force_password_change: true,
            tier: 'T1',
          });
        }, []);
        return null;
      };

      render(
        <MemoryRouter initialEntries={['/change-password']}>
          <AuthProvider>
            <TestLogin />
            <Routes>
              <Route path="/change-password" element={
                <ProtectedRoute>
                  <span>Change Password</span>
                </ProtectedRoute>
              } />
              <Route path="/dashboard" element={<span>Dashboard</span>} />
              <Route path="/login" element={<span>Login Page</span>} />
            </Routes>
          </AuthProvider>
        </MemoryRouter>
      );

      await waitFor(() => {
        expect(screen.getByText('Change Password')).toBeInTheDocument();
      });
    });
  });
});
