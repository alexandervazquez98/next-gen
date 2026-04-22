import React, { useState } from 'react';
import { api } from '../services/api';
import { useCategoriesQuery } from '../hooks/queries/useCategoriesQuery';
import { useQuery } from '@tanstack/react-query';

interface FilterState {
    label: 'CI' | 'MetricDef';
    layer: string;
    location: string;
    name: string;
    id: string;
}

interface FilterPanelProps {
    title: string;
    filter: FilterState;
    setFilter: (f: FilterState) => void;
    categories?: any[];
    metrics?: any[];
}

const FilterPanel: React.FC<FilterPanelProps> = ({ title, filter, setFilter, categories, metrics }) => (
    <div className="flex-1 p-6 bg-neutral-900/50 border border-white/5 rounded-2xl space-y-4">
        <div className="flex justify-between items-center mb-2">
            <h3 className="text-xs font-black text-brand-400 uppercase tracking-widest">{title}</h3>
            <div className="flex bg-black/40 p-1 rounded-lg border border-white/5">
                <button 
                    onClick={() => setFilter({ ...filter, label: 'CI' })}
                    className={`px-3 py-1 text-[9px] font-black rounded-md transition-all ${filter.label === 'CI' ? 'bg-brand-500 text-black' : 'text-neutral-500 hover:text-white'}`}
                >
                    NODES (CI)
                </button>
                <button 
                    onClick={() => setFilter({ ...filter, label: 'MetricDef' })}
                    className={`px-3 py-1 text-[9px] font-black rounded-md transition-all ${filter.label === 'MetricDef' ? 'bg-brand-500 text-black' : 'text-neutral-500 hover:text-white'}`}
                >
                    METRICS
                </button>
            </div>
        </div>

        <div className="space-y-3">
            {filter.label === 'CI' ? (
                <>
                    <label className="block">
                        <span className="text-[10px] font-bold text-neutral-500 uppercase mb-1 block">Technology / Layer</span>
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
                        <span className="text-[10px] font-bold text-neutral-500 uppercase mb-1 block">Exact Name (Optional)</span>
                        <input 
                            className="w-full bg-neutral-950 border border-white/5 rounded-lg px-3 py-2 text-xs text-white outline-none focus:border-brand-500"
                            value={filter.name}
                            onChange={(e) => setFilter({ ...filter, name: e.target.value })}
                            placeholder="e.g. CORE-SW-01"
                        />
                    </label>
                    <label className="block">
                        <span className="text-[10px] font-bold text-neutral-400 uppercase mb-1 block">Location</span>
                        <input 
                            className="w-full bg-neutral-950 border border-white/5 rounded-lg px-3 py-2 text-xs text-white outline-none focus:border-brand-500"
                            value={filter.location}
                            onChange={(e) => setFilter({ ...filter, location: e.target.value })}
                            placeholder="Search by location..."
                        />
                    </label>
                </>
            ) : (
                <label className="block">
                    <span className="text-[10px] font-bold text-neutral-500 uppercase mb-1 block">Select Metric Definition</span>
                    <select 
                        className="w-full bg-neutral-950 border border-white/5 rounded-lg px-3 py-2 text-xs text-white outline-none focus:border-brand-500"
                        value={filter.id}
                        onChange={(e) => setFilter({ ...filter, id: e.target.value })}
                    >
                        <option value="">-- Choose a Metric --</option>
                        {metrics?.map(m => <option key={m.id} value={m.id}>{m.id} ({m.protocol})</option>)}
                    </select>
                </label>
            )}
        </div>
    </div>
);

const MassLinkEditor: React.FC = () => {
    const [sourceFilter, setSourceFilter] = useState<FilterState>({ label: 'CI', layer: '', location: '', name: '', id: '' });
    const [targetFilter, setTargetFilter] = useState<FilterState>({ label: 'CI', layer: '', location: '', name: '', id: '' });
    const [relationship, setRelationship] = useState('DEPENDS_ON');
    const [newRelationship, setNewRelationship] = useState('DEPENDS_ON');
    const [simulation, setSimulation] = useState<any>(null);
    const [loading, setLoading] = useState(false);

    const { data: categories } = useCategoriesQuery();
    const { data: metrics } = useQuery({
        queryKey: ['metrics'],
        queryFn: () => api.get<any[]>('/metrics')
    });

    // Auto-switch relationship to HAS_METRIC if target is a metric
    React.useEffect(() => {
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
            alert("Execution failed: " + e.message);
        } finally {
            setLoading(false);
        }
    };

    const handleMassDelete = async () => {
        if (!simulation || simulation.potential_links === 0) return;
        
        if (!confirm(`CAUTION: This will delete ALL ${relationship} links between the selected sets. Are you sure?`)) {
            return;
        }

        setLoading(true);
        try {
            const result = await api.delete<any>('/links/mass', {
                source_filter: sourceFilter,
                target_filter: targetFilter,
                relationship
            });
            alert(result.message);
            setSimulation(null);
        } catch (e: any) {
            alert("Mass deletion failed: " + e.message);
        } finally {
            setLoading(false);
        }
    };

    const handleMassUpdate = async () => {
        if (!simulation || simulation.potential_links === 0) return;
        if (relationship === newRelationship) {
            alert("The target relationship type is the same as the current one.");
            return;
        }
        
        if (!confirm(`This will change ALL ${relationship} links to ${newRelationship} for the selected sets. Continue?`)) {
            return;
        }

        setLoading(true);
        try {
            const result = await api.put<any>('/links/mass', {
                source_filter: sourceFilter,
                target_filter: targetFilter,
                old_relationship: relationship,
                new_relationship: newRelationship
            });
            alert(result.message);
            setSimulation(null);
        } catch (e: any) {
            alert("Mass update failed: " + e.message);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="p-8 space-y-8 animate-in fade-in duration-500">
            <div className="flex justify-between items-end">
                <div>
                    <h2 className="text-3xl font-black text-white tracking-tighter uppercase">Mass Topology Orchestrator</h2>
                    <p className="text-neutral-500 text-sm">Bind CIs to each other or link entire sets of nodes to Metric Definitions.</p>
                </div>
            </div>

            <div className="flex gap-6">
                <FilterPanel 
                    title="Source Set" 
                    filter={sourceFilter} 
                    setFilter={setSourceFilter} 
                    categories={categories}
                    metrics={metrics}
                />
                
                <div className="flex flex-col justify-center items-center px-4">
                    <div className="w-px h-12 bg-gradient-to-b from-transparent via-white/10 to-transparent"></div>
                    <span className="material-symbols-outlined text-brand-500 my-2">link</span>
                    <div className="w-px h-12 bg-gradient-to-t from-transparent via-white/10 to-transparent"></div>
                </div>

                <FilterPanel 
                    title="Target Set" 
                    filter={targetFilter} 
                    setFilter={setTargetFilter} 
                    categories={categories}
                    metrics={metrics}
                />
            </div>

            <div className="bg-neutral-900/80 backdrop-blur p-8 rounded-3xl border border-brand-500/20 shadow-2xl space-y-6">
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-8">
                        <label>
                            <span className="text-[10px] font-bold text-neutral-500 uppercase mb-1 block">Relationship Type</span>
                            <select 
                                aria-label="Relationship Type"
                                className="bg-neutral-950 border border-white/10 rounded-xl px-4 py-2 text-sm text-brand-400 font-black outline-none focus:border-brand-500 transition-all"
                                value={relationship}
                                onChange={(e) => setRelationship(e.target.value)}
                            >
                                <option value="DEPENDS_ON">DEPENDS ON</option>
                                <option value="CONNECTS_TO">CONNECTS TO</option>
                                <option value="HOSTED_ON">HOSTED ON</option>
                                <option value="HAS_METRIC">HAS METRIC (Monitoring)</option>
                            </select>
                        </label>

                        {simulation && simulation.potential_links > 0 && targetFilter.label === 'CI' && (
                            <div className="flex items-center gap-4 animate-in slide-in-from-left duration-300">
                                <span className="material-symbols-outlined text-neutral-600">arrow_forward</span>
                                <label>
                                    <span className="text-[10px] font-bold text-neutral-500 uppercase mb-1 block">New Relationship Type</span>
                                    <select 
                                        className="bg-neutral-950 border border-brand-500/50 rounded-xl px-4 py-2 text-sm text-brand-400 font-black outline-none focus:border-brand-500 transition-all"
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

                    <div className="flex gap-4">
                        <button 
                            onClick={handleSimulate}
                            disabled={loading}
                            className="px-8 py-3 bg-white/5 hover:bg-white/10 text-white rounded-2xl text-xs font-black transition-all uppercase tracking-widest border border-white/5 disabled:opacity-50"
                        >
                            {loading ? 'Processing...' : 'Simulate Voids'}
                        </button>
                        
                        {simulation && (
                            <button 
                                onClick={handleExecute}
                                disabled={loading || !simulation.is_safe || simulation.potential_links === 0}
                                className={`px-8 py-3 rounded-2xl text-xs font-black transition-all uppercase tracking-widest shadow-lg ${
                                    simulation.is_safe && simulation.potential_links > 0
                                    ? 'bg-brand-600 hover:bg-brand-500 text-white shadow-brand-900/20' 
                                    : 'bg-red-500/20 text-red-500 cursor-not-allowed border border-red-500/20'
                                }`}
                            >
                                {simulation.potential_links > 0 
                                    ? (simulation.is_safe ? `Execute ${simulation.potential_links} Links` : 'Unsafe Operation')
                                    : 'No Links Found'}
                            </button>
                        )}

                        {simulation && simulation.potential_links > 0 && (
                            <>
                                <button 
                                    onClick={handleMassUpdate}
                                    disabled={loading || relationship === newRelationship}
                                    className="px-8 py-3 bg-brand-400/10 hover:bg-brand-400/20 text-brand-400 border border-brand-400/30 rounded-2xl text-xs font-black transition-all uppercase tracking-widest disabled:opacity-30"
                                >
                                    Mass Update Type
                                </button>
                                <button 
                                    onClick={handleMassDelete}
                                    disabled={loading}
                                    className="px-8 py-3 bg-red-500/10 hover:bg-red-500/20 text-red-500 border border-red-500/30 rounded-2xl text-xs font-black transition-all uppercase tracking-widest"
                                >
                                    Mass Delete Links
                                </button>
                            </>
                        )}
                    </div>
                </div>

                {simulation && (
                    <div className={`p-6 rounded-2xl border animate-in slide-in-from-top duration-300 ${
                        simulation.is_safe ? 'bg-green-500/5 border-green-500/20' : 'bg-red-500/5 border-red-500/20'
                    }`}>
                        <div className="flex items-start gap-4">
                            <span className={`material-symbols-outlined ${simulation.is_safe ? 'text-green-400' : 'text-red-400'}`}>
                                {simulation.is_safe ? 'task_alt' : 'warning'}
                            </span>
                            <div>
                                <p className="text-sm font-bold text-white">Simulation Summary</p>
                                <p className="text-xs text-neutral-400 mt-1">{simulation.message}</p>
                                <div className="mt-4 flex flex-wrap gap-8">
                                    <div className="text-center p-3 bg-black/20 rounded-xl border border-white/5 min-w-[120px]">
                                        <p className="text-[10px] text-neutral-500 uppercase font-black">Potential Links</p>
                                        <p className="text-xl font-black text-brand-400">{simulation.potential_links}</p>
                                    </div>
                                    
                                    {simulation.source_samples?.length > 0 && (
                                        <div className="p-3 bg-black/20 rounded-xl border border-white/5 max-w-[200px]">
                                            <p className="text-[10px] text-neutral-500 uppercase font-black mb-1">Source Samples</p>
                                            <div className="flex flex-wrap gap-1">
                                                {simulation.source_samples.map((s: string) => (
                                                    <span key={s} className="text-[9px] px-1.5 py-0.5 bg-white/5 rounded text-neutral-300">{s}</span>
                                                ))}
                                            </div>
                                        </div>
                                    )}

                                    {simulation.target_samples?.length > 0 && (
                                        <div className="p-3 bg-black/20 rounded-xl border border-white/5 max-w-[200px]">
                                            <p className="text-[10px] text-neutral-500 uppercase font-black mb-1">Target Samples</p>
                                            <div className="flex flex-wrap gap-1">
                                                {simulation.target_samples.map((s: string) => (
                                                    <span key={s} className="text-[9px] px-1.5 py-0.5 bg-white/5 rounded text-neutral-300">{s}</span>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                </div>
                            </div>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};

export default MassLinkEditor;
