import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import UserManager from './UserManager';

const mocks = vi.hoisted(() => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
  usePermissions: vi.fn(),
}));

vi.mock('../services/api', () => ({
  api: mocks.api,
}));

vi.mock('../services/permissions', () => ({
  usePermissions: mocks.usePermissions,
}));

vi.mock('../context/AuthContext', () => ({
  useAuth: vi.fn(() => ({ hasPermission: () => true })),
}));

// RoleManager is rendered in a tab we never activate — mock it to avoid its api calls
vi.mock('./RoleManager', () => ({ default: () => <div>Role Manager</div> }));

const ROLES = [
  { name: 'VIEWER', permissions: ['EVENT_VIEW'] },
  { name: 'AI_DIAGNOSTIC', permissions: ['AI_VIEW_ALL', 'AI_EVENT_ACK'] },
];

const USERS_HUMAN = [
  { username: 'alice', role: 'VIEWER', permissions: ['EVENT_VIEW'], allowed_locations: [] },
];

const USERS_AI = [
  { username: 'bot-diag', role: 'AI_DIAGNOSTIC', permissions: ['AI_VIEW_ALL'], allowed_locations: [] },
];

function setupDefaultMocks() {
  mocks.usePermissions.mockReturnValue({
    human: ['EVENT_VIEW', 'EVENT_ACK', 'CI_VIEW'],
    ai: ['AI_VIEW_ALL', 'AI_EVENT_ACK'],
    loading: false,
    error: null,
  });
}

describe('UserManager — AI features', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupDefaultMocks();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    vi.spyOn(window, 'alert').mockImplementation(() => undefined);
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
  });

  it('shows AI Permissions section when an AI role is selected', async () => {
    mocks.api.get.mockImplementation((endpoint: string) => {
      if (endpoint === '/roles/') return Promise.resolve(ROLES);
      if (endpoint === '/users/') return Promise.resolve(USERS_HUMAN);
      return Promise.resolve([]);
    });

    render(<UserManager />);

    // Wait for roles to load
    await waitFor(() => {
      expect(mocks.api.get).toHaveBeenCalledWith('/roles/');
    });

    // Select an AI role
    const roleSelect = await screen.findByRole('combobox');
    fireEvent.change(roleSelect, { target: { value: 'AI_DIAGNOSTIC' } });

    // Open the permissions panel
    const permsToggle = screen.getByText(/Specific Permissions/);
    fireEvent.click(permsToggle);

    expect(screen.getByText('AI Permissions')).toBeInTheDocument();
  });

  it('does NOT show AI Permissions section when a human role is selected', async () => {
    mocks.api.get.mockImplementation((endpoint: string) => {
      if (endpoint === '/roles/') return Promise.resolve(ROLES);
      if (endpoint === '/users/') return Promise.resolve(USERS_HUMAN);
      return Promise.resolve([]);
    });

    render(<UserManager />);

    await waitFor(() => {
      expect(mocks.api.get).toHaveBeenCalledWith('/roles/');
    });

    // VIEWER is the default role — open the permissions panel
    const permsToggle = await screen.findByText(/Specific Permissions/);
    fireEvent.click(permsToggle);

    expect(screen.queryByText('AI Permissions')).toBeNull();
  });

  it('shows AI badge next to an AI user in the user list', async () => {
    mocks.api.get.mockImplementation((endpoint: string) => {
      if (endpoint === '/roles/') return Promise.resolve(ROLES);
      if (endpoint === '/users/') return Promise.resolve(USERS_AI);
      return Promise.resolve([]);
    });

    render(<UserManager />);

    await waitFor(() => {
      expect(screen.getByText('bot-diag')).toBeInTheDocument();
    });

    expect(screen.getByText('AI')).toBeInTheDocument();
  });

  it('does NOT show AI badge for a human user in the user list', async () => {
    mocks.api.get.mockImplementation((endpoint: string) => {
      if (endpoint === '/roles/') return Promise.resolve(ROLES);
      if (endpoint === '/users/') return Promise.resolve(USERS_HUMAN);
      return Promise.resolve([]);
    });

    render(<UserManager />);

    await waitFor(() => {
      expect(screen.getByText('alice')).toBeInTheDocument();
    });

    expect(screen.queryByText('AI')).toBeNull();
  });

  it('shows service-account note when AI role is selected for a new user', async () => {
    mocks.api.get.mockImplementation((endpoint: string) => {
      if (endpoint === '/roles/') return Promise.resolve(ROLES);
      if (endpoint === '/users/') return Promise.resolve(USERS_HUMAN);
      return Promise.resolve([]);
    });

    render(<UserManager />);

    await waitFor(() => {
      expect(mocks.api.get).toHaveBeenCalledWith('/roles/');
    });

    const roleSelect = await screen.findByRole('combobox');
    fireEvent.change(roleSelect, { target: { value: 'AI_DIAGNOSTIC' } });

    expect(screen.getByText(/This is a service account/)).toBeInTheDocument();
  });

  it('shows AI badge for AI_OPERATOR users (not just AI_DIAGNOSTIC)', async () => {
    const USERS_OPERATOR = [
      { username: 'bot-op', role: 'AI_OPERATOR', permissions: ['AI_VIEW_ALL', 'AI_EVENT_CLOSE'], allowed_locations: [] },
    ];
    mocks.api.get.mockImplementation((endpoint: string) => {
      if (endpoint === '/roles/') return Promise.resolve(ROLES);
      if (endpoint === '/users/') return Promise.resolve(USERS_OPERATOR);
      return Promise.resolve([]);
    });

    render(<UserManager />);

    await waitFor(() => {
      expect(screen.getByText('bot-op')).toBeInTheDocument();
    });

    expect(screen.getByText('AI')).toBeInTheDocument();
  });
});
