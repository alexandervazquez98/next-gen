import React, { useEffect, useState, useCallback } from 'react';
import { api } from '../services/api';
import { Agent } from '../types';
import { useAuth } from '../context/AuthContext';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function statusBadge(status: Agent['status']) {
  const map: Record<Agent['status'], string> = {
    ONLINE:   'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
    OFFLINE:  'bg-red-500/20 text-red-400 border-red-500/30',
    DEGRADED: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  };
  return map[status] ?? map.OFFLINE;
}

function formatRelative(iso?: string): string {
  if (!iso) return '—';
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1)  return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24)  return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const AgentManager: React.FC = () => {
  const { hasPermission } = useAuth();
  const [agents, setAgents]     = useState<Agent[]>([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);

  const fetchAgents = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<Agent[]>('/agents');
      setAgents(Array.isArray(data) ? data : []);
    } catch (err: any) {
      setError(err.message ?? 'Failed to load agents');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchAgents(); }, [fetchAgents]);

  const handleDelete = async (id: string) => {
    if (!window.confirm('Deregister this agent? The node will be permanently removed.')) return;
    setDeleting(id);
    try {
      await api.delete(`/agents/${id}`);
      setAgents(prev => prev.filter(a => a.id !== id));
    } catch (err: any) {
      setError(err.message ?? 'Delete failed');
    } finally {
      setDeleting(null);
    }
  };

  const canDelete = hasPermission('ADMIN') || hasPermission('CI_DELETE');

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  return (
    <div className="flex flex-col h-full bg-surface-950 text-neutral-200 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-8 py-5 border-b border-white/5">
        <div className="flex items-center gap-3">
          <span className="material-symbols-outlined text-accent-cyan text-2xl">smart_toy</span>
          <div>
            <h2 className="text-lg font-black uppercase tracking-widest text-white">
              Antigravity Agents
            </h2>
            <p className="text-[11px] text-neutral-500">
              Remote agents registered on the platform
            </p>
          </div>
        </div>
        <button
          onClick={fetchAgents}
          disabled={loading}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold border border-white/10 text-neutral-400 hover:text-white hover:border-white/20 transition-all disabled:opacity-40"
        >
          <span className={`material-symbols-outlined text-sm ${loading ? 'animate-spin' : ''}`}>
            refresh
          </span>
          Refresh
        </button>
      </div>

      {/* Error banner */}
      {error && (
        <div className="mx-8 mt-4 px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/30 text-red-400 text-sm flex items-center gap-2">
          <span className="material-symbols-outlined text-base">error</span>
          {error}
        </div>
      )}

      {/* Table */}
      <div className="flex-1 overflow-auto px-8 py-4">
        {loading && agents.length === 0 ? (
          <div className="flex items-center justify-center h-40 text-neutral-500 text-sm">
            <span className="material-symbols-outlined animate-spin mr-2">progress_activity</span>
            Loading agents…
          </div>
        ) : agents.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-40 gap-3 text-neutral-600">
            <span className="material-symbols-outlined text-5xl">smart_toy</span>
            <p className="text-sm">No agents registered yet.</p>
            <p className="text-xs text-neutral-700">
              Agents self-register via{' '}
              <code className="bg-neutral-800 px-1 rounded text-accent-cyan">
                POST /api/agents/register
              </code>
            </p>
          </div>
        ) : (
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="text-[10px] uppercase tracking-widest text-neutral-500 border-b border-white/5">
                <th className="text-left pb-3 pr-4">Hostname</th>
                <th className="text-left pb-3 pr-4">IP</th>
                <th className="text-left pb-3 pr-4">OS / Version</th>
                <th className="text-left pb-3 pr-4">Status</th>
                <th className="text-left pb-3 pr-4">CI</th>
                <th className="text-left pb-3 pr-4">Last Seen</th>
                <th className="text-left pb-3 pr-4">Registered</th>
                {canDelete && <th className="pb-3" />}
              </tr>
            </thead>
            <tbody>
              {agents.map(agent => (
                <tr
                  key={agent.id}
                  className="border-b border-white/5 hover:bg-white/[0.02] transition-colors"
                >
                  <td className="py-3 pr-4 font-mono text-white">{agent.hostname}</td>
                  <td className="py-3 pr-4 text-neutral-400">{agent.ip ?? '—'}</td>
                  <td className="py-3 pr-4 text-neutral-400">
                    {agent.os ? (
                      <span>
                        {agent.os}
                        {agent.version && (
                          <span className="text-neutral-600"> v{agent.version}</span>
                        )}
                      </span>
                    ) : '—'}
                  </td>
                  <td className="py-3 pr-4">
                    <span
                      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold border ${statusBadge(agent.status)}`}
                    >
                      <span className={`w-1.5 h-1.5 rounded-full ${
                        agent.status === 'ONLINE'   ? 'bg-emerald-400' :
                        agent.status === 'DEGRADED' ? 'bg-yellow-400'  : 'bg-red-400'
                      }`} />
                      {agent.status}
                    </span>
                  </td>
                  <td className="py-3 pr-4 text-neutral-400 text-xs">
                    {agent.ci_label ? (
                      <span className="bg-brand-600/20 text-brand-400 px-2 py-0.5 rounded text-[10px]">
                        {agent.ci_label}
                      </span>
                    ) : '—'}
                  </td>
                  <td className="py-3 pr-4 text-neutral-500 text-xs">
                    {formatRelative(agent.last_seen)}
                  </td>
                  <td className="py-3 pr-4 text-neutral-600 text-xs">
                    {agent.registered_at
                      ? new Date(agent.registered_at).toLocaleDateString()
                      : '—'}
                  </td>
                  {canDelete && (
                    <td className="py-3">
                      <button
                        onClick={() => handleDelete(agent.id)}
                        disabled={deleting === agent.id}
                        className="p-1.5 rounded-lg text-neutral-600 hover:text-red-400 hover:bg-red-500/10 transition-all disabled:opacity-30"
                        title="Deregister agent"
                      >
                        <span className="material-symbols-outlined text-base">
                          {deleting === agent.id ? 'progress_activity' : 'delete'}
                        </span>
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Footer — registration hint */}
      <div className="px-8 py-4 border-t border-white/5 flex items-center gap-2 text-[11px] text-neutral-600">
        <span className="material-symbols-outlined text-sm">info</span>
        Agents self-register by calling{' '}
        <code className="bg-neutral-900 border border-white/5 px-1.5 py-0.5 rounded text-accent-cyan">
          POST /api/agents/register
        </code>
        . Subsequent calls require the{' '}
        <code className="bg-neutral-900 border border-white/5 px-1.5 py-0.5 rounded text-accent-cyan">
          X-Agent-Token
        </code>{' '}
        header.
      </div>
    </div>
  );
};

export default AgentManager;
