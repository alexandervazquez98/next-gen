
import React, { useState } from 'react';
import { GraphNode, NodeType, SNMPConfig, MonitoringThresholds } from '../types';
import { api } from '../services/api';

interface CIEditorProps {
  node?: GraphNode | null;
  onSave: (node: GraphNode) => void;
  onDelete: (id: string) => void;
  onClose: () => void;
  className?: string;
}

/**
 * CIEditor Component
 * 
 * Side-panel form for creating and editing Configuration Items (CIs).
 * Handles:
 * - Basic CI Identification (Label, IP, Type)
 * - Hardware Selection from Catalog
 * - Location Data
 * - SNMP Configuration
 * - Ownership assignment
 */
const CIEditor: React.FC<CIEditorProps> = ({ node, onSave, onDelete, onClose, className }) => {
  const [categories, setCategories] = useState<{ name: string }[]>([]);
  const [owners, setOwners] = useState<{ name: string }[]>([]);
  const [hardwareModels, setHardwareModels] = useState<{ brand: string; model: string }[]>([]);

  React.useEffect(() => {
    const fetchData = async () => {
      try {
        const [cats, owns, hws] = await Promise.all([
          api.get<{ name: string }[]>('/categories'),
          api.get<{ name: string }[]>('/owners'),
          api.get<{ brand: string; model: string }[]>('/hardware')
        ]);
        
        setCategories(Array.isArray(cats) ? cats : []);
        setOwners(Array.isArray(owns) ? owns : []);
        setHardwareModels(Array.isArray(hws) ? hws : []);
      } catch (e) {
        console.error("Failed to load catalog for CIEditor", e);
      }
    };
    
    fetchData();
  }, []);

  const defaultState: Partial<GraphNode> = {
    id: `CI-${Math.random().toString(36).substr(2, 5)}`,
    label: '',
    type: 'INFRASTRUCTURE',
    status: 'ACTIVE',
    metadata: {},
    pollingInterval: 60,
    snmp: { version: 'v2c', readCommunity: 'public', writeCommunity: 'private', port: 161 },
    thresholds: { cpu: 80, memory: 85, latency: 100 }
  };

  const [formData, setFormData] = useState<Partial<GraphNode>>(node || defaultState);

  // Update formData if node prop changes (e.g. valid to null or diff node)
  React.useEffect(() => {
    if (node) {
      setFormData(node);
    } else {
      // Reset to default state if node is null (Switching to Create Mode)
      // We must ensure we generate a NEW ID, not keep the old one
      setFormData({
        ...defaultState,
        id: `CI-${Math.random().toString(36).substr(2, 5)}`
      });
    }
  }, [node]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await onSave(formData as GraphNode);
    // Reset form if creating new (no node prop)
    if (!node) {
      setFormData({
        ...defaultState,
        id: `CI-${Math.random().toString(36).substr(2, 5)}` // New ID
      });
    }
  };

  return (
    <div className={`flex flex-col h-full bg-surface-900 border-l border-white/10 ${className || 'w-[450px] shadow-2xl animate-in slide-in-from-right'}`}>
      <div className="p-6 border-b border-white/5 flex justify-between items-center bg-black/20">
        <h2 className="text-xl font-black text-white tracking-tighter uppercase">
          {node ? 'Edit Config Item' : 'Provision New CI'}
        </h2>
        <button onClick={onClose} className="text-neutral-500 hover:text-white transition-colors">
          <span className="material-symbols-outlined">close</span>
        </button>
      </div>

      <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto p-6 space-y-8 custom-scrollbar">
        {/* Basic Info */}
        <section className="space-y-4">
          <h3 className="text-[10px] font-black text-brand-400 uppercase tracking-[0.2em]">Identification</h3>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="text-xs text-neutral-500 font-bold mb-1 block uppercase">System ID (Auto)</span>
                <input
                  className="w-full bg-neutral-900/50 border border-white/5 rounded-lg px-4 py-2.5 text-xs font-mono text-neutral-400 cursor-not-allowed"
                  value={formData.id}
                  disabled
                />
              </label>
              <label className="block">
                <span className="text-xs text-neutral-500 font-bold mb-1 block uppercase">Common Name</span>
                <input
                  className="w-full bg-neutral-950 border border-white/5 rounded-lg px-4 py-2.5 text-sm focus:border-brand-500 outline-none transition-all"
                  value={formData.label}
                  onChange={e => setFormData({ ...formData, label: e.target.value })}
                  placeholder="e.g. CORE-ROUTER-01"
                  required
                />
              </label>
            </div>

            {/* Hardware Selection from Catalog */}
            <div className="grid grid-cols-2 gap-3">
              <label>
                <span className="text-xs text-neutral-500 font-bold mb-1 block uppercase">Brand</span>
                {hardwareModels.length > 0 ? (
                  <select
                    className="w-full bg-neutral-950 border border-white/5 rounded-lg px-4 py-2.5 text-sm focus:border-brand-500 outline-none"
                    value={formData.brand || ''}
                    onChange={e => setFormData({ ...formData, brand: e.target.value, model: '' })}
                  >
                    <option value="">Select Brand...</option>
                    {Array.from(new Set(hardwareModels.map(h => h.brand))).sort().map(b => (
                      <option key={b} value={b}>{b}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    className="w-full bg-neutral-950 border border-white/5 rounded-lg px-4 py-2.5 text-sm focus:border-brand-500 outline-none"
                    value={formData.brand || ''}
                    onChange={e => setFormData({ ...formData, brand: e.target.value })}
                    placeholder="e.g. Cisco"
                  />
                )}
              </label>
              <label>
                <span className="text-xs text-neutral-500 font-bold mb-1 block uppercase">Model</span>
                {hardwareModels.length > 0 && formData.brand ? (
                  <select
                    className="w-full bg-neutral-950 border border-white/5 rounded-lg px-4 py-2.5 text-sm focus:border-brand-500 outline-none"
                    value={formData.model || ''}
                    onChange={e => setFormData({ ...formData, model: e.target.value })}
                  >
                    <option value="">Select Model...</option>
                    {hardwareModels
                      .filter(h => h.brand === formData.brand)
                      .map(h => (
                        <option key={h.model} value={h.model}>{h.model}</option>
                      ))}
                  </select>
                ) : (
                  <input
                    className="w-full bg-neutral-950 border border-white/5 rounded-lg px-4 py-2.5 text-sm focus:border-brand-500 outline-none"
                    value={formData.model || ''}
                    onChange={e => setFormData({ ...formData, model: e.target.value })}
                    placeholder="e.g. Catalyst 9300"
                  />
                )}
              </label>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <label>
                <span className="text-xs text-neutral-500 font-bold mb-1 block uppercase">Serial Number</span>
                <input
                  className="w-full bg-neutral-950 border border-white/5 rounded-lg px-4 py-2.5 text-sm focus:border-brand-500 outline-none font-mono"
                  value={formData.serialNumber || ''}
                  onChange={e => setFormData({ ...formData, serialNumber: e.target.value })}
                  placeholder="e.g. SN12345678"
                />
              </label>
              <label>
                <span className="text-xs text-neutral-500 font-bold mb-1 block uppercase">Firmware Version</span>
                <input
                  className="w-full bg-neutral-950 border border-white/5 rounded-lg px-4 py-2.5 text-sm focus:border-brand-500 outline-none font-mono"
                  value={formData.firmwareVersion || ''}
                  onChange={e => setFormData({ ...formData, firmwareVersion: e.target.value })}
                  placeholder="e.g. 17.3.1"
                />
              </label>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <label>
                <span className="text-xs text-neutral-500 font-bold mb-1 block uppercase">IP Address</span>
                <input
                  className="w-full bg-neutral-950 border border-white/5 rounded-lg px-4 py-2.5 text-sm focus:border-brand-500 outline-none"
                  value={formData.ip || ''}
                  onChange={e => setFormData({ ...formData, ip: e.target.value })}
                  placeholder="192.168.x.x"
                />
              </label>
              <label>
                <span className="text-xs text-neutral-500 font-bold mb-1 block uppercase">Owner Group</span>
                <select
                  className="w-full bg-neutral-950 border border-white/5 rounded-lg px-4 py-2.5 text-sm focus:border-brand-500 outline-none"
                  value={formData.owner || ''}
                  onChange={e => setFormData({ ...formData, owner: e.target.value })}
                >
                  <option value="">Select Group...</option>
                  {owners.map(o => <option key={o.name} value={o.name}>{o.name}</option>)}
                </select>
              </label>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <label>
                <span className="text-xs text-neutral-500 font-bold mb-1 block uppercase">Network Layer</span>
                <select
                  className="w-full bg-neutral-950 border border-white/5 rounded-lg px-4 py-2.5 text-sm focus:border-brand-500 outline-none"
                  value={formData.type}
                  onChange={e => setFormData({ ...formData, type: e.target.value as NodeType })}
                >
                  <option value="INFRASTRUCTURE">INFRASTRUCTURE (Default)</option>
                  {categories.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
                </select>
              </label>
              <label>
                <span className="text-xs text-neutral-500 font-bold mb-1 block uppercase">Op Status</span>
                <select
                  className="w-full bg-neutral-950 border border-white/5 rounded-lg px-4 py-2.5 text-sm focus:border-brand-500 outline-none"
                  value={formData.status}
                  onChange={e => setFormData({ ...formData, status: e.target.value as any })}
                >
                  <option value="ACTIVE">Active</option>
                  <option value="EXCEPTION">Exception</option>
                  <option value="MAINTENANCE">Maintenance</option>
                </select>
              </label>
            </div>

            <label className="block">
              <span className="text-xs text-neutral-500 font-bold mb-1 block uppercase">Location Name</span>
              <input
                className="w-full bg-neutral-950 border border-white/5 rounded-lg px-4 py-2.5 text-sm focus:border-brand-500 outline-none"
                value={formData.location_name || ''}
                onChange={e => setFormData({ ...formData, location_name: e.target.value })}
                placeholder="e.g. Data Center North"
              />
            </label>

            <div className="grid grid-cols-2 gap-3">
              <label>
                <span className="text-xs text-neutral-500 font-bold mb-1 block uppercase">Latitude</span>
                <input
                  type="number" step="any"
                  className="w-full bg-neutral-950 border border-white/5 rounded-lg px-4 py-2.5 text-sm focus:border-brand-500 outline-none"
                  value={formData.location?.lat || ''}
                  onChange={e => setFormData({ ...formData, location: { ...formData.location, lat: parseFloat(e.target.value) } as any })}
                  placeholder="0.00"
                />
              </label>
              <label>
                <span className="text-xs text-neutral-500 font-bold mb-1 block uppercase">Longitude</span>
                <input
                  type="number" step="any"
                  className="w-full bg-neutral-950 border border-white/5 rounded-lg px-4 py-2.5 text-sm focus:border-brand-500 outline-none"
                  value={formData.location?.long || ''}
                  onChange={e => setFormData({ ...formData, location: { ...(formData.location as any), long: parseFloat(e.target.value) } })}
                  placeholder="0.00"
                />
              </label>
            </div>

          </div>
        </section>

        {/* SNMP Config */}
        <section className="space-y-4 bg-black/20 p-4 rounded-2xl border border-white/5">
          <h3 className="text-[10px] font-black text-accent-cyan uppercase tracking-[0.2em] flex items-center gap-2">
            <span className="material-symbols-outlined text-sm">settings_remote</span> SNMP Agent Config
          </h3>
          <div className="grid grid-cols-2 gap-3">
            <label className="col-span-1">
              <span className="text-xs text-neutral-500 font-bold mb-1 block uppercase">Version</span>
              <select
                className="w-full bg-neutral-900 border border-white/5 rounded-lg px-3 py-2 text-xs"
                value={formData.snmp?.version}
                onChange={e => setFormData({ ...formData, snmp: { ...formData.snmp!, version: e.target.value as any } })}
              >
                <option value="v2c">v2c (Community)</option>
                <option value="v3">v3 (Auth/Priv)</option>
              </select>
            </label>
            <label className="col-span-1">
              <span className="text-xs text-neutral-500 font-bold mb-1 block uppercase">Port</span>
              <input
                type="number"
                className="w-full bg-neutral-900 border border-white/5 rounded-lg px-3 py-2 text-xs"
                value={formData.snmp?.port}
                onChange={e => setFormData({ ...formData, snmp: { ...formData.snmp!, port: parseInt(e.target.value) } })}
              />
            </label>
            {formData.snmp?.version === 'v2c' ? (
              <>
                <label className="col-span-1">
                  <span className="text-xs text-neutral-500 font-bold mb-1 block uppercase">Read Community</span>
                  <input
                    type="text"
                    className="w-full bg-neutral-900 border border-white/5 rounded-lg px-3 py-2 text-xs"
                    value={formData.snmp?.readCommunity || ''}
                    onChange={e => setFormData({ ...formData, snmp: { ...formData.snmp!, readCommunity: e.target.value } })}
                    placeholder="public"
                  />
                </label>
                <label className="col-span-1">
                  <span className="text-xs text-neutral-500 font-bold mb-1 block uppercase">Write Community</span>
                  <input
                    type="text"
                    className="w-full bg-neutral-900 border border-white/5 rounded-lg px-3 py-2 text-xs"
                    value={formData.snmp?.writeCommunity || ''}
                    onChange={e => setFormData({ ...formData, snmp: { ...formData.snmp!, writeCommunity: e.target.value } })}
                    placeholder="private"
                  />
                </label>
              </>
            ) : (
              <label className="col-span-2">
                <span className="text-xs text-neutral-500 font-bold mb-1 block uppercase">Security Name (AuthKey)</span>
                <input
                  type="password"
                  className="w-full bg-neutral-900 border border-white/5 rounded-lg px-3 py-2 text-xs"
                  value={formData.snmp?.authKey || ''}
                  onChange={e => setFormData({ ...formData, snmp: { ...formData.snmp!, authKey: e.target.value } })}
                />
              </label>
            )}
            <label className="col-span-2">
              <span className="text-xs text-neutral-500 font-bold mb-1 block uppercase">Polling Interval (seconds)</span>
              <input
                type="number"
                min={10}
                className="w-full bg-neutral-900 border border-white/5 rounded-lg px-3 py-2 text-xs"
                value={formData.pollingInterval ?? 60}
                onChange={e => setFormData({ ...formData, pollingInterval: parseInt(e.target.value) || 60 })}
                placeholder="60"
              />
            </label>
          </div>
        </section>
      </form>

      <div className="p-6 border-t border-white/5 bg-black/40 flex gap-3">
        {node && (
          <button
            type="button"
            onClick={() => onDelete(node.id)}
            className="flex-1 px-4 py-3 bg-red-500/10 hover:bg-red-500/20 text-red-500 rounded-xl text-xs font-black transition-all border border-red-500/20"
          >
            DELETE CI
          </button>
        )}
        <button
          onClick={handleSubmit}
          className="flex-[2] px-4 py-3 bg-brand-600 hover:bg-brand-500 text-white rounded-xl text-xs font-black transition-all shadow-lg shadow-brand-900/20"
        >
          {node ? 'UPDATE CONFIG' : 'COMMIT TO CMDB'}
        </button>
      </div>
    </div>
  );
};

export default CIEditor;
