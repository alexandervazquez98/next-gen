
import React, { useState, useEffect } from 'react';
import MetricsManager from './MetricsManager';
import CatalogManager from './CatalogManager';
import RelationshipManager from './RelationshipManager';
import CIEditor from './CIEditor';
import MassLinkEditor from './MassLinkEditor';
import { GraphNode } from '../types';
import { useAuth } from '../context/AuthContext';
import { api } from '../services/api';

/**
 * AdminPage Component
 * 
 * Central administration interface for managing:
 * - Metrics (Definitions)
 * - CI Catalog (Hardware models, categories, owners)
 * - Links (Relationships)
 * - CI Inventory (Advanced view)
 * - Mass Relationships (Rule-based linking)
 */
const AdminPage: React.FC = () => {
    type AdminTab = 'METRICS' | 'CATALOG' | 'LINKS' | 'INVENTORY' | 'MASS_LINKS';
    const [activeTab, setActiveTab] = useState<AdminTab>('METRICS');
    const [data, setData] = useState<any[]>([]);
    const [loading, setLoading] = useState(false);
    const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
    const [refreshKey, setRefreshKey] = useState(0);

    const { hasPermission } = useAuth();

    const fetchData = async () => {
        setLoading(true);
        
        const endpoint = activeTab === 'METRICS' ? '/metrics' 
            : activeTab === 'INVENTORY' ? '/nodes'
            : null;

        if (endpoint) {
            try {
                const json = await api.get<any[]>(endpoint);
                setData(Array.isArray(json) ? json : []);
            } catch (e) {
                console.error("Failed to fetch admin data", e);
                setData([]);
            }
        }
        setLoading(false);
    };

    useEffect(() => {
        fetchData();
    }, [activeTab, refreshKey]);

    const handleSaveNode = async (node: GraphNode) => {
        try {
            await api.post('/nodes', node);
            setSelectedNode(null);
            setRefreshKey(prev => prev + 1);
        } catch (e: any) {
            alert('Failed to save CI: ' + e.message);
        }
    };

    const handleDeleteNode = async (id: string) => {
        if (!confirm('Are you sure you want to delete this CI? This will remove all associated metrics and links.')) return;
        try {
            await api.delete(`/nodes/${id}`);
            setSelectedNode(null);
            setRefreshKey(prev => prev + 1);
        } catch (e: any) {
            alert('Failed to delete CI: ' + e.message);
        }
    };

    const fileInputRef = React.useRef<HTMLInputElement>(null);

    const handleDownloadTemplate = async () => {
        try {
            const blob = await api.get<Blob>('/nodes/template');
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'ci_import_template.xlsx';
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
        } catch (e: any) {
            console.error(e);
            alert('Failed to download template: ' + e.message);
        }
    };

    const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        if (!file) return;

        const formData = new FormData();
        formData.append('file', file);

        setLoading(true);
        try {
            const data: any = await api.request('/nodes/upload', {
                method: 'POST',
                body: formData
            });

            console.log('[Bulk Upload] Response:', data);

            let fullMessage = data.message || 'Upload completed';
            if (data.errors && Array.isArray(data.errors) && data.errors.length > 0) {
                fullMessage += `\n\nErrors found:\n- ${data.errors.join('\n- ')}`;
            }

            alert(fullMessage);
            fetchData();
        } catch (e: any) {
            console.error(e);
            const errorMsg = e.message && typeof e.message === 'object' 
                ? JSON.stringify(e.message) 
                : e.message || 'Unknown error';
            alert(`Upload failed: ${errorMsg}`);
        } finally {
            setLoading(false);
            if (fileInputRef.current) fileInputRef.current.value = '';
        }
    };

    return (
        <div className="flex flex-col h-screen bg-surface-950 overflow-hidden">
            {/* Admin Navigation Bar */}
            <div className="bg-neutral-900/50 backdrop-blur-xl border-b border-white/5 px-8 py-4 flex justify-between items-center">
                <div className="flex items-center gap-6">
                    <div>
                        <h1 className="text-xl font-black text-white tracking-tighter uppercase">Nexus Command</h1>
                        <p className="text-[10px] font-bold text-neutral-500 uppercase tracking-widest">System Administration</p>
                    </div>

                    <nav className="flex gap-1 ml-8">
                        {[
                            { id: 'METRICS', label: 'Metrics Def', icon: 'analytics' },
                            { id: 'CATALOG', label: 'Catalog', icon: 'inventory_2' },
                            { id: 'LINKS', label: 'Links', icon: 'link' },
                            { id: 'MASS_LINKS', label: 'Mass Links', icon: 'dynamic_feed' },
                            { id: 'INVENTORY', label: 'Inventory', icon: 'list_alt' }
                        ].map((tab) => (
                            <button
                                key={tab.id}
                                onClick={() => setActiveTab(tab.id as AdminTab)}
                                className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold transition-all ${
                                    activeTab === tab.id 
                                    ? 'bg-brand-500/10 text-brand-400 border border-brand-500/20 shadow-lg shadow-brand-500/5' 
                                    : 'text-neutral-500 hover:text-neutral-300 hover:bg-white/5 border border-transparent'
                                }`}
                            >
                                <span className="material-symbols-outlined text-sm">{tab.icon}</span>
                                {tab.label}
                            </button>
                        ))}
                    </nav>
                </div>

                <div className="flex items-center gap-4">
                    {loading && (
                        <div className="flex items-center gap-2 px-3 py-1 bg-brand-500/10 rounded-full border border-brand-500/20 animate-pulse">
                            <div className="w-1.5 h-1.5 bg-brand-400 rounded-full"></div>
                            <span className="text-[10px] font-black text-brand-400 uppercase tracking-widest">Syncing Hub...</span>
                        </div>
                    )}
                </div>
            </div>

            {/* Content Area */}
            <div className="flex-1 overflow-hidden relative">
                {/* Metrics Management */}
                {activeTab === 'METRICS' ? (
                    <MetricsManager />
                ) : null}

                {/* Catalog Management */}
                {activeTab === 'CATALOG' ? (
                    <CatalogManager />
                ) : null}

                {/* Links Management */}
                {activeTab === 'LINKS' ? (
                    <RelationshipManager />
                ) : null}

                {/* Mass Relationships Editor */}
                {activeTab === 'MASS_LINKS' ? (
                    <MassLinkEditor />
                ) : null}

                {/* Inventory Table */}
                {activeTab === 'INVENTORY' ? (
                    <div className="h-full flex flex-col p-8 space-y-6 overflow-hidden">
                        <div className="flex justify-between items-end">
                            <div>
                                <h2 className="text-3xl font-black text-white tracking-tighter uppercase italic">Inventory</h2>
                                <p className="text-neutral-500 text-sm font-medium tracking-tight">Managing technical assets and configuration state.</p>
                            </div>

                            <div className="flex items-center gap-3">
                                <div className="flex items-center gap-2 bg-neutral-900 border border-white/5 rounded-2xl p-1 shadow-2xl">
                                    <button
                                        onClick={handleDownloadTemplate}
                                        className="btn-secondary text-xs"
                                    >
                                        TEMPLATE
                                    </button>
                                    <div className="relative">
                                        <button className="btn-brand text-xs">
                                            BULK UPLOAD
                                        </button>
                                        <input
                                            ref={fileInputRef}
                                            type="file"
                                            accept=".xlsx"
                                            className="absolute inset-0 opacity-0 cursor-pointer"
                                            onChange={handleFileUpload}
                                        />
                                    </div>
                                </div>
                                <button 
                                    onClick={() => setSelectedNode({} as GraphNode)}
                                    className="px-6 py-2.5 bg-brand-600 hover:bg-brand-500 text-white rounded-2xl text-xs font-black transition-all shadow-xl shadow-brand-900/20 uppercase tracking-widest"
                                >
                                    New CI
                                </button>
                            </div>
                        </div>

                        <div className="flex-1 flex gap-8 overflow-hidden">
                            <div className="flex-1 bg-neutral-900/50 rounded-3xl border border-white/5 flex flex-col overflow-hidden shadow-2xl backdrop-blur-sm">
                                <div className="p-4 border-b border-white/5 bg-black/20 flex justify-between items-center">
                                    <span className="text-[10px] font-black text-neutral-500 uppercase tracking-[0.2em]">Active Assets</span>
                                    <div className="flex gap-4">
                                        <div className="flex items-center gap-2">
                                            <div className="w-2 h-2 rounded-full bg-green-500"></div>
                                            <span className="text-[10px] font-bold text-neutral-400 uppercase">Production: {data.length}</span>
                                        </div>
                                    </div>
                                </div>

                                <div className="flex-1 overflow-y-auto custom-scrollbar">
                                    <table className="w-full border-collapse">
                                        <thead>
                                            <tr className="text-left border-b border-white/5 sticky top-0 bg-neutral-900 z-10">
                                                <th className="p-4 text-[10px] font-black text-neutral-500 uppercase tracking-widest">CI Identity</th>
                                                <th className="p-4 text-[10px] font-black text-neutral-500 uppercase tracking-widest">Network Info</th>
                                                <th className="p-4 text-[10px] font-black text-neutral-500 uppercase tracking-widest">Layer / Model</th>
                                                <th className="p-4 text-[10px] font-black text-neutral-500 uppercase tracking-widest text-right">Actions</th>
                                            </tr>
                                        </thead>
                                        <tbody className="text-sm divide-y divide-white/5">
                                            {data.map((item: any) => (
                                                <tr key={item.id} className="group hover:bg-white/[0.02] transition-colors">
                                                    <td className="p-4">
                                                        <div className="flex flex-col">
                                                            <span className="font-black text-white tracking-tight">{item.label}</span>
                                                            <span className="text-[10px] text-neutral-500 font-mono uppercase">{item.id}</span>
                                                        </div>
                                                    </td>
                                                    <td className="p-4">
                                                        <div className="flex flex-col">
                                                            <span className="text-xs text-neutral-300 font-bold">{item.ip || 'No IP'}</span>
                                                            <span className="text-[10px] text-neutral-500 font-medium uppercase tracking-tighter">Status: {item.status}</span>
                                                        </div>
                                                    </td>
                                                    <td className="p-4">
                                                        <div className="flex items-center gap-2">
                                                            <span className="px-2 py-0.5 bg-neutral-800 text-neutral-400 rounded-md text-[10px] font-bold uppercase border border-white/5">
                                                                {item.type}
                                                            </span>
                                                            <span className="text-xs text-neutral-500">{item.brand} {item.model}</span>
                                                        </div>
                                                    </td>
                                                    <td className="p-4 text-right">
                                                        <button 
                                                            onClick={() => setSelectedNode(item)}
                                                            className="p-2 hover:bg-brand-500/10 hover:text-brand-400 text-neutral-600 rounded-xl transition-all"
                                                        >
                                                            <span className="material-symbols-outlined text-sm">edit_note</span>
                                                        </button>
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            </div>

                            {selectedNode && (
                                <div className="w-[450px] animate-in slide-in-from-right duration-500">
                                    <CIEditor
                                        node={selectedNode.id ? selectedNode : null}
                                        onSave={handleSaveNode}
                                        onDelete={handleDeleteNode}
                                        onClose={() => setSelectedNode(null)}
                                        className="h-full rounded-3xl border border-white/5 shadow-2xl overflow-hidden"
                                    />
                                </div>
                            )}
                        </div>
                    </div>
                ) : null}
            </div>
        </div>
    );
};

export default AdminPage;
