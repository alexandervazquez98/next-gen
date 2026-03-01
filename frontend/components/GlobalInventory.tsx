
import React, { useEffect, useState } from 'react';
import { GraphNode } from '../types';
import { getStatusClasses } from '../utils/status';

/**
 * GlobalInventory Component
 * 
 * Lists all CIs with their live metrics and categorization.
 * Supports filtering by category and search by name/IP.
 */
const GlobalInventory: React.FC = () => {
    // Unify on GraphNode for consistency
    const [inventory, setInventory] = useState<GraphNode[]>([]);
    const [filteredInventory, setFilteredInventory] = useState<GraphNode[]>([]);
    const [categories, setCategories] = useState<string[]>([]);
    const [selectedCategory, setSelectedCategory] = useState<string>('ALL');
    const [selectedItem, setSelectedItem] = useState<GraphNode | null>(null);
    const [searchTerm, setSearchTerm] = useState('');

    const fetchData = () => {
        const token = localStorage.getItem('token');
        const headers = { 'Authorization': `Bearer ${token}` };

        // Fetch Inventory (CIs with Metrics)
        fetch('/api/nodes', { headers })
            .then(res => {
                if (!res.ok) throw new Error(res.statusText);
                return res.json();
            })
            .then(data => {
                if (Array.isArray(data)) {
                    setInventory(data);
                    if (selectedItem) {
                        // Real-time update of selected item
                        const updated = data.find((i: GraphNode) => i.id === selectedItem.id);
                        if (updated) setSelectedItem(updated);
                    }
                } else {
                    console.error("Expected array for inventory but got:", data);
                    setInventory([]);
                }
            })
            .catch(err => console.error("Failed to fetch inventory:", err));

        fetch('/api/categories', { headers })
            .then(res => {
                if (!res.ok) throw new Error(res.statusText);
                return res.json();
            })
            .then(data => {
                if (Array.isArray(data)) {
                    setCategories(data.map((c: any) => c.name));
                } else {
                    console.error("Expected array for categories but got:", data);
                    setCategories([]);
                }
            })
            .catch(err => console.error("Failed to fetch categories:", err));
    };

    useEffect(() => {
        fetchData();
        const interval = setInterval(fetchData, 5000);
        return () => clearInterval(interval);
    }, []);

    // Filter Logic
    useEffect(() => {
        let res = inventory;
        if (selectedCategory !== 'ALL') {
            res = res.filter(i => i.category === selectedCategory || i.type === selectedCategory);
        }
        if (searchTerm) {
            const lower = searchTerm.toLowerCase();
            res = res.filter(i =>
                (i.label || i.id || '').toLowerCase().includes(lower) ||
                i.ip?.toLowerCase().includes(lower)
            );
        }
        setFilteredInventory(res);
    }, [inventory, selectedCategory, searchTerm]);

    return (
        <div className="h-full flex flex-col p-6 overflow-hidden">
            <header className="flex justify-between items-center mb-6">
                <div>
                    <h2 className="text-2xl font-black text-white uppercase tracking-tighter">Global Inventory</h2>
                    <p className="text-xs text-neutral-500 font-bold uppercase tracking-widest">Real-time CI Metrics & Status</p>
                </div>
                <div className="flex gap-4">
                    <input
                        type="text"
                        placeholder="SEARCH CI..."
                        value={searchTerm}
                        onChange={e => setSearchTerm(e.target.value)}
                        className="bg-black/20 border border-white/10 rounded-lg px-4 py-2 text-xs font-bold text-white focus:outline-none focus:border-brand-500 transition-colors uppercase"
                    />
                    <select
                        value={selectedCategory}
                        onChange={e => setSelectedCategory(e.target.value)}
                        className="bg-black/20 border border-white/10 rounded-lg px-4 py-2 text-xs font-bold text-neutral-400 focus:outline-none focus:border-brand-500 transition-colors uppercase"
                    >
                        <option value="ALL">ALL CATEGORIES</option>
                        {categories.map(c => <option key={c} value={c}>{c}</option>)}
                    </select>
                </div>
            </header>

            <div className="flex-1 flex gap-6 overflow-hidden">
                {/* List Column */}
                <div className="w-1/3 flex flex-col gap-3 overflow-y-auto custom-scrollbar pr-2">
                    {filteredInventory.map(item => (
                        <div
                            key={item.id}
                            onClick={() => setSelectedItem(item)}
                            className={`p-4 rounded-xl border cursor-pointer transition-all group ${selectedItem?.id === item.id
                                ? 'bg-brand-600/10 border-brand-500/50 shadow-[0_0_15px_rgba(59,130,246,0.15)]'
                                : 'bg-white/5 border-white/5 hover:bg-white/10 hover:border-white/10'
                                }`}
                        >
                            <div className="flex justify-between items-start">
                                <div>
                                    <div className="flex items-center gap-2">
                                        <span className={`w-2 h-2 rounded-full ${item.metrics?.some(m => m.status === 'CRITICAL') ? 'bg-red-500 animate-pulse' : 'bg-emerald-500'}`}></span>
                                        <h3 className={`text-sm font-black ${selectedItem?.id === item.id ? 'text-brand-400' : 'text-white'}`}>{item.label || item.id}</h3>
                                    </div>
                                    <div className="flex gap-2 mt-1">
                                        <span className="text-[10px] font-mono text-neutral-500">{item.ip || 'NO IP'}</span>
                                        {item.category && <span className="text-[10px] font-bold text-brand-400 bg-brand-500/10 px-1.5 rounded">{item.category}</span>}
                                    </div>
                                </div>
                                <span className="material-symbols-outlined text-neutral-600 text-lg group-hover:text-white transition-colors">chevron_right</span>
                            </div>
                        </div>
                    ))}
                </div>

                {/* Detail Column */}
                <div className="flex-1 glass rounded-2xl border border-white/5 p-6 overflow-y-auto custom-scrollbar relative">
                    {selectedItem ? (
                        <div className="space-y-8">
                            <div className="flex items-start justify-between border-b border-white/5 pb-6">
                                <div>
                                    <h2 className="text-3xl font-black text-white uppercase">{selectedItem.label || selectedItem.id}</h2>
                                    <div className="flex gap-4 mt-2">
                                        <span className="text-xs font-mono text-neutral-400 bg-black/20 px-2 py-1 rounded">ID: {selectedItem.id}</span>
                                        {(selectedItem.category || selectedItem.type) && <span className="text-xs font-bold text-brand-400 bg-brand-500/10 px-2 py-1 rounded">{selectedItem.category || selectedItem.type}</span>}
                                        <span className="text-xs font-mono text-accent-cyan bg-accent-cyan/10 px-2 py-1 rounded">{selectedItem.ip}</span>
                                    </div>
                                </div>
                                <div className="text-right">
                                    <p className="text-[10px] text-neutral-500 uppercase font-bold tracking-widest">Active Metrics</p>
                                    <p className="text-2xl font-black text-white">{selectedItem.metrics?.length || 0}</p>
                                </div>
                            </div>

                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                {selectedItem.metrics?.map((metric, idx) => (
                                    <div key={idx} className={`p-4 rounded-xl border ${getStatusClasses(metric.status)} flex flex-col gap-2 transition-all hover:scale-[1.02]`}>
                                        <div className="flex justify-between items-start">
                                            <span className="text-[10px] font-black uppercase opacity-70 tracking-wider">{metric.protocol}</span>
                                            {metric.status === 'CRITICAL' && <span className="material-symbols-outlined text-sm animate-pulse">warning</span>}
                                        </div>
                                        <h4 className="text-center font-black text-sm uppercase opacity-90">{metric.name}</h4>
                                        <div className="text-center py-2">
                                            <span className="text-2xl font-black tracking-tighter">{metric.value ?? '--'}</span>
                                        </div>
                                        <div className="text-[10px] font-mono opacity-50 text-right">
                                            Last: {metric.last_updated ? new Date(metric.last_updated).toLocaleTimeString() : 'NEVER'}
                                        </div>
                                    </div>
                                ))}
                                {(!selectedItem.metrics || selectedItem.metrics.length === 0) && (
                                    <div className="col-span-2 text-center py-12 text-neutral-600">
                                        <span className="material-symbols-outlined text-4xl mb-2">sensor_window</span>
                                        <p className="text-xs font-bold uppercase">No Metrics Configured</p>
                                    </div>
                                )}
                            </div>
                        </div>
                    ) : (
                        <div className="h-full flex flex-col items-center justify-center text-neutral-600 opacity-50">
                            <span className="material-symbols-outlined text-6xl mb-4">touch_app</span>
                            <p className="text-sm font-bold uppercase tracking-widest">Select a CI to view telemetry</p>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

export default GlobalInventory;
