
import React, { useState, useEffect, useMemo } from 'react';
import MetricsManager from './MetricsManager';
import DictionaryManager from './DictionaryManager';
import CIEditor from './CIEditor';
import RelationshipManager from './RelationshipManager';
import MassLinkEditor from './MassLinkEditor';
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
    type AdminTab = 'METRICS' | 'DICTIONARIES' | 'CATALOG' | 'LINKS' | 'MASS_LINKS' | 'INVENTORY';
    const [activeTab, setActiveTab] = useState<AdminTab>('METRICS');

    const [data, setData] = useState<any[]>([]);
    const [loading, setLoading] = useState(false);

    // Form States
    const [newItem, setNewItem] = useState<any>({});
    const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
    const [refreshKey, setRefreshKey] = useState(0);
    const [inventorySearch, setInventorySearch] = useState('');

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

    const searchableText = (value: unknown): string => {
        if (value == null) return '';
        if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
            return String(value);
        }
        if (Array.isArray(value)) {
            return value.map(searchableText).join(' ');
        }
        if (typeof value === 'object') {
            return Object.values(value as Record<string, unknown>).map(searchableText).join(' ');
        }
        return '';
    };

    const filteredInventory = useMemo(() => {
        const query = inventorySearch.trim().toLowerCase();
        if (!query) return data;

        return data.filter((item) => searchableText(item).toLowerCase().includes(query));
    }, [data, inventorySearch]);

    return (
        <div className="p-8 h-full overflow-y-auto custom-scrollbar space-y-8">
            <h2 className="text-3xl font-black text-white tracking-tighter uppercase">Administration</h2>

            {/* Tabs */}
            <div className="flex gap-4 border-b border-white/5 pb-4">
                {['METRICS', 'DICTIONARIES', 'CATALOG', 'LINKS', 'MASS_LINKS', 'INVENTORY'].map(tab => {
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

                {activeTab === 'DICTIONARIES' && <DictionaryManager />}

                {activeTab === 'METRICS' && <MetricsManager />}

                {activeTab === 'LINKS' && <RelationshipManager onRefresh={fetchData} />}

                {activeTab === 'MASS_LINKS' && <MassLinkEditor />}

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
                            <div className="flex justify-between items-center mb-6 gap-4">
                                <div className="flex items-center gap-4 min-w-0">
                                    <h3 className="text-xl font-bold text-white tracking-tight shrink-0">INVENTORY</h3>
                                    <div className="relative w-[360px] max-w-[40vw]">
                                        <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500 text-sm">search</span>
                                        <input
                                            value={inventorySearch}
                                            onChange={(e) => setInventorySearch(e.target.value)}
                                            placeholder="Search any CI field..."
                                            className="w-full bg-neutral-950/80 border border-white/10 rounded-lg pl-9 pr-8 py-2 text-xs text-white placeholder:text-neutral-600 outline-none focus:border-brand-500 transition-colors"
                                        />
                                        {inventorySearch && (
                                            <button
                                                onClick={() => setInventorySearch('')}
                                                className="absolute right-2 top-1/2 -translate-y-1/2 text-neutral-500 hover:text-white transition-colors"
                                                title="Clear search"
                                            >
                                                <span className="material-symbols-outlined text-sm">close</span>
                                            </button>
                                        )}
                                    </div>
                                    {inventorySearch && (
                                        <span className="text-[10px] font-bold uppercase text-neutral-500 shrink-0">
                                            {filteredInventory.length}/{data.length}
                                        </span>
                                    )}
                                </div>
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
                                        {filteredInventory.map((item: any) => (
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

