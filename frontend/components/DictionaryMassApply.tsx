import React, { useState, useEffect } from 'react';
import { api } from '../services/api';

interface DictionaryItem {
    id: string;
    name: string;
    brand: string;
    model: string;
    metric_ids: string[];
    polling_interval: number;
}

interface TargetCI {
    id: string;
    name: string;
    ip: string | null;
    brand: string;
    model: string;
    location_name: string | null;
}

interface ApplyResult {
    applied_count: number;
    skipped_count: number;
    message: string;
}

interface PreviewMetricResult {
    metric_id: string;
    oid: string;
    value: string | null;
    status: 'OK' | 'WARNING' | 'CRITICAL' | 'NO_DATA';
}

interface CIPreviewResult {
    ci_id: string;
    ci_name: string;
    ip: string | null;
    results: PreviewMetricResult[];
}

interface PreviewResult {
    previews: CIPreviewResult[];
}

interface DictionaryMassApplyProps {
    onClose?: () => void;
}

type Tab = 'select' | 'preview';

const STATUS_COLORS: Record<string, string> = {
    OK: 'bg-green-900/40 border-green-700/50 text-green-400',
    WARNING: 'bg-yellow-900/40 border-yellow-700/50 text-yellow-400',
    CRITICAL: 'bg-red-900/40 border-red-700/50 text-red-400',
    NO_DATA: 'bg-neutral-800/40 border-neutral-700/50 text-neutral-500',
};

const DictionaryMassApply: React.FC<DictionaryMassApplyProps> = ({ onClose }) => {
    const [dictionaries, setDictionaries] = useState<DictionaryItem[]>([]);
    const [loading, setLoading] = useState(false);
    const [selectedDictionary, setSelectedDictionary] = useState<DictionaryItem | null>(null);
    const [targetCIs, setTargetCIs] = useState<TargetCI[]>([]);
    const [selectedCIIds, setSelectedCIIds] = useState<string[]>([]);
    const [loadingCIs, setLoadingCIs] = useState(false);
    const [applying, setApplying] = useState(false);
    const [result, setResult] = useState<ApplyResult | null>(null);
    const [activeTab, setActiveTab] = useState<Tab>('select');
    const [previewing, setPreviewing] = useState(false);
    const [previewResult, setPreviewResult] = useState<PreviewResult | null>(null);

    useEffect(() => {
        fetchDictionaries();
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

    const fetchTargetCIs = async (dictionaryId: string) => {
        setLoadingCIs(true);
        setTargetCIs([]);
        setSelectedCIIds([]);
        setResult(null);
        try {
            const data = await api.get<TargetCI[]>(`/dictionaries/${dictionaryId}/target-cis`);
            setTargetCIs(Array.isArray(data) ? data : []);
        } catch (e) {
            console.error('Failed to fetch target CIs', e);
        } finally {
            setLoadingCIs(false);
        }
    };

    const handleSelectDictionary = (dict: DictionaryItem) => {
        setSelectedDictionary(dict);
        setTargetCIs([]);
        setSelectedCIIds([]);
        setResult(null);
        fetchTargetCIs(dict.id);
    };

    const toggleCI = (ciId: string) => {
        setSelectedCIIds(prev =>
            prev.includes(ciId)
                ? prev.filter(id => id !== ciId)
                : [...prev, ciId]
        );
    };

    const selectAllCIs = () => {
        setSelectedCIIds(targetCIs.map(ci => ci.id));
    };

    const handlePreview = async () => {
        if (!selectedDictionary || selectedCIIds.length === 0) return;

        setPreviewing(true);
        setPreviewResult(null);
        try {
            const data = await api.post<PreviewResult>(
                `/dictionaries/${selectedDictionary.id}/preview`,
                { ci_ids: selectedCIIds }
            );
            setPreviewResult(data);
            setActiveTab('preview');
        } catch (e: any) {
            const msg = e?.response?.data?.detail || e?.message || 'Failed to preview';
            alert(msg);
        } finally {
            setPreviewing(false);
        }
    };

    const handleApply = async () => {
        if (!selectedDictionary || selectedCIIds.length === 0) return;

        setApplying(true);
        setResult(null);
        try {
            const data = await api.post<ApplyResult>(
                `/dictionaries/${selectedDictionary.id}/apply`,
                { ci_ids: selectedCIIds }
            );
            setResult(data);
        } catch (e: any) {
            const msg = e?.response?.data?.detail || e?.message || 'Failed to apply dictionary';
            alert(msg);
        } finally {
            setApplying(false);
        }
    };

    return (
        <div className="h-full flex gap-6">
            {/* Sidebar: Dictionary List */}
            <div className="w-1/3 glass rounded-2xl border border-white/5 flex flex-col overflow-hidden">
                <div className="p-4 border-b border-white/5 flex justify-between items-center bg-black/20">
                    <h3 className="font-bold text-white uppercase tracking-wider text-sm">Dictionaries</h3>
                </div>
                <div className="flex-1 overflow-y-auto custom-scrollbar p-2 space-y-2">
                    {loading ? (
                        <div className="text-center py-4 text-xs text-neutral-500">Loading...</div>
                    ) : dictionaries.length === 0 ? (
                        <div className="text-center py-4 text-xs text-neutral-500 italic">No dictionaries available</div>
                    ) : (
                        dictionaries.map((d, i) => (
                            <div key={i} onClick={() => handleSelectDictionary(d)}
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

            {/* Main: Target CIs & Apply */}
            <div className="flex-1 glass rounded-2xl border border-white/5 p-6 overflow-y-auto custom-scrollbar space-y-6">
                <div className="flex justify-between items-center">
                    <h2 className="text-xl font-black text-white uppercase tracking-tighter">
                        Mass Apply
                    </h2>
                    {onClose && (
                        <button onClick={onClose} className="text-neutral-500 hover:text-white text-sm">
                            Close
                        </button>
                    )}
                </div>

                {!selectedDictionary ? (
                    <div className="flex flex-col items-center justify-center h-64 text-neutral-500">
                        <span className="material-symbols-outlined text-4xl mb-2">playlist_add</span>
                        <p className="text-sm italic">Select a dictionary to see target CIs</p>
                    </div>
                ) : (
                    <>
                        {/* Selected dictionary info */}
                        <div className="p-4 bg-white/5 rounded-xl border border-white/5">
                            <div className="text-sm font-bold text-brand-400 uppercase tracking-widest mb-2">
                                Selected Dictionary
                            </div>
                            <div className="text-white font-bold">{selectedDictionary.name}</div>
                            <div className="text-xs text-neutral-500">
                                {selectedDictionary.brand} / {selectedDictionary.model} — {selectedDictionary.metric_ids.length} metrics
                            </div>
                        </div>

                        {/* Target CIs */}
                        <div className="space-y-4">
                            <div className="flex justify-between items-center">
                                <h3 className="text-sm font-bold text-white uppercase">Target CIs ({targetCIs.length})</h3>
                                {targetCIs.length > 0 && (
                                    <button
                                        onClick={selectAllCIs}
                                        className="text-xs text-brand-400 hover:text-brand-300 uppercase font-black"
                                    >
                                        Select All
                                    </button>
                                )}
                            </div>

                            {loadingCIs ? (
                                <div className="text-center py-8 text-neutral-500 text-sm">Loading target CIs...</div>
                            ) : targetCIs.length === 0 ? (
                                <div className="text-center py-8 text-neutral-500 text-sm italic">
                                    No CIs match this dictionary's brand+model
                                </div>
                            ) : (
                                <div className="space-y-1 max-h-80 overflow-y-auto custom-scrollbar bg-black/20 rounded-lg p-2 border border-white/5">
                                    {targetCIs.map((ci) => (
                                        <div key={ci.id}
                                            onClick={() => toggleCI(ci.id)}
                                            className={`p-3 rounded cursor-pointer hover:bg-white/5 flex items-center gap-3 ${selectedCIIds.includes(ci.id) ? 'bg-brand-600/20 border border-brand-500/50' : 'border border-transparent'}`}>
                                            <input
                                                type="checkbox"
                                                checked={selectedCIIds.includes(ci.id)}
                                                readOnly
                                                className="pointer-events-none"
                                            />
                                            <div className="flex-1 min-w-0">
                                                <div className="flex items-center gap-2">
                                                    <span className="font-bold text-white text-sm">{ci.name}</span>
                                                    {ci.ip && (
                                                        <span className="text-[10px] text-neutral-500 font-mono">{ci.ip}</span>
                                                    )}
                                                </div>
                                                <div className="flex items-center gap-2 text-[10px] text-neutral-500">
                                                    <span>{ci.brand}</span>
                                                    <span>/</span>
                                                    <span>{ci.model}</span>
                                                    {ci.location_name && (
                                                        <>
                                                            <span className="mx-1">·</span>
                                                            <span>{ci.location_name}</span>
                                                        </>
                                                    )}
                                                </div>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>

                        {/* Apply/Preview Buttons */}
                        {targetCIs.length > 0 && (
                            <div className="flex items-center gap-4">
                                <button
                                    onClick={handlePreview}
                                    disabled={selectedCIIds.length === 0 || previewing}
                                    className={`px-6 py-3 rounded-lg font-bold text-sm transition-all ${
                                        selectedCIIds.length === 0 || previewing
                                            ? 'bg-neutral-700 text-neutral-500 cursor-not-allowed'
                                            : 'bg-cyan-900/40 hover:bg-cyan-800/40 border border-cyan-700/50 text-cyan-400'
                                    }`}
                                >
                                    {previewing ? 'Collecting...' : `Preview ${selectedCIIds.length} CI${selectedCIIds.length !== 1 ? 's' : ''}`}
                                </button>

                                <button
                                    onClick={handleApply}
                                    disabled={selectedCIIds.length === 0 || applying}
                                    className={`px-6 py-3 rounded-lg font-bold text-sm transition-all ${
                                        selectedCIIds.length === 0 || applying
                                            ? 'bg-neutral-700 text-neutral-500 cursor-not-allowed'
                                            : 'bg-brand-600 hover:bg-brand-500 text-white'
                                    }`}
                                >
                                    {applying ? 'Applying...' : `Apply to ${selectedCIIds.length} CI${selectedCIIds.length !== 1 ? 's' : ''}`}
                                </button>

                                {result && (
                                    <div className={`p-3 rounded-lg text-sm ${
                                        result.applied_count > 0
                                            ? 'bg-green-900/30 border border-green-700/50 text-green-400'
                                            : 'bg-yellow-900/30 border border-yellow-700/50 text-yellow-400'
                                    }`}>
                                        {result.message}
                                        {result.skipped_count > 0 && (
                                            <span className="ml-2 text-yellow-300">({result.skipped_count} skipped)</span>
                                        )}
                                    </div>
                                )}
                            </div>
                        )}
                    </>
                )}
            </div>

            {/* Preview Panel */}
            {activeTab === 'preview' && previewResult && selectedDictionary && (
                <div className="flex-1 glass rounded-2xl border border-white/5 p-6 overflow-y-auto custom-scrollbar">
                    <div className="flex justify-between items-center mb-4">
                        <h2 className="text-xl font-black text-white uppercase tracking-tighter">
                            Preview Readings
                        </h2>
                        <button
                            onClick={() => setActiveTab('select')}
                            className="text-neutral-500 hover:text-white text-sm"
                        >
                            Back to Selection
                        </button>
                    </div>

                    <div className="mb-4 p-3 bg-white/5 rounded-lg border border-white/5">
                        <span className="text-sm text-neutral-400">
                            Showing SNMP readings for <span className="text-white font-bold">{previewResult.previews.length}</span> CIs
                            across <span className="text-white font-bold">{selectedDictionary.metric_ids.length}</span> metrics
                        </span>
                        <div className="flex items-center gap-4 mt-2 text-xs">
                            {Object.entries(STATUS_COLORS).map(([status, classes]) => (
                                <span key={status} className={`px-2 py-0.5 rounded border ${classes}`}>{status}</span>
                            ))}
                        </div>
                    </div>

                    <div className="overflow-x-auto">
                        <table className="w-full text-xs custom-scrollbar">
                            <thead>
                                <tr className="border-b border-white/10">
                                    <th className="text-left text-neutral-500 font-bold uppercase tracking-wider pb-2 pr-4">CI</th>
                                    <th className="text-left text-neutral-500 font-bold uppercase tracking-wider pb-2 pr-4">IP</th>
                                    {selectedDictionary.metric_ids.map(mid => (
                                        <th key={mid} className="text-center text-neutral-500 font-bold uppercase tracking-wider pb-2 px-2 min-w-[80px]">{mid}</th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody>
                                {previewResult.previews.map((preview) => {
                                    const ci = targetCIs.find(c => c.id === preview.ci_id);
                                    return (
                                        <tr key={preview.ci_id} className="border-b border-white/5 hover:bg-white/5">
                                            <td className="py-2 pr-4">
                                                <div className="font-bold text-white">{preview.ci_name}</div>
                                                <div className="text-neutral-500 text-[10px]">{ci?.brand} / {ci?.model}</div>
                                            </td>
                                            <td className="py-2 pr-4 font-mono text-neutral-400">
                                                {preview.ip || <span className="text-neutral-600">no IP</span>}
                                            </td>
                                            {preview.results.map((r) => (
                                                <td key={r.metric_id} className="py-2 px-2 text-center">
                                                    <span className={`inline-block px-2 py-1 rounded border text-[10px] font-bold ${STATUS_COLORS[r.status] || STATUS_COLORS.NO_DATA}`}>
                                                        {r.value ?? '—'}
                                                    </span>
                                                </td>
                                            ))}
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>

                    {/* Disable apply if all NO_DATA */}
                    {previewResult.previews.every(p => p.results.every(r => r.status === 'NO_DATA')) && (
                        <div className="mt-4 p-3 bg-red-900/20 border border-red-700/50 rounded-lg text-sm text-red-400">
                            ⚠ All metrics returned NO_DATA — SNMP may not be available on selected CIs. Apply will not add monitoring for these devices.
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

export default DictionaryMassApply;
