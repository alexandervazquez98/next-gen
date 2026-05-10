import React, { useState, useEffect, useRef } from 'react';
import { api } from '../services/api';

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

interface TargetCI {
    id: string;
    name: string;
    ip: string | null;
    brand: string;
    model: string;
    location_name: string | null;
}

interface BulkRow {
    brand: string;
    model: string;
    name: string;
    polling_interval: number;
    metric_ids: string[];
    row_index: number;
}

interface BulkError {
    row: number;
    field: string;
    message: string;
}

interface BulkValidateResponse {
    rows: BulkRow[];
    errors: BulkError[];
    valid_count: number;
    error_count: number;
}

interface SNMPResult {
    results: Record<string, {
        sampled_ips: string[];
        polled: Array<{ ip: string; metric_id: string; value: string; status: string }>;
        no_data: Array<{ ip: string; metric_id: string; status: string }>;
    }>;
}

interface BulkConfirmResponse {
    created: Array<{ id: string; name: string; brand: string; model: string }>;
    count: number;
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

type Tab = 'upload' | 'apply';
type UploadStep = 'idle' | 'preview' | 'validating' | 'confirming' | 'done';

const STATUS_COLORS: Record<string, string> = {
    OK: 'bg-green-900/40 border-green-700/50 text-green-400',
    WARNING: 'bg-yellow-900/40 border-yellow-700/50 text-yellow-400',
    CRITICAL: 'bg-red-900/40 border-red-700/50 text-red-400',
    NO_DATA: 'bg-neutral-800/40 border-neutral-700/50 text-neutral-500',
};

interface DictionaryBulkUploadProps {
    onClose?: () => void;
}

const DictionaryBulkUpload: React.FC<DictionaryBulkUploadProps> = ({ onClose }) => {
    const [activeTab, setActiveTab] = useState<Tab>('upload');

    // ---- Upload tab state ----
    const [uploadStep, setUploadStep] = useState<UploadStep>('idle');
    const [parsedRows, setParsedRows] = useState<BulkRow[]>([]);
    const [parseErrors, setParseErrors] = useState<BulkError[]>([]);
    const [snmpResults, setSnmpResults] = useState<SNMPResult | null>(null);
    const [confirmResult, setConfirmResult] = useState<BulkConfirmResponse | null>(null);
    const [uploading, setUploading] = useState(false);
    const [validatingSample, setValidatingSample] = useState(false);
    const [confirming, setConfirming] = useState(false);
    const fileInputRef = useRef<HTMLInputElement>(null);

    // ---- Apply tab state ----
    const [dictionaries, setDictionaries] = useState<DictionaryItem[]>([]);
    const [selectedDictionary, setSelectedDictionary] = useState<DictionaryItem | null>(null);
    const [targetCIs, setTargetCIs] = useState<TargetCI[]>([]);
    const [selectedCIIds, setSelectedCIIds] = useState<string[]>([]);
    const [loadingCIs, setLoadingCIs] = useState(false);
    const [previewing, setPreviewing] = useState(false);
    const [previewResult, setPreviewResult] = useState<PreviewResult | null>(null);
    const [applying, setApplying] = useState(false);
    const [applyResult, setApplyResult] = useState<ApplyResult | null>(null);

    useEffect(() => {
        if (activeTab === 'apply') {
            fetchDictionaries();
        }
    }, [activeTab]);

    const fetchDictionaries = async () => {
        try {
            const data = await api.get<DictionaryItem[]>('/dictionaries');
            setDictionaries(Array.isArray(data) ? data : []);
        } catch (e) {
            console.error(e);
        }
    };

    // ---- Upload tab handlers ----

    const handleDownloadTemplate = () => {
        api.get('/dictionaries/template-csv', { responseType: 'blob' }).then((blob: any) => {
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'dictionary_template.csv';
            a.click();
            URL.revokeObjectURL(url);
        });
    };

    const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;

        setUploading(true);
        setUploadStep('idle');
        setParsedRows([]);
        setParseErrors([]);
        setSnmpResults(null);
        setConfirmResult(null);

        try {
            const formData = new FormData();
            formData.append('file', file);

            const data = await api.post<BulkValidateResponse>('/dictionaries/bulk', formData);

            setParsedRows(data.rows || []);
            setParseErrors(data.errors || []);
            setUploadStep('preview');
        } catch (err: any) {
            const msg = err?.response?.data?.detail || err?.message || 'Upload failed';
            alert(msg);
        } finally {
            setUploading(false);
        }

        // Reset file input
        if (fileInputRef.current) {
            fileInputRef.current.value = '';
        }
    };

    const handleValidateSample = async () => {
        if (parsedRows.length === 0) return;

        setValidatingSample(true);
        setSnmpResults(null);
        try {
            const data = await api.post<SNMPResult>('/dictionaries/bulk/validate-sample', {
                rows: parsedRows,
            });
            setSnmpResults(data);
        } catch (err: any) {
            const msg = err?.response?.data?.detail || err?.message || 'Validation failed';
            alert(msg);
        } finally {
            setValidatingSample(false);
        }
    };

    const handleConfirm = async () => {
        if (parsedRows.length === 0) return;

        setConfirming(true);
        try {
            const data = await api.post<BulkConfirmResponse>('/dictionaries/bulk/confirm', {
                rows: parsedRows,
            });
            setConfirmResult(data);
            setUploadStep('done');
        } catch (err: any) {
            const msg = err?.response?.data?.detail || err?.message || 'Confirmation failed';
            alert(msg);
        } finally {
            setConfirming(false);
        }
    };

    const resetUpload = () => {
        setUploadStep('idle');
        setParsedRows([]);
        setParseErrors([]);
        setSnmpResults(null);
        setConfirmResult(null);
    };

    // ---- Apply tab handlers ----

    const fetchTargetCIs = async (dictionaryId: string) => {
        setLoadingCIs(true);
        setTargetCIs([]);
        setSelectedCIIds([]);
        setApplyResult(null);
        try {
            const data = await api.get<TargetCI[]>(`/dictionaries/${dictionaryId}/target-cis`);
            const cis = Array.isArray(data) ? data : [];
            setTargetCIs(cis);
            // Default: select ALL CIs
            setSelectedCIIds(cis.map(c => c.id));
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
        setApplyResult(null);
        setPreviewResult(null);
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
        } catch (err: any) {
            const msg = err?.response?.data?.detail || err?.message || 'Preview failed';
            alert(msg);
        } finally {
            setPreviewing(false);
        }
    };

    const handleApply = async () => {
        if (!selectedDictionary || selectedCIIds.length === 0) return;

        setApplying(true);
        setApplyResult(null);
        try {
            const data = await api.post<ApplyResult>(
                `/dictionaries/${selectedDictionary.id}/apply`,
                { ci_ids: selectedCIIds }
            );
            setApplyResult(data);
        } catch (err: any) {
            const msg = err?.response?.data?.detail || err?.message || 'Apply failed';
            alert(msg);
        } finally {
            setApplying(false);
        }
    };

    return (
        <div className="h-full flex flex-col">
            {/* Header */}
            <div className="flex justify-between items-center p-4 border-b border-white/10">
                <h2 className="text-xl font-black text-white uppercase tracking-tighter">Bulk Dictionary Upload</h2>
                {onClose && (
                    <button onClick={onClose} className="text-neutral-500 hover:text-white text-sm">
                        Close
                    </button>
                )}
            </div>

            {/* Tabs */}
            <div className="flex border-b border-white/10">
                <button
                    onClick={() => setActiveTab('upload')}
                    className={`px-6 py-3 font-bold text-sm uppercase tracking-wider transition-colors ${
                        activeTab === 'upload'
                            ? 'text-brand-400 border-b-2 border-brand-400'
                            : 'text-neutral-500 hover:text-white'
                    }`}
                >
                    Upload CSV
                </button>
                <button
                    onClick={() => setActiveTab('apply')}
                    className={`px-6 py-3 font-bold text-sm uppercase tracking-wider transition-colors ${
                        activeTab === 'apply'
                            ? 'text-brand-400 border-b-2 border-brand-400'
                            : 'text-neutral-500 hover:text-white'
                    }`}
                >
                    Apply Dictionaries
                </button>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto custom-scrollbar p-6">
                {activeTab === 'upload' && (
                    <UploadPanel
                        uploadStep={uploadStep}
                        parsedRows={parsedRows}
                        parseErrors={parseErrors}
                        snmpResults={snmpResults}
                        confirmResult={confirmResult}
                        uploading={uploading}
                        validatingSample={validatingSample}
                        confirming={confirming}
                        fileInputRef={fileInputRef}
                        onDownloadTemplate={handleDownloadTemplate}
                        onFileChange={handleFileChange}
                        onValidateSample={handleValidateSample}
                        onConfirm={handleConfirm}
                        onReset={resetUpload}
                    />
                )}
                {activeTab === 'apply' && (
                    <ApplyPanel
                        dictionaries={dictionaries}
                        selectedDictionary={selectedDictionary}
                        targetCIs={targetCIs}
                        selectedCIIds={selectedCIIds}
                        loadingCIs={loadingCIs}
                        previewing={previewing}
                        previewResult={previewResult}
                        applying={applying}
                        applyResult={applyResult}
                        onSelectDictionary={handleSelectDictionary}
                        onToggleCI={toggleCI}
                        onSelectAll={selectAllCIs}
                        onPreview={handlePreview}
                        onApply={handleApply}
                    />
                )}
            </div>
        </div>
    );
};

// ---- Upload Panel Sub-component ----

interface UploadPanelProps {
    uploadStep: UploadStep;
    parsedRows: BulkRow[];
    parseErrors: BulkError[];
    snmpResults: SNMPResult | null;
    confirmResult: BulkConfirmResponse | null;
    uploading: boolean;
    validatingSample: boolean;
    confirming: boolean;
    fileInputRef: React.RefObject<HTMLInputElement>;
    onDownloadTemplate: () => void;
    onFileChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
    onValidateSample: () => void;
    onConfirm: () => void;
    onReset: () => void;
}

const UploadPanel: React.FC<UploadPanelProps> = ({
    uploadStep,
    parsedRows,
    parseErrors,
    snmpResults,
    confirmResult,
    uploading,
    validatingSample,
    confirming,
    fileInputRef,
    onDownloadTemplate,
    onFileChange,
    onValidateSample,
    onConfirm,
    onReset,
}) => {
    return (
        <div className="space-y-6">
            {/* Actions bar */}
            <div className="flex gap-4 items-center">
                <button
                    onClick={onDownloadTemplate}
                    className="flex items-center gap-2 px-4 py-2 bg-cyan-900/40 hover:bg-cyan-800/40 border border-cyan-700/50 text-cyan-400 rounded-lg font-bold text-sm transition-colors"
                >
                    <span className="material-symbols-outlined text-sm">download</span>
                    Download Template CSV
                </button>

                <label className="flex items-center gap-2 px-4 py-2 bg-white/10 hover:bg-white/20 border border-white/20 text-white rounded-lg font-bold text-sm cursor-pointer transition-colors">
                    <span className="material-symbols-outlined text-sm">upload</span>
                    {uploading ? 'Parsing...' : 'Upload CSV'}
                    <input
                        ref={fileInputRef}
                        type="file"
                        accept=".csv"
                        onChange={onFileChange}
                        className="hidden"
                    />
                </label>
            </div>

            {/* Preview table */}
            {uploadStep !== 'idle' && (
                <div className="space-y-4">
                    {/* Summary */}
                    <div className="flex gap-4 text-sm">
                        <span className="text-green-400 font-bold">{parsedRows.length} valid rows</span>
                        {parseErrors.length > 0 && (
                            <span className="text-red-400 font-bold">{parseErrors.length} errors</span>
                        )}
                    </div>

                    {/* Errors */}
                    {parseErrors.length > 0 && (
                        <div className="bg-red-900/20 border border-red-700/50 rounded-lg p-4 space-y-1">
                            <h4 className="text-red-400 font-bold text-sm uppercase">Errors</h4>
                            {parseErrors.map((err, i) => (
                                <div key={i} className="text-xs text-red-300">
                                    Row {err.row}: [{err.field}] {err.message}
                                </div>
                            ))}
                        </div>
                    )}

                    {/* Rows table */}
                    {parsedRows.length > 0 && (
                        <div className="overflow-x-auto">
                            <table className="w-full text-xs custom-scrollbar">
                                <thead>
                                    <tr className="border-b border-white/10">
                                        <th className="text-left text-neutral-500 font-bold uppercase tracking-wider pb-2 pr-4">#</th>
                                        <th className="text-left text-neutral-500 font-bold uppercase tracking-wider pb-2 pr-4">Brand</th>
                                        <th className="text-left text-neutral-500 font-bold uppercase tracking-wider pb-2 pr-4">Model</th>
                                        <th className="text-left text-neutral-500 font-bold uppercase tracking-wider pb-2 pr-4">Name</th>
                                        <th className="text-left text-neutral-500 font-bold uppercase tracking-wider pb-2 pr-4">Interval</th>
                                        <th className="text-left text-neutral-500 font-bold uppercase tracking-wider pb-2 pr-4">Metric IDs</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {parsedRows.map((row) => (
                                        <tr key={row.row_index} className="border-b border-white/5 hover:bg-white/5">
                                            <td className="py-2 pr-4 text-neutral-500">{row.row_index}</td>
                                            <td className="py-2 pr-4 text-white font-bold">{row.brand}</td>
                                            <td className="py-2 pr-4 text-white">{row.model}</td>
                                            <td className="py-2 pr-4 text-white">{row.name}</td>
                                            <td className="py-2 pr-4 text-neutral-400">{row.polling_interval}s</td>
                                            <td className="py-2 pr-4 font-mono text-brand-400 text-xs">{row.metric_ids.join(', ')}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}

                    {/* SNMP Validation Results */}
                    {snmpResults && (
                        <SNMPResultsPanel results={snmpResults} />
                    )}

                    {/* Action buttons */}
                    <div className="flex gap-4 items-center">
                        {uploadStep === 'preview' && parsedRows.length > 0 && (
                            <>
                                <button
                                    onClick={onValidateSample}
                                    disabled={validatingSample}
                                    className="px-6 py-3 bg-cyan-900/40 hover:bg-cyan-800/40 border border-cyan-700/50 text-cyan-400 rounded-lg font-bold text-sm transition-colors disabled:opacity-50"
                                >
                                    {validatingSample ? 'Validating SNMP...' : `Validate SNMP (10% sample)`}
                                </button>

                                {snmpResults && (
                                    <button
                                        onClick={onConfirm}
                                        disabled={confirming}
                                        className="px-6 py-3 bg-brand-600 hover:bg-brand-500 text-white rounded-lg font-bold text-sm transition-colors disabled:opacity-50"
                                    >
                                        {confirming ? 'Creating...' : `Confirm & Create ${parsedRows.length} Dictionaries`}
                                    </button>
                                )}
                            </>
                        )}

                        {uploadStep === 'done' && confirmResult && (
                            <div className="bg-green-900/30 border border-green-700/50 rounded-lg p-4 space-y-2 w-full">
                                <h4 className="text-green-400 font-bold">Successfully Created {confirmResult.count} Dictionaries</h4>
                                <div className="space-y-1">
                                    {confirmResult.created.map((dict) => (
                                        <div key={dict.id} className="text-xs text-green-300">
                                            ✓ {dict.name} ({dict.brand} / {dict.model})
                                        </div>
                                    ))}
                                </div>
                                <button
                                    onClick={onReset}
                                    className="mt-2 px-4 py-2 bg-white/10 hover:bg-white/20 border border-white/20 text-white rounded-lg text-sm font-bold transition-colors"
                                >
                                    Upload Another CSV
                                </button>
                            </div>
                        )}
                    </div>
                </div>
            )}

            {uploadStep === 'idle' && (
                <div className="flex flex-col items-center justify-center h-48 text-neutral-500 border border-dashed border-white/10 rounded-xl">
                    <span className="material-symbols-outlined text-4xl mb-2">upload_file</span>
                    <p className="text-sm italic">Download the template, fill it, then upload the CSV</p>
                </div>
            )}
        </div>
    );
};

// ---- SNMP Results Panel ----

const SNMPResultsPanel: React.FC<{ results: SNMPResult }> = ({ results }) => {
    return (
        <div className="space-y-4">
            <h4 className="text-sm font-bold text-white uppercase">SNMP Validation (10% sample)</h4>
            {Object.entries(results.results).map(([key, data]) => (
                <div key={key} className="bg-white/5 rounded-lg border border-white/10 p-4 space-y-2">
                    <div className="text-sm font-bold text-brand-400">{key}</div>
                    <div className="text-xs text-neutral-500">Sampled IPs: {data.sampled_ips.join(', ') || 'none'}</div>

                    {data.polled.length > 0 && (
                        <div>
                            <div className="text-xs font-bold text-green-400 mb-1">Responding ({data.polled.length})</div>
                            <div className="space-y-1">
                                {data.polled.slice(0, 5).map((p, i) => (
                                    <div key={i} className="text-xs text-green-300">
                                        {p.ip} / {p.metric_id}: {p.value} ({p.status})
                                    </div>
                                ))}
                                {data.polled.length > 5 && (
                                    <div className="text-xs text-neutral-500">... and {data.polled.length - 5} more</div>
                                )}
                            </div>
                        </div>
                    )}

                    {data.no_data.length > 0 && (
                        <div>
                            <div className="text-xs font-bold text-red-400 mb-1">No Data ({data.no_data.length})</div>
                            <div className="space-y-1">
                                {data.no_data.slice(0, 5).map((nd, i) => (
                                    <div key={i} className="text-xs text-red-300">
                                        {nd.ip} / {nd.metric_id}: NO_DATA
                                    </div>
                                ))}
                                {data.no_data.length > 5 && (
                                    <div className="text-xs text-neutral-500">... and {data.no_data.length - 5} more</div>
                                )}
                            </div>
                        </div>
                    )}

                    {data.polled.length === 0 && data.no_data.length === 0 && (
                        <div className="text-xs text-neutral-500 italic">No CIs with SNMP available for this brand/model</div>
                    )}
                </div>
            ))}
        </div>
    );
};

// ---- Apply Panel Sub-component ----

interface ApplyPanelProps {
    dictionaries: DictionaryItem[];
    selectedDictionary: DictionaryItem | null;
    targetCIs: TargetCI[];
    selectedCIIds: string[];
    loadingCIs: boolean;
    previewing: boolean;
    previewResult: PreviewResult | null;
    applying: boolean;
    applyResult: ApplyResult | null;
    onSelectDictionary: (d: DictionaryItem) => void;
    onToggleCI: (id: string) => void;
    onSelectAll: () => void;
    onPreview: () => void;
    onApply: () => void;
}

const ApplyPanel: React.FC<ApplyPanelProps> = ({
    dictionaries,
    selectedDictionary,
    targetCIs,
    selectedCIIds,
    loadingCIs,
    previewing,
    previewResult,
    applying,
    applyResult,
    onSelectDictionary,
    onToggleCI,
    onSelectAll,
    onPreview,
    onApply,
}) => {
    const [activeTab, setActiveTab] = useState<'select' | 'preview'>('select');

    useEffect(() => {
        if (previewResult && !previewing) {
            setActiveTab('preview');
        }
    }, [previewResult, previewing]);

    return (
        <div className="h-full flex gap-6">
            {/* Sidebar: Dictionary List */}
            <div className="w-1/3 glass rounded-2xl border border-white/5 flex flex-col overflow-hidden">
                <div className="p-4 border-b border-white/5 flex justify-between items-center bg-black/20">
                    <h3 className="font-bold text-white uppercase tracking-wider text-sm">Dictionaries</h3>
                </div>
                <div className="flex-1 overflow-y-auto custom-scrollbar p-2 space-y-2">
                    {dictionaries.length === 0 ? (
                        <div className="text-center py-4 text-xs text-neutral-500 italic">No dictionaries available</div>
                    ) : (
                        dictionaries.map((d, i) => (
                            <div key={i} onClick={() => onSelectDictionary(d)}
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
                <h2 className="text-xl font-black text-white uppercase tracking-tighter">Apply Dictionary</h2>

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
                                <h3 className="text-sm font-bold text-white uppercase">
                                    Target CIs ({targetCIs.length}) — {selectedCIIds.length} selected
                                </h3>
                                {targetCIs.length > 0 && (
                                    <button
                                        onClick={onSelectAll}
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
                                            onClick={() => onToggleCI(ci.id)}
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

                        {/* Buttons */}
                        {targetCIs.length > 0 && selectedCIIds.length === 0 && (
                            <div className="text-xs text-red-400 italic">At least one CI must be selected</div>
                        )}

                        {targetCIs.length > 0 && selectedCIIds.length > 0 && (
                            <div className="flex items-center gap-4">
                                <button
                                    onClick={onPreview}
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
                                    onClick={onApply}
                                    disabled={selectedCIIds.length === 0 || applying}
                                    className={`px-6 py-3 rounded-lg font-bold text-sm transition-all ${
                                        selectedCIIds.length === 0 || applying
                                            ? 'bg-neutral-700 text-neutral-500 cursor-not-allowed'
                                            : 'bg-brand-600 hover:bg-brand-500 text-white'
                                    }`}
                                >
                                    {applying ? 'Applying...' : `Apply to ${selectedCIIds.length} CI${selectedCIIds.length !== 1 ? 's' : ''}`}
                                </button>

                                {applyResult && (
                                    <div className={`p-3 rounded-lg text-sm ${
                                        applyResult.applied_count > 0
                                            ? 'bg-green-900/30 border border-green-700/50 text-green-400'
                                            : 'bg-yellow-900/30 border border-yellow-700/50 text-yellow-400'
                                    }`}>
                                        {applyResult.message}
                                        {applyResult.skipped_count > 0 && (
                                            <span className="ml-2 text-yellow-300">({applyResult.skipped_count} skipped)</span>
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
                        <h2 className="text-xl font-black text-white uppercase tracking-tighter">Preview Readings</h2>
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
                                {previewResult.previews.map((preview) => (
                                    <tr key={preview.ci_id} className="border-b border-white/5 hover:bg-white/5">
                                        <td className="py-2 pr-4">
                                            <div className="font-bold text-white">{preview.ci_name}</div>
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
                                ))}
                            </tbody>
                        </table>
                    </div>

                    {previewResult.previews.every(p => p.results.every(r => r.status === 'NO_DATA')) && (
                        <div className="mt-4 p-3 bg-red-900/20 border border-red-700/50 rounded-lg text-sm text-red-400">
                            All metrics returned NO_DATA — SNMP may not be available on selected CIs.
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

export default DictionaryBulkUpload;