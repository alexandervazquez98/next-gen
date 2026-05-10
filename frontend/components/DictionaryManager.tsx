import React, { useState, useEffect } from 'react';
import { api } from '../services/api';
import DictionaryBulkUpload from './DictionaryBulkUpload';

interface MetricDef {
    id: string;
    protocol?: string;
    oid?: string;
    warning?: number | null;
    critical?: number | null;
    dataType?: string;
    unit?: string;
    description?: string;
    criticality?: 1 | 2 | 3;
    operator?: string;
    applicable_to?: ApplicabilityCriteria;
}

interface ApplicabilityCriteria {
    brands?: string[];
    models?: string[];
    layers?: string[];
    names?: string[];
    excluded_names?: string[];
}

interface DictionaryItem {
    id: string;
    name: string;
    brand: string;
    model: string;
    metric_ids: string[];
    polling_interval: number;
    created_at?: string;
    updated_at?: string;
}

interface DictionaryManagerProps {
    onClose?: () => void;
}

const DictionaryManager: React.FC<DictionaryManagerProps> = ({ onClose }) => {
    const [dictionaries, setDictionaries] = useState<DictionaryItem[]>([]);
    const [loading, setLoading] = useState(false);
    const [selectedDictionary, setSelectedDictionary] = useState<DictionaryItem | null>(null);
    const [isEditing, setIsEditing] = useState(false);
    const [showBulkUpload, setShowBulkUpload] = useState(false);

    // Form State
    const [formData, setFormData] = useState<Partial<DictionaryItem>>({});
    const [selectedMetricIds, setSelectedMetricIds] = useState<string[]>([]);

    // Metric definitions for selection
    const [allMetrics, setAllMetrics] = useState<MetricDef[]>([]);
    const [filterBrand, setFilterBrand] = useState('');

    useEffect(() => {
        fetchDictionaries();
        fetchMetrics();
    }, []);

    const fetchDictionaries = async () => {
        setLoading(true);
        try {
            const data = await api.get<DictionaryItem[]>('/dictionaries');
            setDictionaries(Array.isArray(data) ? data : []);
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    };

    const fetchMetrics = async () => {
        try {
            const data = await api.get<MetricDef[]>('/metrics');
            setAllMetrics(Array.isArray(data) ? data : []);
        } catch (e) {
            console.error(e);
        }
    };

    const handleEdit = (dictionary: DictionaryItem) => {
        setSelectedDictionary(dictionary);
        setFormData(dictionary);
        setSelectedMetricIds(dictionary.metric_ids || []);
        setIsEditing(true);
    };

    const handleCreate = () => {
        setSelectedDictionary(null);
        setFormData({
            id: '',
            name: '',
            brand: '',
            model: '',
            metric_ids: [],
            polling_interval: 60
        });
        setSelectedMetricIds([]);
        setIsEditing(true);
    };

    const handleSave = async () => {
        if (!formData.id || !formData.name || !formData.brand || !formData.model) {
            alert('ID, Name, Brand, and Model are required');
            return;
        }

        const payload = {
            ...formData,
            metric_ids: selectedMetricIds,
            polling_interval: formData.polling_interval ?? 60,
        };

        try {
            if (selectedDictionary) {
                await api.put(`/dictionaries/${selectedDictionary.id}`, {
                    name: formData.name,
                    brand: formData.brand,
                    model: formData.model,
                    metric_ids: selectedMetricIds,
                    polling_interval: formData.polling_interval ?? 60,
                });
                alert('Dictionary Updated');
            } else {
                await api.post('/dictionaries', payload);
                alert('Dictionary Created');
            }
            setIsEditing(false);
            setFormData({});
            setSelectedMetricIds([]);
            fetchDictionaries();
        } catch (e: any) {
            const msg = e?.response?.data?.detail || e?.message || 'Error saving dictionary';
            alert(msg);
        }
    };

    const handleDelete = async (dictionary: DictionaryItem) => {
        if (!confirm(`Delete dictionary '${dictionary.name}'? This will also remove all AppliedDictionary nodes.`)) return;

        try {
            await api.delete(`/dictionaries/${dictionary.id}`);
            if (selectedDictionary?.id === dictionary.id) {
                setSelectedDictionary(null);
                setIsEditing(false);
            }
            fetchDictionaries();
        } catch (e) {
            alert('Error deleting dictionary');
        }
    };

    const toggleMetric = (metricId: string) => {
        setSelectedMetricIds(prev =>
            prev.includes(metricId)
                ? prev.filter(id => id !== metricId)
                : [...prev, metricId]
        );
    };

    // Get unique brands from metrics' applicable_to
    const availableBrands = Array.from(
        new Set(
            allMetrics
                .flatMap(m => m.applicable_to?.brands || [])
        )
    ).sort();

    // Filter metrics by selected brand (from formData.brand)
    const filteredMetrics = filterBrand
        ? allMetrics.filter(m =>
            m.applicable_to?.brands?.includes(filterBrand)
          )
        : allMetrics;

    return (
        <div className="h-full flex gap-6">
            {/* Sidebar List */}
            <div className="w-1/3 glass rounded-2xl border border-white/5 flex flex-col overflow-hidden">
                <div className="p-4 border-b border-white/5 flex justify-between items-center bg-black/20">
                    <h3 className="font-bold text-white uppercase tracking-wider text-sm">Metric Dictionaries</h3>
                    <div className="flex gap-2">
                        <button onClick={() => setShowBulkUpload(true)} className="bg-cyan-900/40 hover:bg-cyan-800/40 text-cyan-400 rounded p-1" title="Bulk Upload">
                            <span className="material-symbols-outlined text-sm">upload</span>
                        </button>
                        <button onClick={handleCreate} className="bg-brand-600 hover:bg-brand-500 text-white rounded p-1">
                            <span className="material-symbols-outlined text-sm">add</span>
                        </button>
                    </div>
                </div>
                <div className="flex-1 overflow-y-auto custom-scrollbar p-2 space-y-2">
                    {loading ? (
                        <div className="text-center py-4 text-xs text-neutral-500">Loading...</div>
                    ) : dictionaries.length === 0 ? (
                        <div className="text-center py-4 text-xs text-neutral-500 italic">No dictionaries yet</div>
                    ) : (
                        dictionaries.map((d, i) => (
                            <div key={i} onClick={() => handleEdit(d)}
                                className={`p-3 rounded-lg border border-white/5 cursor-pointer hover:bg-white/5 transition-colors ${selectedDictionary?.id === d.id ? 'bg-brand-500/10 border-brand-500/50' : 'bg-transparent'}`}>
                                <div className="flex justify-between items-start">
                                    <span className="font-bold text-white text-sm">{d.name}</span>
                                    <span className="text-[10px] bg-white/10 px-1.5 rounded text-neutral-300">{d.metric_ids.length} metrics</span>
                                </div>
                                <div className="text-xs text-neutral-500 mt-1">
                                    {d.brand} / {d.model}
                                </div>
                            </div>
                        ))
                    )}
                </div>
            </div>

            {/* Editor Area */}
            <div className="flex-1 glass rounded-2xl border border-white/5 p-6 overflow-y-auto custom-scrollbar">
                {isEditing ? (
                    <div className="space-y-6">
                        <h2 className="text-2xl font-black text-white uppercase tracking-tighter">
                            {selectedDictionary ? 'Edit Dictionary' : 'New Dictionary'}
                        </h2>

                        <div className="grid grid-cols-2 gap-4">
                            <div className="space-y-2">
                                <label className="text-xs font-bold text-neutral-500 uppercase">Dictionary ID</label>
                                <input className="input-field w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                                    value={formData.id || ''}
                                    onChange={e => setFormData({ ...formData, id: e.target.value })}
                                    disabled={!!selectedDictionary}
                                    placeholder="e.g., cisco-catalyst-2960-v1" />
                            </div>
                            <div className="space-y-2">
                                <label className="text-xs font-bold text-neutral-500 uppercase">Name</label>
                                <input className="input-field w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                                    value={formData.name || ''}
                                    onChange={e => setFormData({ ...formData, name: e.target.value })}
                                    placeholder="e.g., Cisco Catalyst 2960 Template" />
                            </div>
                        </div>

                        <div className="grid grid-cols-2 gap-4">
                            <div className="space-y-2">
                                <label className="text-xs font-bold text-neutral-500 uppercase">Brand (REQUIRED)</label>
                                <input className="input-field w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                                    value={formData.brand || ''}
                                    onChange={e => setFormData({ ...formData, brand: e.target.value })}
                                    placeholder="e.g., Cisco" />
                            </div>
                            <div className="space-y-2">
                                <label className="text-xs font-bold text-neutral-500 uppercase">Model (REQUIRED)</label>
                                <input className="input-field w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                                    value={formData.model || ''}
                                    onChange={e => setFormData({ ...formData, model: e.target.value })}
                                    placeholder="e.g., Catalyst-2960" />
                            </div>
                        </div>

                        <div className="grid grid-cols-2 gap-4">
                            <div className="space-y-2">
                                <label className="text-xs font-bold text-neutral-500 uppercase">Polling Interval (seconds)</label>
                                <input type="number" className="input-field w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                                    value={formData.polling_interval ?? 60}
                                    onChange={e => setFormData({ ...formData, polling_interval: parseInt(e.target.value) || 60 })}
                                    min={10} />
                            </div>
                        </div>

                        {/* Metric Selection */}
                        <div className="p-4 bg-white/5 rounded-xl border border-white/5 space-y-4">
                            <div className="flex justify-between items-center">
                                <h3 className="text-sm font-bold text-white uppercase">Associated Metrics</h3>
                                <span className="text-xs text-neutral-500">{selectedMetricIds.length} selected</span>
                            </div>

                            {/* Brand filter */}
                            <div className="flex gap-2 items-center">
                                <label className="text-xs font-bold text-neutral-500 uppercase">Filter by Brand:</label>
                                <select className="input-field bg-black/40 border border-white/10 p-2 rounded text-white text-xs"
                                    value={filterBrand}
                                    onChange={e => setFilterBrand(e.target.value)}>
                                    <option value="">All Brands</option>
                                    {availableBrands.map(b => (
                                        <option key={b} value={b}>{b}</option>
                                    ))}
                                </select>
                            </div>

                            {/* Available metrics */}
                            <div className="bg-black/20 rounded-lg p-2 max-h-60 overflow-y-auto custom-scrollbar border border-white/5">
                                {filteredMetrics.length === 0 ? (
                                    <div className="text-center py-4 text-xs text-neutral-500 italic">No metrics available</div>
                                ) : (
                                    <div className="space-y-1">
                                        {filteredMetrics.map((m) => (
                                            <div key={m.id}
                                                onClick={() => toggleMetric(m.id)}
                                                className={`p-2 rounded cursor-pointer hover:bg-white/5 flex items-center gap-2 ${selectedMetricIds.includes(m.id) ? 'bg-brand-600/20 border border-brand-500/50' : 'border border-transparent'}`}>
                                                <input type="checkbox" checked={selectedMetricIds.includes(m.id)} readOnly className="pointer-events-none" />
                                                <span className="font-mono text-xs text-white">{m.id}</span>
                                                <span className="text-[10px] text-neutral-500 truncate">{m.oid || 'NO OID'}</span>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>

                            {/* Selected chips */}
                            <div className="flex flex-wrap gap-2">
                                {selectedMetricIds.length === 0 && (
                                    <p className="text-xs text-neutral-600 italic">No metrics selected.</p>
                                )}
                                {selectedMetricIds.map(mid => {
                                    const metric = allMetrics.find(m => m.id === mid);
                                    return (
                                        <button key={mid}
                                            onClick={() => toggleMetric(mid)}
                                            className="text-xs px-2 py-1 rounded border bg-brand-600 text-white border-brand-500 hover:bg-red-500 hover:border-red-500 transition-colors flex items-center gap-1">
                                            {mid}
                                            <span className="material-symbols-outlined text-[10px]">close</span>
                                        </button>
                                    );
                                })}
                            </div>
                        </div>

                        <div className="flex gap-4 pt-4">
                            <button onClick={handleSave} className="flex-1 bg-brand-600 hover:bg-brand-500 text-white font-bold py-3 rounded-xl transition-colors">
                                SAVE DICTIONARY
                            </button>
                            {selectedDictionary && (
                                <button onClick={() => handleDelete(selectedDictionary)} className="px-6 bg-red-600/20 hover:bg-red-600/40 text-red-500 font-bold py-3 rounded-xl transition-colors">
                                    DELETE
                                </button>
                            )}
                            <button onClick={() => setIsEditing(false)} className="px-6 bg-white/10 hover:bg-white/20 text-white font-bold py-3 rounded-xl transition-colors">
                                CANCEL
                            </button>
                        </div>
                    </div>
                ) : (
                    <div className="h-full flex flex-col items-center justify-center text-neutral-500 opacity-50">
                        <span className="material-symbols-outlined text-6xl mb-4">book</span>
                        <p className="uppercase font-bold tracking-widest text-sm">Select a Dictionary to Edit</p>
                    </div>
                )}
            </div>

            {/* Bulk Upload Modal */}
            {showBulkUpload && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
                    <div className="w-[90vw] h-[85vh] glass rounded-2xl border border-white/10 shadow-2xl overflow-hidden">
                        <DictionaryBulkUpload onClose={() => setShowBulkUpload(false)} />
                    </div>
                </div>
            )}
        </div>
    );
};

export default DictionaryManager;