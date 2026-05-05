
import React, { useState, useEffect } from 'react';
import MetricsManager from './MetricsManager';
import CIEditor from './CIEditor';
import RelationshipManager from './RelationshipManager';
import CatalogManager from './CatalogManager';
import { GraphNode } from '../types';
import { useAuth } from '../context/AuthContext';
import { api } from '../services/api';

/**
 * AdminPage Component
 * 
 * Central administration interface for managing:
 * - Metrics (Definitions)
 * - Catalog (Hardware, Categories, Owners)
 * - Relationships (Links)
 * - CI Inventory (Advanced view)
 */
const AdminPage: React.FC = () => {
    const { hasPermission } = useAuth();
    type AdminTab = 'METRICS' | 'CATALOG' | 'LINKS' | 'INVENTORY';
    const [activeTab, setActiveTab] = useState<AdminTab>('METRICS');

    const [data, setData] = useState<any[]>([]);
    const [loading, setLoading] = useState(false);

    // Form States
    const [newItem, setNewItem] = useState<any>({});
    const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
    const [refreshKey, setRefreshKey] = useState(0);

    useEffect(() => {
        fetchData();
    }, [activeTab]);

    const fetchData = async () => {
        setLoading(true);
        try {
            const endpoint = activeTab === 'METRICS' ? '/metrics'
                : activeTab === 'INVENTORY' ? '/nodes'
                    : null;

            if (endpoint) {
                const json = await api.get<any[]>(endpoint);
                setData(Array.isArray(json) ? json : []);
            }
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    }

    const handleCreate = async () => {
        let endpoint = '';
        let body = {};

        if (activeTab === 'METRICS') {
            endpoint = '/metrics';
            body = {
                id: newItem.id,
                protocol: newItem.protocol || 'SNMP',
                warning: parseFloat(newItem.warning),
                critical: parseFloat(newItem.critical)
            };
        } else if (activeTab === 'LINKS') {
            endpoint = '/links';
            body = { source: newItem.source, target: newItem.target, relationship: newItem.relationship };
        } else {
            return;
        }

        try {
            await api.post(endpoint, body);
            setNewItem({});
            fetchData();
        } catch (e) {
            console.error(e);
        }
    }

    const handleDelete = async (id: string) => {
        if (!confirm("Are you sure?")) return;

        try {
            await api.delete(`/${activeTab.toLowerCase()}/${id}`);
            fetchData();
        } catch (e) {
            console.error(e);
        }
    };

    const fileInputRef = React.useRef<HTMLInputElement>(null);

    const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        if (!file) return;

        const formData = new FormData();
        formData.append('file', file);

        setLoading(true);
        try {
            // Use api.request for FormData to handle headers correctly (no JSON content-type)
            const data: any = await api.request('/nodes/upload', {
                method: 'POST',
                body: formData
                // Don't set Content-Type header manually for FormData
            });

            alert('Upload successful! ' + (data.message || ''));
            fetchData();
        } catch (e: any) {
            console.error(e);
            alert(`Upload failed: ${e.message || 'Unknown error'} `);
        } finally {
            setLoading(false);
            if (fileInputRef.current) fileInputRef.current.value = '';
        }
    };

    return (
        <div className="p-8 h-full overflow-y-auto custom-scrollbar space-y-8">
            <h2 className="text-3xl font-black text-white tracking-tighter uppercase">Administration</h2>

            {/* Tabs */}
            <div className="flex gap-4 border-b border-white/5 pb-4">
                {['METRICS', 'CATALOG', 'LINKS', 'INVENTORY'].map(tab => {
                    return (
                        <button
                            key={tab}
                            onClick={() => setActiveTab(tab as any)}
                            className={`text-xs font-bold uppercase tracking-widest px-4 py-2 rounded-lg transition-all ${activeTab === tab ? 'bg-brand-600 text-white' : 'text-neutral-500 hover:text-white hover:bg-white/5'
                                }`}
                        >
                            {tab}
                        </button>
                    )
                })}
            </div>

            {/* Content Area */}
            <div className="h-[calc(100vh-250px)]">
                {activeTab === 'CATALOG' && <CatalogManager />}

                {activeTab === 'METRICS' && <MetricsManager />}

                {activeTab === 'LINKS' && <RelationshipManager onRefresh={fetchData} />}

                {activeTab === 'INVENTORY' ? (
                    <div className="flex gap-6 h-full">
                        {/* Editor Panel */}
                        <div className="w-[400px] flex-shrink-0 bg-neutral-900/50 rounded-2xl border border-white/5 overflow-hidden flex flex-col">
                            <CIEditor
                                key={selectedNode?.id || `new-${refreshKey}`}
                                node={selectedNode}
                                onSave={async (node) => {
                                    try {
                                        await api.post('/nodes', node);

                                        fetchData();
                                        setSelectedNode(null);
                                        setRefreshKey(prev => prev + 1);
                                    } catch (e: any) {
                                        console.error(e);
                                        alert('Error updating CI: ' + e.message);
                                    }
                                }}
                                onDelete={async (id) => {
                                    if (confirm('Delete this CI?')) {
                                        await api.delete(`/nodes/${id}`);
                                        fetchData();
                                        setSelectedNode(null);
                                    }
                                }}
                                onClose={() => setSelectedNode(null)}
                                className="h-full"
                            />
                        </div>

                        {/* List Panel */}
                        <div className="flex-1 glass rounded-2xl border border-white/5 p-6 flex flex-col overflow-hidden">
                            <div className="flex justify-between items-center mb-6">
                                <h3 className="text-xl font-bold text-white tracking-tight">INVENTORY</h3>
                                <div className="flex gap-3">
                                    <button
                                        onClick={() => setSelectedNode(null)}
                                        className="btn-secondary text-xs"
                                    >
                                        <span className="material-symbols-outlined text-sm">add</span>
                                        NEW CI
                                    </button>
                                    <button onClick={() => fetchData()} className="btn-icon">
                                        <span className="material-symbols-outlined">refresh</span>
                                    </button>
                                    <div className="h-6 w-px bg-white/10 mx-2" />
                                    <button
                                        onClick={() => window.open('/api/nodes/template', '_blank')}
                                        className="btn-secondary text-xs"
                                    >
                                        <span className="material-symbols-outlined text-sm">download</span>
                                        TEMPLATE
                                    </button>
                                    <div className="relative">
                                        <input
                                            type="file"
                                            accept=".xlsx"
                                            className="absolute inset-0 opacity-0 cursor-pointer"
                                            onChange={handleFileUpload}
                                        />
                                        <button className="btn-primary text-xs">
                                            <span className="material-symbols-outlined text-sm">upload_file</span>
                                            IMPORT
                                        </button>
                                    </div>
                                </div>
                            </div>

                            <div className="flex-1 overflow-y-auto custom-scrollbar">
                                <table className="w-full text-left border-collapse">
                                    <thead className="sticky top-0 bg-neutral-900/90 backdrop-blur z-10">
                                        <tr className="text-xs text-neutral-500 border-b border-white/10">
                                            <th className="p-3 uppercase tracking-wider font-bold">Name / ID</th>
                                            <th className="p-3 uppercase tracking-wider font-bold">Category</th>
                                            <th className="p-3 uppercase tracking-wider font-bold">IP Address</th>
                                            <th className="p-3 uppercase tracking-wider font-bold">Status</th>
                                            <th className="p-3 text-right uppercase tracking-wider font-bold">Actions</th>
                                        </tr>
                                    </thead>
                                    <tbody className="text-sm divide-y divide-white/5">
                                        {data.map((item: any) => (
                                            <tr
                                                key={item.id}
                                                className={`hover:bg-brand-500/5 transition-colors cursor-pointer ${selectedNode?.id === item.id ? 'bg-brand-500/10' : ''}`}
                                                onClick={() => setSelectedNode(item)}
                                            >
                                                <td className="p-3">
                                                    <div className="font-bold text-white">{item.label}</div>
                                                    <div className="text-[10px] text-neutral-500 font-mono">{item.id}</div>
                                                </td>
                                                <td className="p-3 text-neutral-300">
                                                    <span className="px-2 py-1 rounded bg-white/5 text-xs border border-white/5">
                                                        {item.type || 'Uncategorized'}
                                                    </span>
                                                </td>
                                                <td className="p-3 font-mono text-neutral-400 text-xs">
                                                    {item.ip || '-'}
                                                </td>
                                                <td className="p-3">
                                                    <span className={`px-2 py-0.5 rounded text-[10px] font-black uppercase ${item.status === 'ACTIVE' ? 'bg-green-500/20 text-green-400' :
                                                        item.status === 'MAINTENANCE' ? 'bg-yellow-500/20 text-yellow-400' :
                                                            'bg-neutral-500/20 text-neutral-400'
                                                        }`}>
                                                        {item.status}
                                                    </span>
                                                </td>
                                                <td className="p-3 text-right">
                                                    <button
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            if (confirm('Delete CI?')) {
                                                                api.delete(`/nodes/${item.id}`).then(() => fetchData());
                                                            }
                                                        }}
                                                        className="text-neutral-500 hover:text-red-500 p-2 transition-colors"
                                                    >
                                                        <span className="material-symbols-outlined text-sm">delete</span>
                                                    </button>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                ) : null}
            </div>
        </div>
    );
};

export default AdminPage;

