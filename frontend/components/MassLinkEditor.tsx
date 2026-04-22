import React, { useState, useMemo, useEffect } from 'react';
import { api } from '../services/api';
import { useCategoriesQuery } from '../hooks/queries/useCategoriesQuery';
import { useQuery } from '@tanstack/react-query';

interface FilterState {
    label: 'CI' | 'MetricDef';
    layer: string;
    brand: string;
    model: string;
    searchTerm: string;
    id: string;
    ids: string[]; // Explicit selection
}

interface FilterPanelProps {
    title: string;
    filter: FilterState;
    setFilter: (f: FilterState) => void;
    categories?: any[];
    metrics?: any[];
    availableNodes?: any[];
    hardwareModels?: { brand: string, model: string }[];
}

const FilterPanel: React.FC<FilterPanelProps> = ({ title, filter, setFilter, categories, metrics, availableNodes, hardwareModels }) => {
    const toggleId = (id: string) => {
        const nextIds = filter.ids.includes(id) 
            ? filter.ids.filter(i => i !== id) 
            : [...filter.ids, id];
        setFilter({ ...filter, ids: nextIds });
    };

    const selectAll = () => {
        if (availableNodes) {
            setFilter({ ...filter, ids: availableNodes.map(n => n.id) });
        }
    };

    const uniqueBrands = Array.from(new Set(hardwareModels?.map(h => h.brand))).sort();
    const availableModels = hardwareModels?.filter(h => !filter.brand || h.brand === filter.brand).map(h => h.model).sort();

    return (
        <div className="flex-1 p-6 bg-neutral-900/50 border border-white/5 rounded-2xl space-y-4 flex flex-col min-h-[450px]">
            <div className="flex justify-between items-center mb-2">
                <h3 className="text-xs font-black text-brand-400 uppercase tracking-widest">{title}</h3>
                <div className="flex bg-black/40 p-1 rounded-lg border border-white/5">
                    <button 
                        onClick={() => setFilter({ ...filter, label: 'CI', ids: [] })}
                        className={`px-3 py-1 text-[9px] font-black rounded-md transition-all ${filter.label === 'CI' ? 'bg-brand-500 text-black' : 'text-neutral-500 hover:text-white'}`}
                    >
                        NODES
                    </button>
                    <button 
                        onClick={() => setFilter({ ...filter, label: 'MetricDef', ids: [] })}
                        className={`px-3 py-1 text-[9px] font-black rounded-md transition-all ${filter.label === 'MetricDef' ? 'bg-brand-500 text-black' : 'text-neutral-500 hover:text-white'}`}
                    >
                        METRICS
                    </button>
                </div>
            </div>

            <div className="space-y-3 shrink-0">
                {filter.label === 'CI' ? (
                    <div className="grid grid-cols-2 gap-2">
                        <label className="block">
                            <span className="text-[9px] font-black text-neutral-600 uppercase mb-1 block">Layer</span>
                            <select 
                                className="w-full bg-neutral-950 border border-white/5 rounded-lg px-3 py-2 text-xs text-white outline-none focus:border-brand-500"
                                value={filter.layer}
                                onChange={(e) => setFilter({ ...filter, layer: e.target.value })}
                            >
                                <option value="">All Layers</option>
                                {categories?.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
                            </select>
                        </label>
                        <label className="block">
                            <span className="text-[9px] font-black text-neutral-600 uppercase mb-1 block">Brand</span>
                            <select 
                                className="w-full bg-neutral-950 border border-white/5 rounded-lg px-3 py-2 text-xs text-white outline-none focus:border-brand-500"
                                value={filter.brand}
                                onChange={(e) => setFilter({ ...filter, brand: e.target.value, model: '' })}
                            >
                                <option value="">All Brands</option>
                                {uniqueBrands.map(b => <option key={b} value={b}>{b}</option>)}
                            </select>
                        </label>
                        <label className="block">
                            <span className="text-[9px] font-black text-neutral-600 uppercase mb-1 block">Model</span>
                            <select 
                                className="w-full bg-neutral-950 border border-white/5 rounded-lg px-3 py-2 text-xs text-white outline-none focus:border-brand-500"
                                value={filter.model}
                                onChange={(e) => setFilter({ ...filter, model: e.target.value })}
                            >
                                <option value="">All Models</option>
                                {availableModels?.map(m => <option key={m} value={m}>{m}</option>)}
                            </select>
                        </label>
                        <label className="block">
                            <span className="text-[9px] font-black text-neutral-600 uppercase mb-1 block">Quick Search</span>
                            <div className="relative">
                                <input 
                                    className="w-full bg-neutral-950 border border-white/5 rounded-lg pl-8 pr-3 py-2 text-xs text-white outline-none focus:border-brand-500 font-bold placeholder:text-neutral-700"
                                    value={filter.searchTerm}
                                    onChange={(e) => setFilter({ ...filter, searchTerm: e.target.value })}
                                    placeholder="IP, Name, Loc..."
                                />
                                <span className="material-symbols-outlined absolute left-2 top-1/2 -translate-y-1/2 text-sm text-neutral-600">search</span>
                            </div>
                        </label>
                    </div>
                ) : (
                    <label className="block">
                        <span className="text-[10px] font-bold text-neutral-500 uppercase mb-1 block">Select Metric Definition</span>
                        <select 
                            className="w-full bg-neutral-950 border border-white/5 rounded-lg px-3 py-2 text-xs text-white outline-none focus:border-brand-500"
                            value={filter.id}
                            onChange={(e) => setFilter({ ...filter, id: e.target.value, ids: [] })}
                        >
                            <option value="">-- Choose a Metric --</option>
                            {metrics?.map(m => <option key={m.id} value={m.id}>{m.id} ({m.protocol})</option>)}
                        </select>
                    </label>
                )}
            </div>

            {/* Granular Picker Section */}
            {filter.label === 'CI' && availableNodes && availableNodes.length > 0 && (
                <div className="flex-1 flex flex-col min-h-0 bg-black/20 rounded-xl border border-white/5 overflow-hidden mt-4">
                    <div className="p-2 border-b border-white/5 bg-white/5 flex justify-between items-center">
                        <span className="text-[9px] font-black text-neutral-500 uppercase tracking-widest">{availableNodes.length} Assets Found</span>
                        <button onClick={selectAll} className="text-[9px] font-black text-brand-400 hover:text-brand-300 uppercase">Select All</button>
                    </div>
                    <div className="flex-1 overflow-y-auto custom-scrollbar p-2 space-y-1">
                        {availableNodes.map(node => (
                            <label key={node.id} className={`flex items-center gap-3 p-2 rounded-lg cursor-pointer transition-colors ${filter.ids.includes(node.id) ? 'bg-brand-500/10 border border-brand-500/20' : 'hover:bg-white/5 border border-transparent'}`}>
                                <input 
                                    type="checkbox" 
                                    className="w-3 h-3 rounded bg-neutral-900 border-white/10 checked:bg-brand-500" 
                                    checked={filter.ids.includes(node.id)}
                                    onChange={() => toggleId(node.id)}
                                />
                                <div className="flex flex-col min-w-0">
                                    <span className="text-[11px] font-bold text-white truncate">{node.label}</span>
                                    <span className="text-[9px] text-neutral-500 font-mono truncate">{node.id} • {node.ip || 'No IP'} • {node.location_name}</span>
                                </div>
                            </label>
                        ))}
                    </div>
                    {filter.ids.length > 0 && (
                        <div className="p-2 bg-brand-500/20 border-t border-brand-500/30 text-center">
                            <span className="text-[9px] font-black text-brand-400 uppercase">{filter.ids.length} Explicitly Selected</span>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

const MassLinkEditor: React.FC = () => {
    const initialFilter: FilterState = { label: 'CI', layer: '', brand: '', model: '', searchTerm: '', id: '', ids: [] };
    
    const [sourceFilter, setSourceFilter] = useState<FilterState>({ ...initialFilter });
    const [targetFilter, setTargetFilter] = useState<FilterState>({ ...initialFilter });
    const [relationship, setRelationship] = useState('DEPENDS_ON');
    const [newRelationship, setNewRelationship] = useState('DEPENDS_ON');
    const [simulation, setSimulation] = useState<any>(null);
    const [loading, setLoading] = useState(false);

    const { data: categories } = useCategoriesQuery();
    const { data: metrics } = useQuery({ queryKey: ['metrics'], queryFn: () => api.get<any[]>('/metrics') });
    const { data: allNodes } = useQuery({ queryKey: ['nodes'], queryFn: () => api.get<any[]>('/nodes') });
    const { data: hardwareModels } = useQuery({ queryKey: ['hardware'], queryFn: () => api.get<any[]>('/hardware') });

    const filterNodes = (filter: FilterState) => {
        if (!allNodes) return [];
        return allNodes.filter(n => {
            // Label filtering
            const isMetric = n._labels?.includes('MetricDef');
            if (filter.label === 'MetricDef' && !isMetric) return false;
            if (filter.label === 'CI' && isMetric) return false;

            const matchesLayer = !filter.layer || n.type === filter.layer;
            const matchesBrand = !filter.brand || n.brand === filter.brand;
            const matchesModel = !filter.model || n.model === filter.model;
            
            const s = filter.searchTerm.toLowerCase();
            const matchesSearch = !filter.searchTerm || 
                n.label?.toLowerCase().includes(s) || 
                n.id?.toLowerCase().includes(s) || 
                n.ip?.includes(s) ||
                n.location_name?.toLowerCase().includes(s) ||
                n.brand?.toLowerCase().includes(s) || // Added brand search
                n.model?.toLowerCase().includes(s);    // Added model search
                
            return matchesLayer && matchesBrand && matchesModel && matchesSearch;
        });
    };

    const sourceAvailable = useMemo(() => filterNodes(sourceFilter), [allNodes, sourceFilter.layer, sourceFilter.brand, sourceFilter.model, sourceFilter.searchTerm]);
    const targetAvailable = useMemo(() => filterNodes(targetFilter), [allNodes, targetFilter.layer, targetFilter.brand, targetFilter.model, targetFilter.searchTerm]);

    const handleReset = () => {
        setSourceFilter({ ...initialFilter });
        setTargetFilter({ ...initialFilter });
        setRelationship('DEPENDS_ON');
        setNewRelationship('DEPENDS_ON');
        setSimulation(null);
    };

    useEffect(() => {
        if (targetFilter.label === 'MetricDef') {
            setRelationship('HAS_METRIC');
            setNewRelationship('HAS_METRIC');
        } else if (relationship === 'HAS_METRIC') {
            setRelationship('DEPENDS_ON');
            setNewRelationship('DEPENDS_ON');
        }
    }, [targetFilter.label]);

    const handleSimulate = async () => {
        setLoading(true);
        setSimulation(null);
        try {
            const result = await api.post<any>('/links/mass/simulate', {
                source_filter: sourceFilter,
                target_filter: targetFilter,
                relationship
            });
            setSimulation(result);
        } catch (e: any) {
            alert("Simulation failed: " + e.message);
        } finally {
            setLoading(false);
        }
    };

    const handleExecute = async () => {
        if (!simulation?.is_safe) return;
        setLoading(true);
        try {
            const result = await api.post<any>('/links/mass', {
                source_filter: sourceFilter,
                target_filter: targetFilter,
                relationship
            });
            alert(result.message);
            setSimulation(null);
        } catch (e: any) {
            alert("Execution failed: " + (e.response?.data?.detail || e.message));
        } finally {
            setLoading(false);
        }
    };

    const handleMassDelete = async () => {
        if (!simulation || simulation.potential_links === 0) return;
        if (!confirm(`CAUTION: This will delete ALL ${relationship} links between the selected sets. Are you sure?`)) return;
        setLoading(true);
        try {
            await api.delete<any>('/links/mass', { source_filter: sourceFilter, target_filter: targetFilter, relationship });
            alert("Mass deletion successful");
            setSimulation(null);
        } catch (e: any) {
            alert("Mass deletion failed: " + e.message);
        } finally {
            setLoading(false);
        }
    };

    const handleMassUpdate = async () => {
        if (!simulation || simulation.potential_links === 0) return;
        if (relationship === newRelationship) return alert("The target relationship type is the same as the current one.");
        if (!confirm(`This will change ALL ${relationship} links to ${newRelationship} for the selected sets. Continue?`)) return;
        setLoading(true);
        try {
            await api.put<any>('/links/mass', { source_filter: sourceFilter, target_filter: targetFilter, old_relationship: relationship, new_relationship: newRelationship });
            alert("Mass update successful");
            setSimulation(null);
        } catch (e: any) {
            alert("Mass update failed: " + e.message);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="h-full flex flex-col p-4 overflow-hidden border border-white/5 bg-neutral-950/20">
            <div className="flex justify-between items-end mb-4 shrink-0">
                <div>
                    <h2 className="text-2xl font-black text-white tracking-tighter uppercase italic">Granular Orchestrator</h2>
                    <p className="text-neutral-500 text-[10px] font-bold uppercase tracking-widest">Global search and explicit selection for precise topology control.</p>
                </div>
                <button onClick={handleReset} className="flex items-center gap-2 px-3 py-1.5 bg-white/5 hover:bg-white/10 text-neutral-400 hover:text-white rounded-lg text-[10px] font-bold transition-all border border-white/5">
                    <span className="material-symbols-outlined text-xs">restart_alt</span>
                    RESET
                </button>
            </div>

            <div className="flex-1 flex gap-6 min-h-0 overflow-hidden mb-6">
                <FilterPanel 
                    title="Source Selection" 
                    filter={sourceFilter} 
                    setFilter={setSourceFilter} 
                    categories={categories}
                    metrics={metrics}
                    availableNodes={sourceAvailable}
                    hardwareModels={hardwareModels}
                />
                
                <div className="flex flex-col justify-center items-center px-2 shrink-0">
                    <div className="w-px h-full bg-gradient-to-b from-transparent via-white/10 to-transparent"></div>
                    <span className="material-symbols-outlined text-brand-500 my-4 text-3xl">hub</span>
                    <div className="w-px h-full bg-gradient-to-t from-transparent via-white/10 to-transparent"></div>
                </div>

                <FilterPanel 
                    title="Target Selection" 
                    filter={targetFilter} 
                    setFilter={setTargetFilter} 
                    categories={categories}
                    metrics={metrics}
                    availableNodes={targetAvailable}
                    hardwareModels={hardwareModels}
                />
            </div>

            <div className="bg-neutral-900/80 backdrop-blur p-6 rounded-3xl border border-brand-500/20 shadow-2xl space-y-4 shrink-0">
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-6">
                        <label>
                            <span className="text-[9px] font-black text-neutral-500 uppercase mb-1 block">Relationship Type</span>
                            <select 
                                className="bg-neutral-950 border border-white/10 rounded-xl px-4 py-2 text-xs text-brand-400 font-black outline-none focus:border-brand-500 transition-all"
                                value={relationship}
                                onChange={(e) => setRelationship(e.target.value)}
                            >
                                <option value="DEPENDS_ON">DEPENDS ON</option>
                                <option value="CONNECTS_TO">CONNECTS TO</option>
                                <option value="HOSTED_ON">HOSTED ON</option>
                                <option value="HAS_METRIC">HAS METRIC</option>
                            </select>
                        </label>

                        {simulation && simulation.potential_links > 0 && targetFilter.label === 'CI' && (
                            <div className="flex items-center gap-3 animate-in slide-in-from-left duration-300 border-l border-white/10 pl-6">
                                <span className="material-symbols-outlined text-neutral-600 text-sm">arrow_forward</span>
                                <label>
                                    <span className="text-[9px] font-black text-neutral-500 uppercase mb-1 block">New Type (Update)</span>
                                    <select 
                                        className="bg-neutral-950 border border-brand-500/50 rounded-xl px-4 py-2 text-xs text-brand-400 font-black outline-none focus:border-brand-500 transition-all"
                                        value={newRelationship}
                                        onChange={(e) => setNewRelationship(e.target.value)}
                                    >
                                        <option value="DEPENDS_ON">DEPENDS ON</option>
                                        <option value="CONNECTS_TO">CONNECTS TO</option>
                                        <option value="HOSTED_ON">HOSTED ON</option>
                                        <option value="HAS_METRIC">HAS METRIC</option>
                                    </select>
                                </label>
                            </div>
                        )}
                    </div>

                    <div className="flex gap-3">
                        <button onClick={handleSimulate} disabled={loading} className="px-6 py-2.5 bg-white/5 hover:bg-white/10 text-white rounded-xl text-[10px] font-black transition-all uppercase tracking-widest border border-white/5">
                            {loading ? '...' : 'SIMULATE'}
                        </button>
                        
                        {simulation && (
                            <button 
                                onClick={handleExecute}
                                disabled={loading || !simulation.is_safe || simulation.potential_links === 0}
                                className={`px-6 py-2.5 rounded-xl text-[10px] font-black transition-all uppercase tracking-widest shadow-lg ${
                                    simulation.is_safe && simulation.potential_links > 0 ? 'bg-brand-600 hover:bg-brand-500 text-white' : 'bg-red-500/20 text-red-500 border border-red-500/20'
                                }`}
                            >
                                {simulation.potential_links > 0 ? `EXECUTE ${simulation.potential_links}` : 'NO MATCH'}
                            </button>
                        )}

                        {simulation && simulation.potential_links > 0 && (
                            <>
                                <button onClick={handleMassUpdate} className="px-6 py-2.5 bg-brand-400/10 hover:bg-brand-400/20 text-brand-400 border border-brand-400/30 rounded-xl text-[10px] font-black transition-all uppercase tracking-widest">UPDATE</button>
                                <button onClick={handleMassDelete} className="px-6 py-2.5 bg-red-500/10 hover:bg-red-500/20 text-red-500 border border-red-500/30 rounded-xl text-[10px] font-black transition-all uppercase tracking-widest">DELETE</button>
                            </>
                        )}
                    </div>
                </div>

                {simulation && (
                    <div className={`p-4 rounded-xl border animate-in slide-in-from-top duration-300 ${simulation.is_safe ? 'bg-green-500/5 border-green-500/20' : 'bg-red-500/5 border-red-500/20'}`}>
                        <div className="flex items-center gap-8">
                            <div className="text-center p-2 bg-black/20 rounded-lg border border-white/5 min-w-[100px]">
                                <p className="text-[8px] text-neutral-500 uppercase font-black">Potential Links</p>
                                <p className="text-lg font-black text-brand-400">{simulation.potential_links}</p>
                            </div>
                            <div className="flex-1 text-[10px] text-neutral-400 leading-tight">
                                {simulation.message || "Rules applied successfully based on current granular selection."}
                            </div>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};

export default MassLinkEditor;
