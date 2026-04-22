import React, { useState } from 'react';
import { api } from '../services/api';
import { useCategoriesQuery } from '../hooks/queries/useCategoriesQuery';
import { useQuery } from '@tanstack/react-query';

interface MassAssetCreatorProps {
    onClose: () => void;
    onRefresh: () => void;
}

const MassAssetCreator: React.FC<MassAssetCreatorProps> = ({ onClose, onRefresh }) => {
    const [entitiesText, setEntitiesText] = useState('');
    const [template, setTemplate] = useState({
        type: '',
        brand: '',
        model: '',
        location_name: '',
        owner: '',
        pollingInterval: 60
    });
    const [loading, setLoading] = useState(false);

    const { data: categories } = useCategoriesQuery();
    const { data: hardware } = useQuery({
        queryKey: ['hardware-catalog'],
        queryFn: () => api.get<any[]>('/hardware')
    });
    const { data: owners } = useQuery({
        queryKey: ['owners'],
        queryFn: () => api.get<any[]>('/owners')
    });

    const handleExecute = async () => {
        const lines = entitiesText.split('\n').map(l => l.trim()).filter(l => l !== '');
        if (lines.length === 0) return alert('Please enter at least one CI name or IP.');
        if (!template.type) return alert('Please select a Category/Layer.');

        const entities = lines.map(line => {
            const parts = line.split(',');
            return {
                name: parts[0].trim(),
                ip: parts[1]?.trim() || parts[0].trim() // Use name as IP if only one part
            };
        });

        setLoading(true);
        try {
            const result: any = await api.post('/nodes/mass', {
                entities,
                template
            });
            alert(result.message);
            onRefresh();
            onClose();
        } catch (e: any) {
            alert('Mass creation failed: ' + e.message);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="flex flex-col h-full bg-neutral-900 border-l border-white/5 animate-in slide-in-from-right duration-500">
            <header className="p-6 border-b border-white/5 flex justify-between items-center bg-black/20">
                <div>
                    <h3 className="text-xl font-black text-white uppercase tracking-tighter">Mass Asset Creator</h3>
                    <p className="text-[10px] font-bold text-neutral-500 uppercase tracking-widest">Rapid CI Deployment</p>
                </div>
                <button onClick={onClose} className="p-2 hover:bg-white/5 rounded-full text-neutral-500 hover:text-white transition-all">
                    <span className="material-symbols-outlined">close</span>
                </button>
            </header>

            <div className="flex-1 overflow-y-auto custom-scrollbar p-6 space-y-6">
                {/* Step 1: Template Selection */}
                <section className="space-y-4">
                    <h4 className="text-[10px] font-black text-brand-400 uppercase tracking-[0.2em] border-b border-brand-500/20 pb-2">1. Set Base Template</h4>
                    <div className="grid grid-cols-2 gap-4">
                        <label className="block">
                            <span className="text-[10px] font-bold text-neutral-500 uppercase mb-1 block">Technology / Layer</span>
                            <select 
                                className="w-full bg-neutral-950 border border-white/5 rounded-lg px-3 py-2 text-xs text-white outline-none focus:border-brand-500"
                                value={template.type}
                                onChange={e => setTemplate({ ...template, type: e.target.value })}
                            >
                                <option value="">Select Layer...</option>
                                {categories?.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
                            </select>
                        </label>
                        <label className="block">
                            <span className="text-[10px] font-bold text-neutral-500 uppercase mb-1 block">Hardware Model</span>
                            <select 
                                className="w-full bg-neutral-950 border border-white/5 rounded-lg px-3 py-2 text-xs text-white outline-none focus:border-brand-500"
                                value={`${template.brand}|${template.model}`}
                                onChange={e => {
                                    const [brand, model] = e.target.value.split('|');
                                    setTemplate({ ...template, brand, model });
                                }}
                            >
                                <option value="|">Select Model...</option>
                                {hardware?.map(h => <option key={`${h.brand}-${h.model}`} value={`${h.brand}|${h.model}`}>{h.brand} {h.model}</option>)}
                            </select>
                        </label>
                        <label className="block">
                            <span className="text-[10px] font-bold text-neutral-500 uppercase mb-1 block">Location</span>
                            <input 
                                className="w-full bg-neutral-950 border border-white/5 rounded-lg px-3 py-2 text-xs text-white outline-none focus:border-brand-500"
                                value={template.location_name}
                                onChange={e => setTemplate({ ...template, location_name: e.target.value })}
                                placeholder="e.g. Data Center A"
                            />
                        </label>
                        <label className="block">
                            <span className="text-[10px] font-bold text-neutral-500 uppercase mb-1 block">Owner Group</span>
                            <select 
                                className="w-full bg-neutral-950 border border-white/5 rounded-lg px-3 py-2 text-xs text-white outline-none focus:border-brand-500"
                                value={template.owner}
                                onChange={e => setTemplate({ ...template, owner: e.target.value })}
                            >
                                <option value="">Select Owner...</option>
                                {owners?.map(o => <option key={o.name} value={o.name}>{o.name}</option>)}
                            </select>
                        </label>
                    </div>
                </section>

                {/* Step 2: Entity Input */}
                <section className="space-y-4">
                    <h4 className="text-[10px] font-black text-brand-400 uppercase tracking-[0.2em] border-b border-brand-500/20 pb-2">2. Enter Entities</h4>
                    <p className="text-[10px] text-neutral-500 leading-relaxed italic">
                        Enter one CI per line. Format: <code className="text-neutral-300">Name, IP</code> (IP is optional).
                    </p>
                    <textarea 
                        className="w-full h-64 bg-neutral-950 border border-white/5 rounded-2xl p-4 text-xs font-mono text-white outline-none focus:border-brand-500 custom-scrollbar"
                        placeholder="ROUTER-MAD-01, 10.0.0.1&#10;ROUTER-MAD-02, 10.0.0.2"
                        value={entitiesText}
                        onChange={e => setEntitiesText(e.target.value)}
                    />
                </section>
            </div>

            <footer className="p-6 border-t border-white/5 bg-black/20">
                <button 
                    onClick={handleExecute}
                    disabled={loading || !template.type || !entitiesText.trim()}
                    className="w-full py-4 bg-brand-600 hover:bg-brand-500 disabled:opacity-30 disabled:hover:bg-brand-600 text-white rounded-2xl text-xs font-black transition-all shadow-xl shadow-brand-900/20 uppercase tracking-[0.2em]"
                >
                    {loading ? 'Processing Queue...' : 'Deploy Assets Now'}
                </button>
            </footer>
        </div>
    );
};

export default MassAssetCreator;
