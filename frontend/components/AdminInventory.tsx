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
        <div className="absolute inset-0 flex flex-col p-6 overflow-hidden border-2 border-dashed border-white/5">
            <div className="absolute top-0 right-0 z-[100] opacity-50 pointer-events-none"><span className="bg-blue-500 text-white text-[8px] px-1 rounded font-black uppercase tracking-tighter">INV_CONTAINER_START</span></div>
            
            {/* Header section - Fixed height */}
            <header className="flex justify-between items-end mb-6 shrink-0 relative border-b border-white/5 pb-4">
                <div className="absolute top-0 left-1/2 -translate-x-1/2 opacity-30 pointer-events-none"><span className="bg-green-500 text-black text-[8px] px-1 rounded font-black uppercase">INV_HEADER</span></div>
                <div>
                    <h2 className="text-3xl font-black text-white tracking-tighter uppercase italic">Inventory</h2>
                    <p className="text-neutral-500 text-sm font-medium tracking-tight">Managing technical assets and configuration state.</p>
                </div>

                <div className="flex items-center gap-3">
                    <div className="flex items-center gap-2 bg-neutral-900 border border-white/5 rounded-2xl p-1 shadow-2xl">
                        <button onClick={() => api.get<Blob>('/nodes/template').then(b => {
                            const url = window.URL.createObjectURL(b);
                            const a = document.createElement('a'); a.href = url; a.download = 'template.xlsx'; a.click();
                        })} className="btn-secondary text-xs">TEMPLATE</button>
                        <div className="relative">
                            <button className="btn-brand text-xs">BULK UPLOAD</button>
                            <input ref={fileInputRef} type="file" accept=".xlsx" className="absolute inset-0 opacity-0 cursor-pointer" onChange={handleFileUpload} />
                        </div>
                    </div>
                    <button 
                        onClick={() => { setSelectedNode(null); setIsMassDeploying(true); }}
                        className="px-6 py-2.5 bg-neutral-800 hover:bg-neutral-700 text-brand-400 border border-brand-500/20 rounded-2xl text-xs font-black transition-all uppercase tracking-widest"
                    >
                        Mass Deploy
                    </button>
                    <button 
                        onClick={() => { setIsMassDeploying(false); setSelectedNode({} as GraphNode); }}
                        className="px-6 py-2.5 bg-brand-600 hover:bg-brand-500 text-white rounded-2xl text-xs font-black transition-all shadow-xl shadow-brand-900/20 uppercase tracking-widest"
                    >
                        New CI
                    </button>
                </div>
            </header>

            {/* Main Content Area - Responsive Flex Container */}
            <div className="flex-1 flex gap-6 min-h-0 overflow-hidden relative">
                <div className="absolute -top-4 left-0 w-full text-center opacity-30 pointer-events-none z-50"><span className="bg-purple-500 text-white text-[8px] px-1 rounded font-black uppercase">CONTENT_AREA_START</span></div>
                
                {/* Table Container */}
                <div className="flex-1 bg-neutral-900/50 rounded-3xl border border-white/5 flex flex-col overflow-hidden shadow-2xl backdrop-blur-sm relative">
                    <div className="p-4 border-b border-white/5 bg-black/20 flex justify-between items-center shrink-0">
                        <span className="text-[10px] font-black text-neutral-500 uppercase tracking-[0.2em]">Active Assets (Total: {data.length})</span>
                    </div>

                    {/* This is the key wrapper: relative + flex-1 + overflow-hidden */}
                    <div className="flex-1 relative overflow-hidden">
                        <div className="absolute inset-0 overflow-y-auto custom-scrollbar">
                            <table className="w-full border-collapse">
                                <thead className="sticky top-0 bg-neutral-900 z-10">
                                    <tr className="text-left border-b border-white/5">
                                        <th className="p-4 text-[10px] font-black text-neutral-500 uppercase tracking-widest bg-neutral-900">CI Identity</th>
                                        <th className="p-4 text-[10px] font-black text-neutral-500 uppercase tracking-widest bg-neutral-900">Network Info</th>
                                        <th className="p-4 text-[10px] font-black text-neutral-500 uppercase tracking-widest bg-neutral-900">Layer / Model</th>
                                        <th className="p-4 text-[10px] font-black text-neutral-500 uppercase tracking-widest text-right bg-neutral-900">Actions</th>
                                    </tr>
                                </thead>
                                <tbody className="text-sm divide-y divide-white/5">
                                    {data.map((item: any) => (
                                        <tr key={item.id} className={`group hover:bg-white/[0.02] transition-colors ${selectedNode?.id === item.id ? 'bg-white/[0.03]' : ''}`}>
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
                                                    <span className="px-2 py-0.5 bg-neutral-800 text-neutral-400 rounded-md text-[10px] font-bold uppercase border border-white/5">{item.type}</span>
                                                    <span className="text-xs text-neutral-500">{item.brand} {item.model}</span>
                                                </div>
                                            </td>
                                            <td className="p-4 text-right">
                                                <button onClick={() => { setIsMassDeploying(false); setSelectedNode(item); }} className="p-2 hover:bg-brand-500/10 hover:text-brand-400 text-neutral-600 rounded-xl transition-all">
                                                    <span className="material-symbols-outlined text-sm">edit_note</span>
                                                </button>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                            <div className="w-full text-center py-8 opacity-50"><span className="bg-red-500 text-white text-xs px-4 py-1 rounded-full font-black animate-bounce shadow-xl">⚠️ INV_TABLE_END_REACHED ⚠️</span></div>
                        </div>
                    </div>
                </div>

                {/* Right Side Panels (Editor / Mass Deployer) */}
                {(selectedNode || isMassDeploying) && (
                    <div className="w-[500px] shrink-0 animate-in slide-in-from-right duration-300">
                        {isMassDeploying ? (
                            <MassAssetCreator onClose={() => setIsMassDeploying(false)} onRefresh={() => setRefreshKey(k => k+1)} />
                        ) : (
                            <CIEditor 
                                node={selectedNode?.id ? selectedNode : null} 
                                onSave={handleSaveNode} 
                                onDelete={handleDeleteNode} 
                                onClose={() => setSelectedNode(null)} 
                                className="h-full rounded-3xl border border-white/5 shadow-2xl overflow-hidden" 
                            />
                        )}
                    </div>
                )}
            </div>
        </div>
    );
};

export default AdminInventory;
