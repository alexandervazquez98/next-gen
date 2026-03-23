/**
 * AgentManager.smoke.test.tsx
 *
 * Smoke & static-analysis tests for the AgentManager component.
 *
 * Verifies:
 *  1. The component mounts without throwing.
 *  2. The "Antigravity Agents" heading is visible.
 *  3. An empty-state message is shown when the API returns no agents.
 *  4. The registration hint is rendered in the footer.
 *  5. The source file imports the Agent type from types.ts (static check).
 *  6. agent_token is never rendered to the DOM (security check).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock('../../services/api', () => ({
  api: {
    get: vi.fn().mockResolvedValue([]),
    delete: vi.fn().mockResolvedValue({ deleted: 'some-id' }),
  },
}));

vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({
    hasPermission: (_: string) => true,
    user: { username: 'admin', role: 'ADMIN' },
    isAuthenticated: true,
    token: 'test-token',
    logout: vi.fn(),
  }),
}));

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('AgentManager smoke tests', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('GIVEN the component WHEN rendered THEN mounts without throwing', async () => {
    const { default: AgentManager } = await import('../AgentManager');
    expect(() => render(<AgentManager />)).not.toThrow();
  });

  it('GIVEN the component WHEN rendered THEN shows Antigravity Agents heading', async () => {
    const { default: AgentManager } = await import('../AgentManager');
    render(<AgentManager />);
    expect(screen.getByText('Antigravity Agents')).toBeDefined();
  });

  it('GIVEN the API returns an empty list WHEN rendered THEN shows empty-state message', async () => {
    const { api } = await import('../../services/api');
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]);

    const { default: AgentManager } = await import('../AgentManager');
    render(<AgentManager />);

    await waitFor(() => {
      expect(screen.getByText('No agents registered yet.')).toBeDefined();
    });
  });

  it('GIVEN the component WHEN rendered THEN shows registration hint in footer', async () => {
    const { default: AgentManager } = await import('../AgentManager');
    render(<AgentManager />);

    // The footer contains the registration endpoint hint
    expect(screen.getByText(/POST \/api\/agents\/register/)).toBeDefined();
  });

  it('GIVEN the component source WHEN inspected THEN imports Agent type from types', async () => {
    const fs = await import('fs');
    const path = await import('path');
    const filePath = path.resolve(process.cwd(), 'components/AgentManager.tsx');
    const source = fs.readFileSync(filePath, 'utf-8');

    expect(source).toContain("import { Agent } from '../types'");
  });

  it('GIVEN agents returned by API WHEN rendered THEN agent_token is never exposed in DOM', async () => {
    const { api } = await import('../../services/api');
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      {
        id: 'abc-123',
        hostname: 'prod-server-01',
        ip: '10.0.0.1',
        os: 'Linux',
        version: '1.0.0',
        status: 'ONLINE',
        registered_at: new Date().toISOString(),
        last_seen: new Date().toISOString(),
        agent_token: 'super-secret-token-must-not-appear',
        ci_id: null,
        ci_label: null,
      },
    ]);

    const { default: AgentManager } = await import('../AgentManager');
    const { container } = render(<AgentManager />);

    await waitFor(() => {
      expect(screen.getByText('prod-server-01')).toBeDefined();
    });

    expect(container.innerHTML).not.toContain('super-secret-token-must-not-appear');
  });

  it('GIVEN agents returned by API WHEN rendered THEN hostname and status are visible', async () => {
    const { api } = await import('../../services/api');
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      {
        id: 'abc-123',
        hostname: 'edge-router-01',
        ip: '192.168.1.1',
        os: 'FRR/Linux',
        version: '2.3.1',
        status: 'ONLINE',
        registered_at: new Date().toISOString(),
        last_seen: new Date().toISOString(),
        ci_id: null,
        ci_label: null,
      },
    ]);

    const { default: AgentManager } = await import('../AgentManager');
    render(<AgentManager />);

    await waitFor(() => {
      expect(screen.getByText('edge-router-01')).toBeDefined();
      expect(screen.getByText('ONLINE')).toBeDefined();
    });
  });
});
