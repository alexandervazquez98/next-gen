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
  const { isAuthenticated, token, user } = useAuth();
  const location = useLocation();

  if (!isAuthenticated && !token) {
    return <Navigate to="/login" replace />;
  }

  if (user?.force_password_change && location.pathname !== '/change-password') {
    return <Navigate to="/change-password" replace />;
  }

  return children;
};

// Helper to capture current location
const LocationSpy = () => {
  const location = useLocation();
  return <span data-testid="location">{location.pathname}</span>;
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
    it('redirects to /login when no token and no user', async () => {
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

      await waitFor(() => {
        expect(screen.getByText('Login Page')).toBeInTheDocument();
      });
      expect(screen.queryByText('Protected Content')).not.toBeInTheDocument();
    });

    it('renders protected content when token exists (even without user yet)', async () => {
      localStorage.setItem('token', 'some-token');

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

      // With a token in localStorage, ProtectedRoute should render children
      // (the user may still be loading from the hydration effect)
      expect(screen.getByText('Protected Content')).toBeInTheDocument();
      expect(screen.queryByText('Login Page')).not.toBeInTheDocument();
    });
  });

  describe('force password change', () => {
    it('redirects to /change-password when force_password_change is true', async () => {
      // Setup: login with a user that has force_password_change
      const TestLogin = () => {
        const { login } = useAuth();
        React.useEffect(() => {
          login('token', {
            username: 'admin',
            role: 'USER',
            permissions: [],
            allowed_locations: [],
            force_password_change: true,
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
      // Pre-set token so ProtectedRoute doesn't immediately redirect to /login
      localStorage.setItem('token', 'token');

      const TestLogin = () => {
        const { login } = useAuth();
        React.useEffect(() => {
          login('token', {
            username: 'admin',
            role: 'USER',
            permissions: [],
            allowed_locations: [],
            force_password_change: true,
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
