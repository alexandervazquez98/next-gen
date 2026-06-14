import React, { useState, useEffect } from 'react';
import { MetricDef } from '../types';
import CategoryIcon from './CategoryIcon';

interface HardwareModel {
    brand: string;
    model: string;
    category?: string;
    owner?: string;
}

const HardwareCatalog: React.FC = () => {
    const [models, setModels] = useState<HardwareModel[]>([]);
    const [categories, setCategories] = useState<{ name: string; icon_key?: string | null }[]>([]);
    const [owners, setOwners] = useState<{ name: string }[]>([]);

    // Form State
    const [newModel, setNewModel] = useState<Partial<HardwareModel>>({});

    useEffect(() => {
        fetchData();
    }, []);

    const fetchData = async () => {
        try {
            const [resModels, resCats, resOwners] = await Promise.all([
                fetch('/api/hardware'),
                fetch('/api/categories'),
                fetch('/api/owners')
            ]);
            setModels(await resModels.json());
            setCategories(await resCats.json());
            setOwners(await resOwners.json());
        } catch (e) {
            console.error(e);
        }
    };

    const handleCreate = async () => {
        if (!newModel.brand || !newModel.model) return alert("Brand and Model required");

        try {
            await fetch('/api/hardware', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(newModel)
            });
            setNewModel({});
            fetchData();
        } catch (e) {
            alert("Error creating model");
        }
    };

    const handleDelete = async (m: HardwareModel) => {
        try {
            const res = await fetch(`/api/hardware/${m.brand}/${m.model}/usage`);
            const usage = await res.json();
            const count = usage.count || 0;

            const msg = `Delete Hardware Model '${m.brand} ${m.model}'?\n\n` +
                `There are currently ${count} CIs of this model in the inventory.\n` +
                (count > 0 ? `These CIs will remain but will be unlinked from the official catalog.\n\n` : `\n`) +
                `Proceed with deletion?`;

            if (!confirm(msg)) return;

            await fetch(`/api/hardware/${m.brand}/${m.model}`, { method: 'DELETE' });
            fetchData();
        } catch (e) {
            alert("Error checking usage");
        }
    };

    return (
        <div className="h-full flex flex-col p-6">
            <h2 className="text-3xl font-black text-white tracking-tighter uppercase mb-6">Hardware Catalog</h2>

            <div className="flex gap-6 h-full">
                {/* Creation Form */}
                <div className="w-1/3 glass p-6 rounded-2xl border border-white/5 h-fit">
                    <h3 className="font-bold text-white uppercase tracking-wider text-sm mb-4">Register New Hardware</h3>

                    <div className="space-y-4">
                        <div className="space-y-2">
                            <label className="text-xs font-bold text-neutral-500 uppercase">Brand</label>
                            <input className="input-field w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                                placeholder="e.g. Cisco" value={newModel.brand || ''} onChange={e => setNewModel({ ...newModel, brand: e.target.value })} />
                        </div>
                        <div className="space-y-2">
                            <label className="text-xs font-bold text-neutral-500 uppercase">Model</label>
                            <input className="input-field w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                                placeholder="e.g. Catalyst 9300" value={newModel.model || ''} onChange={e => setNewModel({ ...newModel, model: e.target.value })} />
                        </div>

                        <div className="grid grid-cols-2 gap-4">
                            <div className="space-y-2">
                                <label className="text-xs font-bold text-neutral-500 uppercase">Category</label>
                                <select className="w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                                    value={newModel.category || ''} onChange={e => setNewModel({ ...newModel, category: e.target.value })}>
                                    <option value="">Select...</option>
                                    {categories.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
                                </select>
                            </div>
                            <div className="space-y-2">
                                <label className="text-xs font-bold text-neutral-500 uppercase">Default Owner</label>
                                <select className="w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                                    value={newModel.owner || ''} onChange={e => setNewModel({ ...newModel, owner: e.target.value })}>
                                    <option value="">Select...</option>
                                    {owners.map(o => <option key={o.name} value={o.name}>{o.name}</option>)}
                                </select>
                            </div>
                        </div>

                        <button onClick={handleCreate} className="w-full bg-brand-600 hover:bg-brand-500 text-white font-bold py-3 rounded-xl transition-colors mt-4">
                            ADD TO CATALOG
                        </button>
                    </div>
                </div>

                {/* List */}
                <div className="flex-1 glass rounded-2xl border border-white/5 overflow-hidden flex flex-col">
                    <div className="p-4 border-b border-white/5 bg-black/20 flex justify-between items-center">
                        <h3 className="font-bold text-white uppercase tracking-wider text-sm">Registered Models</h3>
                        <span className="text-xs text-neutral-500">{models.length} items</span>
                    </div>

                    <div className="flex-1 overflow-y-auto custom-scrollbar p-2 space-y-2">
                        {models.length === 0 && (
                            <div className="text-center text-neutral-500 py-10">No models registered yet.</div>
                        )}
                        {models.map((m, i) => (
                            <div key={i} className="p-4 rounded-xl border border-white/5 bg-white/5 flex justify-between items-center hover:bg-white/10 transition-colors">
                                <div>
                                    <div className="flex items-center gap-2">
                                        <span className="font-bold text-white">{m.brand}</span>
                                        <span className="text-neutral-400">{m.model}</span>
                                    </div>
                                    <div className="flex gap-2 mt-2">
                                        {m.category && (
                                            <span className="text-[10px] bg-brand-500/20 text-brand-300 px-2 py-0.5 rounded uppercase tracking-wider inline-flex items-center gap-1">
                                                <CategoryIcon
                                                    className="text-[11px]"
                                                    iconKey={categories.find((c) => c.name === m.category)?.icon_key}
                                                    categoryName={m.category}
                                                />
                                                {m.category}
                                            </span>
                                        )}
                                        {m.owner && <span className="text-[10px] bg-neutral-700 text-neutral-300 px-2 py-0.5 rounded uppercase tracking-wider">{m.owner}</span>}
                                    </div>
                                </div>
                                <button onClick={() => handleDelete(m)} className="text-neutral-600 hover:text-red-500 p-2">
                                    <span className="material-symbols-outlined">delete</span>
                                </button>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    );
};

export default HardwareCatalog;
