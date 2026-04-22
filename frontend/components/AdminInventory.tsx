import React, { useState, useEffect, useRef } from 'react';
import { api } from '../services/api';
import { GraphNode } from '../types';
import CIEditor from './CIEditor';
import MassAssetCreator from './MassAssetCreator';

const AdminInventory: React.FC = () => {
    const [data, setData] = useState<any[]>([]);
    const [loading, setLoading] = useState(false);
    const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
    const [isMassDeploying, setIsMassDeploying] = useState(false);
    const [refreshKey, setRefreshKey] = useState(0);
    const fileInputRef = useRef<HTMLInputElement>(null);

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
        <div className="absolute inset-0 flex flex-col p-4 overflow-hidden border border-white/5 bg-neutral-950/20">
            {/* Header section - Reduced padding/margins */}
            <header className="flex justify-between items-center mb-4 shrink-0 relative border-b border-white/5 pb-3">
                <div>
                    <h2 className="text-2xl font-black text-white tracking-tighter uppercase italic leading-none">Inventory</h2>
                    <p className="text-[10px] text-neutral-500 font-medium tracking-tight mt-1">Managing configuration state.</p>
                </div>

                <div className="flex items-center gap-2">
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
                        onClick={() => { setSelectedNode(null); setIsMassDeploying(true); }}
                        className="px-4 py-2 bg-neutral-800 hover:bg-neutral-700 text-brand-400 border border-brand-500/20 rounded-xl text-[10px] font-black transition-all uppercase tracking-widest"
                    >
                        Mass
                    </button>
                    <button 
                        onClick={() => { setIsMassDeploying(false); setSelectedNode({} as GraphNode); }}
                        className="px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white rounded-xl text-[10px] font-black transition-all shadow-xl uppercase tracking-widest"
                    >
                        New
                    </button>
                </div>
            </header>

            {/* Main Content Area - Responsive Flex Container */}
            <div className="flex-1 flex gap-4 min-h-0 overflow-hidden relative">
                {/* Table Container */}
                <div className="flex-1 bg-neutral-900/50 rounded-2xl border border-white/5 flex flex-col overflow-hidden shadow-2xl backdrop-blur-sm relative">
                    <div className="p-3 border-b border-white/5 bg-black/20 flex justify-between items-center shrink-0">
                        <span className="text-[9px] font-black text-neutral-500 uppercase tracking-widest">Active Assets ({data.length})</span>
                    </div>

                    {/* This is the key wrapper: relative + flex-1 + overflow-hidden */}
                    <div className="flex-1 relative overflow-hidden">
                        <div className="absolute inset-0 overflow-y-auto custom-scrollbar p-1">
                            <table className="w-full border-collapse">
                                <thead className="sticky top-0 bg-neutral-900 z-10">
                                    <tr className="text-left border-b border-white/5">
                                        <th className="p-3 text-[9px] font-black text-neutral-500 uppercase tracking-widest bg-neutral-900">CI Identity</th>
                                        <th className="p-3 text-[9px] font-black text-neutral-500 uppercase tracking-widest bg-neutral-900">Network</th>
                                        <th className="p-3 text-[9px] font-black text-neutral-500 uppercase tracking-widest bg-neutral-900">Layer</th>
                                        <th className="p-3 text-[9px] font-black text-neutral-500 uppercase tracking-widest text-right bg-neutral-900">Actions</th>
                                    </tr>
                                </thead>
                                <tbody className="text-xs divide-y divide-white/5">
                                    {data.map((item: any) => (
                                        <tr key={item.id} className={`group hover:bg-white/[0.02] transition-colors ${selectedNode?.id === item.id ? 'bg-white/[0.03]' : ''}`}>
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
                                                    <span className="text-[10px] text-neutral-500 truncate max-w-[100px]">{item.model}</span>
                                                </div>
                                            </td>
                                            <td className="p-3 text-right">
                                                <button onClick={() => { setIsMassDeploying(false); setSelectedNode(item); }} className="p-1.5 hover:bg-brand-500/10 hover:text-brand-400 text-neutral-600 rounded-lg transition-all">
                                                    <span className="material-symbols-outlined text-sm">edit_note</span>
                                                </button>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                            {/* Visual Sentinel */}
                            <div className="w-full text-center py-6">
                                <div className="inline-block px-3 py-1 bg-red-500/20 text-red-500 text-[10px] font-black rounded-full border border-red-500/30">
                                    END_OF_INVENTORY
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Right Side Panels (Editor / Mass Deployer) */}
                {(selectedNode || isMassDeploying) && (
                    <div className="w-[420px] shrink-0 animate-in slide-in-from-right duration-300 relative border-l border-white/5">
                        {isMassDeploying ? (
                            <MassAssetCreator onClose={() => setIsMassDeploying(false)} onRefresh={() => setRefreshKey(k => k+1)} />
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
