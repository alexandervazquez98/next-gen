import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import RoleManager from './RoleManager';

const mocks = vi.hoisted(() => ({
  useAuth: vi.fn(),
  usePermissions: vi.fn(),
  api: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock('../context/AuthContext', () => ({
  useAuth: mocks.useAuth,
}));

vi.mock('../services/api', () => ({
  api: mocks.api,
}));

vi.mock('../services/permissions', () => ({
  usePermissions: mocks.usePermissions,
}));

type Role = {
  name: string;
  description: string;
  permissions: string[];
  is_system: boolean;
};

const customRole: Role = {
  name: 'Operator',
  description: 'Handles incidents and diagnostics',
  permissions: ['EVENT_VIEW', 'EVENT_ACK', 'RUN_DIAGNOSTICS', 'AUDIT_VIEW'],
  is_system: false,
};

const systemRole: Role = {
  name: 'ADMIN',
  description: 'System administrator',
  permissions: ['ROLE_MANAGE', 'USER_MANAGE'],
  is_system: true,
};

const setAuth = (allowedPerms: string[] = ['ROLE_MANAGE']) => {
  mocks.useAuth.mockReturnValue({
    token: 'test-token',
    hasPermission: (perm: string) => allowedPerms.includes(perm),
  });
};

const AI_ROLE = {
  name: 'AI_DIAGNOSTIC',
  description: 'AI agent',
  permissions: ['AI_VIEW_ALL'],
  is_system: true,
};

describe('RoleManager', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setAuth();
    mocks.usePermissions.mockReturnValue({
      human: [
        'EVENT_VIEW', 'EVENT_ACK', 'EVENT_CLOSE', 'EVENT_FORCED_CLOSE',
        'CI_VIEW', 'CI_EDIT', 'CI_DELETE',
        'RUN_DIAGNOSTICS',
        'USER_MANAGE', 'ROLE_MANAGE', 'AUDIT_VIEW',
        'METRICS_VIEW',
      ],
      ai: ['AI_VIEW_ALL', 'AI_EVENT_ACK'],
      loading: false,
      error: null,
    });
    mocks.api.get.mockResolvedValue([]);
    mocks.api.post.mockResolvedValue(undefined);
    mocks.api.put.mockResolvedValue(undefined);
    mocks.api.delete.mockResolvedValue(undefined);
    vi.spyOn(window, 'alert').mockImplementation(() => undefined);
    vi.spyOn(window, 'confirm').mockImplementation(() => true);
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
  });

  it('renders access denied when the user lacks view/mutate permissions', () => {
    setAuth([]);

    render(<RoleManager />);

    expect(screen.getByText(/access denied\. required: user_manage or role_manage/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /new role/i })).not.toBeInTheDocument();
    expect(mocks.api.get).not.toHaveBeenCalled();
  });

  it('allows ADMIN permission without explicit ROLE_MANAGE permission', async () => {
    setAuth(['ADMIN']);
    mocks.api.get.mockResolvedValue([customRole]);

    render(<RoleManager />);

    expect(screen.getByRole('button', { name: /new role/i })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText('Operator')).toBeInTheDocument();
    });
  });

  it('allows USER_MANAGE-only users to view roles but not mutate', async () => {
    setAuth(['USER_MANAGE']);
    mocks.api.get.mockResolvedValue([customRole]);

    render(<RoleManager />);

    await waitFor(() => {
      expect(screen.getByText('Operator')).toBeInTheDocument();
    });

    expect(screen.queryByRole('button', { name: /new role/i })).not.toBeInTheDocument();
    expect(screen.queryByTitle('Edit')).not.toBeInTheDocument();
    expect(screen.queryByTitle('Delete')).not.toBeInTheDocument();
  });

  it('starts with no role cards while the fetch is still pending and then renders data', async () => {
    let resolveRoles: (roles: Role[]) => void = () => undefined;
    const pendingRoles = new Promise<Role[]>((resolve) => {
      resolveRoles = resolve;
    });
    mocks.api.get.mockReturnValue(pendingRoles);

    render(<RoleManager />);

    expect(screen.getByText(/available roles/i)).toBeInTheDocument();
    expect(screen.queryByText('Operator')).not.toBeInTheDocument();

    resolveRoles([customRole]);

    await waitFor(() => {
      expect(screen.getByText('Operator')).toBeInTheDocument();
    });
  });

  it('renders the fetched role list after loading completes', async () => {
    mocks.api.get.mockResolvedValue([customRole, systemRole]);

    render(<RoleManager />);

    await waitFor(() => {
      expect(screen.getByText('Operator')).toBeInTheDocument();
      expect(screen.getByText('ADMIN')).toBeInTheDocument();
      expect(screen.getByText(/handles incidents and diagnostics/i)).toBeInTheDocument();
      expect(screen.getByText('System')).toBeInTheDocument();
    });
  });

  it('keeps the list empty and logs when the initial fetch fails', async () => {
    const error = new Error('Roles fetch failed');
    mocks.api.get.mockRejectedValue(error);

    render(<RoleManager />);

    await waitFor(() => {
      expect(console.error).toHaveBeenCalledWith(error);
    });
    expect(screen.getByText(/available roles/i)).toBeInTheDocument();
    expect(screen.queryByText('Operator')).not.toBeInTheDocument();
  });

  it('renders an empty list when the API returns no roles', async () => {
    mocks.api.get.mockResolvedValue([]);

    render(<RoleManager />);

    await waitFor(() => {
      expect(mocks.api.get).toHaveBeenCalledWith('/roles/');
    });
    expect(screen.getByText(/available roles/i)).toBeInTheDocument();
    expect(screen.queryByTitle('Edit')).not.toBeInTheDocument();
    expect(screen.queryByTitle('Delete')).not.toBeInTheDocument();
  });

  it('shows create, edit, and delete actions for a user with mutate permissions', async () => {
    mocks.api.get.mockResolvedValue([customRole]);

    render(<RoleManager />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /new role/i })).toBeInTheDocument();
      expect(screen.getByTitle('Edit')).toBeInTheDocument();
      expect(screen.getByTitle('Delete')).toBeInTheDocument();
    });
  });

  it('does not render edit control for system roles', async () => {
    mocks.api.get.mockResolvedValue([systemRole]);

    render(<RoleManager />);

    await waitFor(() => {
      expect(screen.getByText('ADMIN')).toBeInTheDocument();
    });

    expect(screen.queryByTitle('Edit')).not.toBeInTheDocument();
    expect(screen.queryByTitle('Delete')).not.toBeInTheDocument();
  });

  it('creates a new role and reloads the list', async () => {
    mocks.api.get
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([customRole]);

    render(<RoleManager />);

    fireEvent.click(screen.getByRole('button', { name: /new role/i }));

    const inputs = screen.getAllByRole('textbox');
    fireEvent.change(inputs[0], { target: { value: 'Operator' } });
    fireEvent.change(inputs[1], { target: { value: 'Handles incidents and diagnostics' } });
    fireEvent.click(screen.getByLabelText('EVENT_VIEW'));
    fireEvent.click(screen.getByRole('button', { name: /save role/i }));

    await waitFor(() => {
      expect(mocks.api.post).toHaveBeenCalledWith('/roles/', {
        name: 'Operator',
        description: 'Handles incidents and diagnostics',
        permissions: ['EVENT_VIEW'],
      });
    });

    await waitFor(() => {
      expect(screen.getByText('Operator')).toBeInTheDocument();
    });
  });

  it('renders explicit permission catalog options in create/edit form', async () => {
    mocks.api.get.mockResolvedValue([]);

    render(<RoleManager />);

    fireEvent.click(screen.getByRole('button', { name: /new role/i }));

    expect(screen.getByLabelText('EVENT_FORCED_CLOSE')).toBeInTheDocument();
    expect(screen.getByLabelText('AUDIT_VIEW')).toBeInTheDocument();
    expect(screen.getByLabelText('METRICS_VIEW')).toBeInTheDocument();
  });

  it('allows selecting AUDIT_VIEW in role permissions and sends it in payload', async () => {
    mocks.api.get.mockResolvedValue([]);

    render(<RoleManager />);

    fireEvent.click(screen.getByRole('button', { name: /new role/i }));

    const inputs = screen.getAllByRole('textbox');
    fireEvent.change(inputs[0], { target: { value: 'Auditor' } });
    fireEvent.change(inputs[1], { target: { value: 'Read-only audit profile' } });
    fireEvent.click(screen.getByLabelText('AUDIT_VIEW'));

    fireEvent.click(screen.getByRole('button', { name: /save role/i }));

    await waitFor(() => {
      expect(mocks.api.post).toHaveBeenCalledWith('/roles/', {
        name: 'Auditor',
        description: 'Read-only audit profile',
        permissions: ['AUDIT_VIEW'],
      });
    });
  });

  it('edits an existing role and keeps the name immutable', async () => {
    mocks.api.get.mockResolvedValue([customRole]);

    render(<RoleManager />);

    await waitFor(() => {
      expect(screen.getByTitle('Edit')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTitle('Edit'));

    const inputs = screen.getAllByRole('textbox');
    expect(inputs[0]).toHaveValue('Operator');
    expect(inputs[0]).toBeDisabled();
    fireEvent.change(inputs[1], { target: { value: 'Updated operator description' } });
    fireEvent.click(screen.getByLabelText('EVENT_ACK'));
    fireEvent.click(screen.getByLabelText('RUN_DIAGNOSTICS'));
    fireEvent.click(screen.getByRole('button', { name: /save role/i }));

    await waitFor(() => {
      expect(mocks.api.put).toHaveBeenCalledWith('/roles/Operator', {
        description: 'Updated operator description',
        permissions: ['EVENT_VIEW', 'AUDIT_VIEW'],
      });
    });

    await waitFor(() => {
      expect(mocks.api.get).toHaveBeenCalledTimes(2);
    });
  });

  it('deletes a role after confirmation and reloads the list', async () => {
    mocks.api.get.mockResolvedValue([customRole]);

    render(<RoleManager />);

    await waitFor(() => {
      expect(screen.getByTitle('Delete')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTitle('Delete'));

    await waitFor(() => {
      expect(window.confirm).toHaveBeenCalledWith('Delete role Operator?');
      expect(mocks.api.delete).toHaveBeenCalledWith('/roles/Operator');
    });

    await waitFor(() => {
      expect(mocks.api.get).toHaveBeenCalledTimes(2);
    });
  });

  it('does not delete a role when confirmation is cancelled', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    mocks.api.get.mockResolvedValue([customRole]);

    render(<RoleManager />);

    await screen.findByText('Operator');

    fireEvent.click(screen.getByTitle('Delete'));

    expect(confirmSpy).toHaveBeenCalledWith('Delete role Operator?');
    expect(mocks.api.delete).not.toHaveBeenCalled();
  });

  it('alerts and stays on the form when creating a role fails', async () => {
    mocks.api.post.mockRejectedValue(new Error('Create failed'));

    render(<RoleManager />);

    fireEvent.click(screen.getByRole('button', { name: /new role/i }));
    const inputs = screen.getAllByRole('textbox');
    fireEvent.change(inputs[0], { target: { value: 'Auditor' } });
    fireEvent.click(screen.getByRole('button', { name: /save role/i }));

    await waitFor(() => {
      expect(window.alert).toHaveBeenCalledWith('Error: Create failed');
    });
    expect(screen.getByRole('heading', { name: /create role/i })).toBeInTheDocument();
  });

  it('alerts when updating a role fails', async () => {
    mocks.api.get.mockResolvedValue([customRole]);
    mocks.api.put.mockRejectedValue(new Error('Update failed'));

    render(<RoleManager />);

    await waitFor(() => {
      expect(screen.getByTitle('Edit')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTitle('Edit'));
    fireEvent.click(screen.getByRole('button', { name: /save role/i }));

    await waitFor(() => {
      expect(window.alert).toHaveBeenCalledWith('Error: Update failed');
    });
  });

  it('alerts when deleting a role fails', async () => {
    mocks.api.get.mockResolvedValue([customRole]);
    mocks.api.delete.mockRejectedValue(new Error('Delete failed'));

    render(<RoleManager />);

    await waitFor(() => {
      expect(screen.getByTitle('Delete')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTitle('Delete'));

    await waitFor(() => {
      expect(window.alert).toHaveBeenCalledWith('Delete failed');
    });
  });

  it('returns to the role list when cancelling the edit form', () => {
    render(<RoleManager />);

    fireEvent.click(screen.getByRole('button', { name: /new role/i }));
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));

    expect(screen.getByText(/available roles/i)).toBeInTheDocument();
    expect(mocks.api.post).not.toHaveBeenCalled();
  });

  describe('AI expand/collapse — role list cards', () => {
    // R-1: AI system role card must show expand toggle button
    it('R-1: shows AI Permissions expand toggle for AI system roles', async () => {
      mocks.api.get.mockResolvedValue([AI_ROLE]);

      render(<RoleManager />);

      await waitFor(() => {
        expect(screen.getByText('AI_DIAGNOSTIC')).toBeInTheDocument();
      });

      expect(
        screen.getByRole('button', { name: /toggle ai permissions for ai_diagnostic/i }),
      ).toBeInTheDocument();
    });

    // R-2: clicking the toggle reveals disabled checkboxes for each AI permission
    it('R-2: clicking expand toggle reveals disabled AI permission checkboxes', async () => {
      mocks.api.get.mockResolvedValue([AI_ROLE]);

      render(<RoleManager />);

      await waitFor(() => {
        expect(screen.getByText('AI_DIAGNOSTIC')).toBeInTheDocument();
      });

      const toggle = screen.getByRole('button', {
        name: /toggle ai permissions for ai_diagnostic/i,
      });
      fireEvent.click(toggle);

      // All checkboxes rendered must be disabled
      const checkboxes = screen.getAllByRole('checkbox');
      checkboxes.forEach(cb => expect(cb).toBeDisabled());

      // The mocked ai permission label is visible
      expect(screen.getByText('AI_VIEW_ALL')).toBeInTheDocument();
    });
  });
});
