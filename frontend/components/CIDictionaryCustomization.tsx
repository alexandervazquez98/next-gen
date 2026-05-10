import React, { useState, useEffect } from 'react';
import { api } from '../services/api';

interface AppliedDictionary {
    dictionary_id: string;
    dictionary_name: string;
    brand: string;
    model: string;
    metric_ids: string[];
    excluded_metrics: string[];
    extra_metrics: string[];
    applied_at: string;
}

interface CIDictionaryCustomizationProps {
    ci_id: string;
    onClose?: () => void;
}

const CIDictionaryCustomization: React.FC<CIDictionaryCustomizationProps> = ({ ci_id, onClose }) => {
    const [data, setData] = useState<AppliedDictionary | null>(null);
    const [loading, setLoading] = useState(false);
    const [saving, setSaving] = useState(false);
    const [removing, setRemoving] = useState(false);
    const [newExtraMetric, setNewExtraMetric] = useState('');
    const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; msg: string } | null>(null);

    useEffect(() => {
        fetchAppliedDictionary();
    }, [ci_id]);

    const fetchAppliedDictionary = async () => {
        setLoading(true);
        setFeedback(null);
        try {
            const result = await api.get<AppliedDictionary>(`/cis/${ci_id}/applied-dictionary`);
            setData(result);
        } catch (e: any) {
            const msg = e?.response?.data?.detail || e?.message || 'Failed to load applied dictionary';
            setFeedback({ type: 'error', msg });
        } finally {
            setLoading(false);
        }
    };

    const isMetricExcluded = (metricId: string): boolean => {
        if (!data) return false;
        return data.excluded_metrics.includes(metricId);
    };

    const toggleMetric = (metricId: string) => {
        if (!data) return;
        setData(prev => {
            if (!prev) return prev;
            const excluded = prev.excluded_metrics.includes(metricId)
                ? prev.excluded_metrics.filter(id => id !== metricId)
                : [...prev.excluded_metrics, metricId];
            return { ...prev, excluded_metrics: excluded };
        });
    };

    const addExtraMetric = () => {
        const trimmed = newExtraMetric.trim();
        if (!trimmed || !data) return;
        if (data.extra_metrics.includes(trimmed) || data.metric_ids.includes(trimmed)) {
            setFeedback({ type: 'error', msg: 'Metric already exists' });
            return;
        }
        setData(prev => {
            if (!prev) return prev;
            return { ...prev, extra_metrics: [...prev.extra_metrics, trimmed] };
        });
        setNewExtraMetric('');
    };

    const removeExtraMetric = (metricId: string) => {
        setData(prev => {
            if (!prev) return prev;
            return { ...prev, extra_metrics: prev.extra_metrics.filter(id => id !== metricId) };
        });
    };

    const handleSave = async () => {
        if (!data) return;
        setSaving(true);
        setFeedback(null);
        try {
            await api.put(`/cis/${ci_id}/dictionary-exclusions`, {
                excluded_metrics: data.excluded_metrics,
                extra_metrics: data.extra_metrics,
            });
            setFeedback({ type: 'success', msg: 'Customization saved successfully' });
        } catch (e: any) {
            const msg = e?.response?.data?.detail || e?.message || 'Failed to save customization';
            setFeedback({ type: 'error', msg });
        } finally {
            setSaving(false);
        }
    };

    const handleRemove = async () => {
        if (!data) return;
        if (!confirm('Remove this dictionary from the CI? This cannot be undone.')) return;
        setRemoving(true);
        setFeedback(null);
        try {
            await api.delete(`/cis/${ci_id}/applied-dictionary`);
            setFeedback({ type: 'success', msg: 'Dictionary removed' });
            setTimeout(() => onClose?.(), 1000);
        } catch (e: any) {
            const msg = e?.response?.data?.detail || e?.message || 'Failed to remove dictionary';
            setFeedback({ type: 'error', msg });
        } finally {
            setRemoving(false);
        }
    };

    if (loading) {
        return (
            <div className="flex items-center justify-center h-64">
                <span className="text-neutral-500 text-sm">Loading...</span>
            </div>
        );
    }

    if (!data) {
        return (
            <div className="flex flex-col items-center justify-center h-64 gap-3">
                <span className="material-symbols-outlined text-4xl text-neutral-600">search_off</span>
                <span className="text-neutral-500 text-sm italic">No dictionary applied to this CI</span>
                {onClose && (
                    <button onClick={onClose} className="text-neutral-500 hover:text-white text-sm mt-2">
                        Close
                    </button>
                )}
            </div>
        );
    }

    const activeMetrics = data.metric_ids.filter(id => !data.excluded_metrics.includes(id));
    const excludedMetricsCount = data.metric_ids.length - activeMetrics.length;

    return (
        <div className="glass rounded-2xl border border-white/5 p-6 space-y-6 overflow-y-auto custom-scrollbar max-h-[80vh]">
            {/* Header */}
            <div className="flex justify-between items-start">
                <div>
                    <h2 className="text-xl font-black text-white uppercase tracking-tighter">
                        Dictionary Customization
                    </h2>
                    <div className="mt-1">
                        <span className="text-brand-400 font-bold text-sm">{data.dictionary_name}</span>
                        <span className="text-neutral-500 text-xs ml-2">{data.brand} / {data.model}</span>
                    </div>
                </div>
                {onClose && (
                    <button onClick={onClose} className="text-neutral-500 hover:text-white text-sm">
                        Close
                    </button>
                )}
            </div>

            {/* Feedback */}
            {feedback && (
                <div className={`p-3 rounded-lg text-sm ${
                    feedback.type === 'success'
                        ? 'bg-green-900/30 border border-green-700/50 text-green-400'
                        : 'bg-red-900/30 border border-red-700/50 text-red-400'
                }`}>
                    {feedback.msg}
                </div>
            )}

            {/* Summary */}
            <div className="grid grid-cols-3 gap-3">
                <div className="p-3 bg-white/5 rounded-lg border border-white/5 text-center">
                    <div className="text-2xl font-black text-white">{data.metric_ids.length}</div>
                    <div className="text-xs text-neutral-500 uppercase tracking-wider">Total Metrics</div>
                </div>
                <div className="p-3 bg-white/5 rounded-lg border border-white/5 text-center">
                    <div className="text-2xl font-black text-green-400">{activeMetrics.length}</div>
                    <div className="text-xs text-neutral-500 uppercase tracking-wider">Active</div>
                </div>
                <div className="p-3 bg-white/5 rounded-lg border border-white/5 text-center">
                    <div className="text-2xl font-black text-red-400">{excludedMetricsCount}</div>
                    <div className="text-xs text-neutral-500 uppercase tracking-wider">Excluded</div>
                </div>
            </div>

            {/* Metric List */}
            <div className="space-y-3">
                <h3 className="text-sm font-bold text-white uppercase tracking-wider">Metrics</h3>
                <div className="space-y-1 max-h-64 overflow-y-auto custom-scrollbar bg-black/20 rounded-lg p-2 border border-white/5">
                    {data.metric_ids.map(metricId => (
                        <div key={metricId}
                            onClick={() => toggleMetric(metricId)}
                            className={`p-2 rounded cursor-pointer hover:bg-white/5 flex items-center gap-3 ${
                                isMetricExcluded(metricId)
                                    ? 'border border-transparent opacity-50'
                                    : 'bg-green-900/10 border border-green-700/30'
                            }`}>
                            <input
                                type="checkbox"
                                checked={!isMetricExcluded(metricId)}
                                onChange={() => toggleMetric(metricId)}
                                className="pointer-events-none"
                            />
                            <span className={`text-sm font-mono ${isMetricExcluded(metricId) ? 'text-neutral-500 line-through' : 'text-white'}`}>
                                {metricId}
                            </span>
                        </div>
                    ))}
                </div>
            </div>

            {/* Extra Metrics */}
            <div className="space-y-3">
                <h3 className="text-sm font-bold text-white uppercase tracking-wider">
                    Extra Metrics ({data.extra_metrics.length})
                </h3>
                <div className="flex gap-2">
                    <input
                        type="text"
                        value={newExtraMetric}
                        onChange={e => setNewExtraMetric(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && addExtraMetric()}
                        placeholder="Add custom metric ID..."
                        className="flex-1 bg-black/30 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-neutral-600 focus:outline-none focus:border-brand-500/50"
                    />
                    <button
                        onClick={addExtraMetric}
                        className="px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white text-sm font-bold rounded-lg transition-colors"
                    >
                        Add
                    </button>
                </div>
                {data.extra_metrics.length > 0 && (
                    <div className="space-y-1 max-h-32 overflow-y-auto custom-scrollbar bg-black/20 rounded-lg p-2 border border-white/5">
                        {data.extra_metrics.map(metricId => (
                            <div key={metricId} className="p-2 rounded hover:bg-white/5 flex items-center gap-3 bg-cyan-900/10 border border-cyan-700/30">
                                <span className="text-sm font-mono text-cyan-400">{metricId}</span>
                                <button
                                    onClick={() => removeExtraMetric(metricId)}
                                    className="ml-auto text-neutral-500 hover:text-red-400 text-xs"
                                >
                                    Remove
                                </button>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {/* Actions */}
            <div className="flex gap-3 pt-2 border-t border-white/5">
                <button
                    onClick={handleSave}
                    disabled={saving}
                    className={`px-6 py-3 rounded-lg font-bold text-sm transition-all ${
                        saving
                            ? 'bg-neutral-700 text-neutral-500 cursor-not-allowed'
                            : 'bg-brand-600 hover:bg-brand-500 text-white'
                    }`}
                >
                    {saving ? 'Saving...' : 'Save Changes'}
                </button>
                <button
                    onClick={handleRemove}
                    disabled={removing}
                    className={`px-6 py-3 rounded-lg font-bold text-sm transition-all ${
                        removing
                            ? 'bg-neutral-700 text-neutral-500 cursor-not-allowed'
                            : 'bg-red-900/40 hover:bg-red-800/40 border border-red-700/50 text-red-400'
                    }`}
                >
                    {removing ? 'Removing...' : 'Remove Dictionary'}
                </button>
            </div>
        </div>
    );
};

export default CIDictionaryCustomization;
