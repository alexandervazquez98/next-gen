import React, { useState, useEffect, useRef, useMemo } from 'react';
import { api } from '../services/api';
import { GraphNode } from '../types';
import { useCategoriesQuery } from '../hooks/queries/useCategoriesQuery';
import { useQuery } from '@tanstack/react-query';
import CIEditor from './CIEditor';
import MassAssetCreator from './MassAssetCreator';

const AdminInventory: React.FC = () => {
    const [data, setData] = useState<any[]>([]);
    const [loading, setLoading] = useState(false);
    const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
    const [isMassDeploying, setIsMassDeploying] = useState(false);
    const [refreshKey, setRefreshKey] = useState(0);
    const fileInputRef = useRef<HTMLInputElement>(null);

    // Search and Filter State
    const [searchTerm, setSearchTerm] = useState('');
    const [filterLayer, setFilterLayer] = useState('');
    const [filterStatus, setFilterStatus] = useState('');
    
    // Multi-select State
    const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
    const [isBulkEditing, setIsBulkEditing] = useState(false);

    // Catalog Data for Bulk Edit
    const { data: categories } = useCategoriesQuery();
    const { data: hardware } = useQuery({
        queryKey: ['hardware-catalog'],
        queryFn: () => api.get<any[]>('/hardware')
    });
    const { data: owners } = useQuery({
        queryKey: ['owners'],
        queryFn: () => api.get<any[]>('/owners')
    });

    const fetchData = async () => {
        setLoading(true);
        try {
            const json = await api.get<any[]>('/nodes');
            setData(Array.isArray(json) ? json : []);
        } catch (e) {
            console.error("Failed to fetch inventory", e);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchData();
    }, [refreshKey]);

    // Derived Data: Filtered List
    const filteredData = useMemo(() => {
        return data.filter(item => {
            const matchesSearch = !searchTerm || 
                item.label?.toLowerCase().includes(searchTerm.toLowerCase()) ||
                item.id?.toLowerCase().includes(searchTerm.toLowerCase()) ||
                item.ip?.includes(searchTerm);
            
            const matchesLayer = !filterLayer || item.type === filterLayer;
            const matchesStatus = !filterStatus || item.status === filterStatus;

            return matchesSearch && matchesLayer && matchesStatus;
        });
    }, [data, searchTerm, filterLayer, filterStatus]);

    // Unique values for filters
    const layerOptions = useMemo(() => Array.from(new Set(data.map(item => item.type))), [data]);
    const statusOptions = useMemo(() => Array.from(new Set(data.map(item => item.status))), [data]);

    // Bulk Selection Logic
    const selectedItems = useMemo(() => 
        data.filter(item => selectedIds.has(item.id)), 
    [data, selectedIds]);

    const isSelectionUniform = useMemo(() => {
        if (selectedItems.length <= 1) return true;
        const first = selectedItems[0];
        return selectedItems.every(item => item.brand === first.brand && item.model === first.model);
    }, [selectedItems]);

    const handleSelectAll = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.checked) {
            setSelectedIds(new Set(filteredData.map(item => item.id)));
        } else {
            setSelectedIds(new Set());
        }
    };

    const toggleSelect = (id: string) => {
        const next = new Set(selectedIds);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        setSelectedIds(next);
    };

    const handleBulkUpdate = async (updates: any) => {
        setLoading(true);
        try {
            await api.post('/nodes/bulk-update', {
                ids: Array.from(selectedIds),
                updates
            });
            alert('Bulk update successful');
            setIsBulkEditing(false);
            setSelectedIds(new Set());
            setRefreshKey(prev => prev + 1);
        } catch (e: any) {
            alert('Bulk update failed: ' + e.message);
        } finally {
            setLoading(false);
        }
    };


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
        if (!confirm('Are you sure you want to delete this CI?')) return;
        try {
            await api.delete(`/nodes/${id}`);
            setSelectedNode(null);
            setRefreshKey(prev => prev + 1);
        } catch (e: any) {
            alert('Failed to delete CI: ' + e.message);
        }
    };

    const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        if (!file) return;
        const formData = new FormData();
        formData.append('file', file);
        setLoading(true);
        try {
            await api.request('/nodes/upload', { method: 'POST', body: formData });
            setRefreshKey(prev => prev + 1);
            alert('Upload completed');
        } catch (e: any) {
            alert(`Upload failed: ${e.message}`);
        } finally {
            setLoading(false);
            if (fileInputRef.current) fileInputRef.current.value = '';
        }
    };

    return (
        <div className="h-full flex flex-col p-4 overflow-hidden border border-white/5 bg-neutral-950/20">
            {/* Header section */}
            <header className="flex justify-between items-center mb-4 shrink-0 relative border-b border-white/5 pb-3">
                <div className="flex items-center gap-6">
                    <div>
                        <h2 className="text-2xl font-black text-white tracking-tighter uppercase italic leading-none">Inventory</h2>
                        <p className="text-[10px] text-neutral-500 font-medium tracking-tight mt-1">Total Assets: {filteredData.length}</p>
                    </div>

                    {/* Search Bar */}
                    <div className="flex items-center gap-2 bg-black/40 border border-white/5 rounded-xl px-3 py-1.5 focus-within:border-brand-500/50 transition-all">
                        <span className="material-symbols-outlined text-sm text-neutral-500">search</span>
                        <input 
                            className="bg-transparent text-xs text-white outline-none w-48 font-bold placeholder:text-neutral-700"
                            placeholder="Search Label, IP, ID..."
                            value={searchTerm}
                            onChange={e => setSearchTerm(e.target.value)}
                        />
                    </div>

                    {/* Quick Filters */}
                    <div className="flex items-center gap-2">
                        <select 
                            className="bg-neutral-900 border border-white/5 rounded-lg px-2 py-1 text-[10px] font-bold text-neutral-400 outline-none"
                            value={filterLayer}
                            onChange={e => setFilterLayer(e.target.value)}
                        >
                            <option value="">All Layers</option>
                            {layerOptions.map(l => <option key={l} value={l}>{l}</option>)}
                        </select>
                        <select 
                            className="bg-neutral-900 border border-white/5 rounded-lg px-2 py-1 text-[10px] font-bold text-neutral-400 outline-none"
                            value={filterStatus}
                            onChange={e => setFilterStatus(e.target.value)}
                        >
                            <option value="">All Status</option>
                            {statusOptions.map(s => <option key={s} value={s}>{s}</option>)}
                        </select>
                    </div>
                </div>

                <div className="flex items-center gap-2">
                    {selectedIds.size > 0 && (
                        <div className="flex items-center gap-2 mr-4 px-3 py-1.5 bg-brand-500/10 border border-brand-500/20 rounded-xl animate-in fade-in slide-in-from-top-2">
                            <span className="text-[10px] font-black text-brand-400 uppercase tracking-widest">{selectedIds.size} Selected</span>
                            <button 
                                onClick={() => setIsBulkEditing(true)}
                                className="px-3 py-1 bg-brand-500 text-black text-[9px] font-black rounded-lg hover:bg-brand-400 transition-all uppercase"
                            >
                                Bulk Edit
                            </button>
                        </div>
                    )}

                    <div className="flex items-center gap-1 bg-neutral-900 border border-white/5 rounded-xl p-1 shadow-2xl scale-90 origin-right">
                        <button onClick={() => api.get<Blob>('/nodes/template').then(b => {
                            const url = window.URL.createObjectURL(b);
                            const a = document.createElement('a'); a.href = url; a.download = 'template.xlsx'; a.click();
                        })} className="btn-secondary text-[9px] px-2 py-1">TEMP</button>
                        <div className="relative">
                            <button className="btn-brand text-[9px] px-2 py-1 uppercase">Bulk</button>
                            <input ref={fileInputRef} type="file" accept=".xlsx" className="absolute inset-0 opacity-0 cursor-pointer" onChange={handleFileUpload} />
                        </div>
                    </div>
                    <button 
                        onClick={() => { setSelectedNode(null); setIsMassDeploying(true); setIsBulkEditing(false); }}
                        className="px-4 py-2 bg-neutral-800 hover:bg-neutral-700 text-brand-400 border border-brand-500/20 rounded-xl text-[10px] font-black transition-all uppercase tracking-widest"
                    >
                        Mass Deploy
                    </button>
                    <button 
                        onClick={() => { setIsMassDeploying(false); setIsBulkEditing(false); setSelectedNode({} as GraphNode); }}
                        className="px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white rounded-xl text-[10px] font-black transition-all shadow-xl uppercase tracking-widest"
                    >
                        New
                    </button>
                </div>
            </header>

            {/* Main Content Area */}
            <div className="flex-1 flex gap-4 min-h-0 overflow-hidden relative">
                <div className="flex-1 bg-neutral-900/50 rounded-2xl border border-white/5 flex flex-col overflow-hidden shadow-2xl backdrop-blur-sm relative">
                    <div className="p-3 border-b border-white/5 bg-black/20 flex justify-between items-center shrink-0">
                        <div className="flex items-center gap-4">
                            <input 
                                type="checkbox" 
                                className="w-3.5 h-3.5 rounded border-white/10 bg-neutral-950 checked:bg-brand-500 transition-all cursor-pointer"
                                checked={filteredData.length > 0 && selectedIds.size === filteredData.length}
                                onChange={handleSelectAll}
                            />
                            <span className="text-[9px] font-black text-neutral-500 uppercase tracking-widest">Active Assets</span>
                        </div>
                    </div>

                    <div className="flex-1 relative overflow-hidden">
                        <div className="absolute inset-0 overflow-y-auto custom-scrollbar p-1">
                            <table className="w-full border-collapse">
                                <thead className="sticky top-0 bg-neutral-900 z-10">
                                    <tr className="text-left border-b border-white/5">
                                        <th className="w-10 p-3 bg-neutral-900"></th>
                                        <th className="p-3 text-[9px] font-black text-neutral-500 uppercase tracking-widest bg-neutral-900">CI Identity</th>
                                        <th className="p-3 text-[9px] font-black text-neutral-500 uppercase tracking-widest bg-neutral-900">Network</th>
                                        <th className="p-3 text-[9px] font-black text-neutral-500 uppercase tracking-widest bg-neutral-900">Layer / Hardware</th>
                                        <th className="p-3 text-[9px] font-black text-neutral-500 uppercase tracking-widest text-right bg-neutral-900">Actions</th>
                                    </tr>
                                </thead>
                                <tbody className="text-xs divide-y divide-white/5">
                                    {filteredData.map((item: any) => (
                                        <tr key={item.id} className={`group hover:bg-white/[0.02] transition-colors ${selectedIds.has(item.id) ? 'bg-brand-500/5' : ''}`}>
                                            <td className="p-3 text-center">
                                                <input 
                                                    type="checkbox"
                                                    className="w-3.5 h-3.5 rounded border-white/10 bg-neutral-950 checked:bg-brand-500 transition-all cursor-pointer"
                                                    checked={selectedIds.has(item.id)}
                                                    onChange={() => toggleSelect(item.id)}
                                                />
                                            </td>
                                            <td className="p-3">
                                                <div className="flex flex-col">
                                                    <span className="font-black text-white tracking-tight">{item.label}</span>
                                                    <span className="text-[9px] text-neutral-500 font-mono uppercase">{item.id}</span>
                                                </div>
                                            </td>
                                            <td className="p-3">
                                                <div className="flex flex-col">
                                                    <span className="text-[11px] text-neutral-300 font-bold">{item.ip || 'No IP'}</span>
                                                    <span className="text-[9px] text-neutral-500 font-medium uppercase tracking-tighter">{item.status}</span>
                                                </div>
                                            </td>
                                            <td className="p-3">
                                                <div className="flex items-center gap-2">
                                                    <span className="px-1.5 py-0.5 bg-neutral-800 text-neutral-400 rounded-md text-[9px] font-bold uppercase border border-white/5">{item.type}</span>
                                                    <span className="text-[10px] text-neutral-500 truncate max-w-[150px]">{item.brand} {item.model}</span>
                                                </div>
                                            </td>
                                            <td className="p-3 text-right">
                                                <button onClick={() => { setIsMassDeploying(false); setIsBulkEditing(false); setSelectedNode(item); }} className="p-1.5 hover:bg-brand-500/10 hover:text-brand-400 text-neutral-600 rounded-lg transition-all">
                                                    <span className="material-symbols-outlined text-sm">edit_note</span>
                                                </button>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>

                {/* Right Side Panels */}
                {(selectedNode || isMassDeploying || isBulkEditing) && (
                    <div className="w-[450px] shrink-0 animate-in slide-in-from-right duration-300 relative border-l border-white/5">
                        {isMassDeploying ? (
                            <MassAssetCreator onClose={() => setIsMassDeploying(false)} onRefresh={() => setRefreshKey(k => k+1)} />
                        ) : isBulkEditing ? (
                            <div className="h-full bg-neutral-900 p-6 space-y-6 overflow-y-auto custom-scrollbar">
                                <header className="flex justify-between items-center border-b border-white/5 pb-4">
                                    <div>
                                        <h3 className="text-xl font-black text-white uppercase italic">Bulk Metadata Edit</h3>
                                        <p className="text-[10px] text-neutral-500 font-bold uppercase tracking-widest">Updating {selectedIds.size} Selected Assets</p>
                                    </div>
                                    <button onClick={() => setIsBulkEditing(false)} className="p-2 hover:bg-white/5 rounded-full text-neutral-500 transition-all"><span className="material-symbols-outlined">close</span></button>
                                </header>
                                
                                <div className="space-y-6">
                                    <div className="grid grid-cols-2 gap-4">
                                        <label className="block col-span-2">
                                            <span className="text-[10px] font-bold text-neutral-500 uppercase mb-1 block">Technology / Layer</span>
                                            <select className="w-full bg-neutral-950 border border-white/5 rounded-lg px-3 py-2 text-xs text-white outline-none focus:border-brand-500" id="bulk-type">
                                                <option value="">Keep current...</option>
                                                {categories?.map((c: any) => <option key={c.name} value={c.name}>{c.name}</option>)}
                                            </select>
                                        </label>
                                        <label className="block col-span-2">
                                            <span className="text-[10px] font-bold text-neutral-500 uppercase mb-1 block">Hardware Model</span>
                                            <select className="w-full bg-neutral-950 border border-white/5 rounded-lg px-3 py-2 text-xs text-white outline-none focus:border-brand-500" id="bulk-hw">
                                                <option value="|">Keep current...</option>
                                                {hardware?.map((h: any) => <option key={`${h.brand}-${h.model}`} value={`${h.brand}|${h.model}`}>{h.brand} {h.model}</option>)}
                                            </select>
                                        </label>
                                        <label className="block">
                                            <span className="text-[10px] font-bold text-neutral-500 uppercase mb-1 block">Operational Status</span>
                                            <select className="w-full bg-neutral-950 border border-white/5 rounded-lg px-3 py-2 text-xs text-white outline-none focus:border-brand-500" id="bulk-status">
                                                <option value="">Keep current...</option>
                                                <option value="ACTIVE">ACTIVE</option>
                                                <option value="MAINTENANCE">MAINTENANCE</option>
                                                <option value="EXCEPTION">EXCEPTION</option>
                                            </select>
                                        </label>
                                        <label className="block">
                                            <span className="text-[10px] font-bold text-neutral-500 uppercase mb-1 block">Polling (s)</span>
                                            <input type="number" className="w-full bg-neutral-950 border border-white/5 rounded-lg px-3 py-2 text-xs text-white outline-none focus:border-brand-500" placeholder="60" id="bulk-polling" />
                                        </label>
                                        <label className="block col-span-2">
                                            <span className="text-[10px] font-bold text-neutral-500 uppercase mb-1 block">New Location</span>
                                            <input className="w-full bg-neutral-950 border border-white/5 rounded-lg px-3 py-2 text-xs text-white outline-none focus:border-brand-500" placeholder="Search by location..." id="bulk-location" />
                                        </label>
                                        <label className="block col-span-2">
                                            <span className="text-[10px] font-bold text-neutral-500 uppercase mb-1 block">Owner Group</span>
                                            <select className="w-full bg-neutral-950 border border-white/5 rounded-lg px-3 py-2 text-xs text-white outline-none focus:border-brand-500" id="bulk-owner">
                                                <option value="">Keep current...</option>
                                                {owners?.map((o: any) => <option key={o.name} value={o.name}>{o.name}</option>)}
                                            </select>
                                        </label>
                                    </div>
                                </div>

                                <div className="pt-6">
                                    <button 
                                        disabled={loading}
                                        onClick={() => {
                                            const hwValue = (document.getElementById('bulk-hw') as HTMLSelectElement).value;
                                            const [brand, model] = hwValue.split('|');
                                            handleBulkUpdate({
                                                type: (document.getElementById('bulk-type') as HTMLSelectElement).value || undefined,
                                                brand: brand || undefined,
                                                model: model || undefined,
                                                status: (document.getElementById('bulk-status') as HTMLSelectElement).value || undefined,
                                                location_name: (document.getElementById('bulk-location') as HTMLInputElement).value || undefined,
                                                owner: (document.getElementById('bulk-owner') as HTMLSelectElement).value || undefined,
                                                pollingInterval: (document.getElementById('bulk-polling') as HTMLInputElement).value ? parseInt((document.getElementById('bulk-polling') as HTMLInputElement).value) : undefined
                                            });
                                        }}
                                        className="w-full py-4 bg-brand-600 hover:bg-brand-500 text-white rounded-2xl text-xs font-black uppercase tracking-[0.2em] shadow-xl shadow-brand-900/20 transition-all disabled:opacity-50"
                                    >
                                        {loading ? 'Processing Update...' : `Update ${selectedIds.size} Assets`}
                                    </button>
                                    <p className="text-[9px] text-neutral-500 mt-4 text-center italic">Leave fields empty to keep their current values.</p>
                                </div>
                            </div>
                        ) : (
                            <CIEditor 
                                node={selectedNode?.id ? selectedNode : null} 
                                onSave={handleSaveNode} 
                                onDelete={handleDeleteNode} 
                                onClose={() => setSelectedNode(null)} 
                                className="h-full border-none shadow-none overflow-hidden" 
                            />
                        )}
                    </div>
                )}
            </div>
        </div>
    );
};

export default AdminInventory;
