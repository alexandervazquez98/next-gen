import React, { useState, useEffect } from 'react';
import { MetricDef } from '../types';
import { api } from '../services/api';

interface MetricsManagerProps {
    onClose?: () => void;
}

const MetricsManager: React.FC<MetricsManagerProps> = ({ onClose }) => {
    const [metrics, setMetrics] = useState<MetricDef[]>([]);
    const [loading, setLoading] = useState(false);
    const [selectedMetric, setSelectedMetric] = useState<MetricDef | null>(null);
    const [isEditing, setIsEditing] = useState(false);

    // Form State
    const [formData, setFormData] = useState<Partial<MetricDef>>({});
    const [criteria, setCriteria] = useState<{ brands: string, models: string, layers: string, names: string, excluded_names: string }>({ brands: '', models: '', layers: '', names: '', excluded_names: '' });

    // Test State
    const [testIp, setTestIp] = useState('');
    const [testCommunity, setTestCommunity] = useState('public');
    const [testResult, setTestResult] = useState<any>(null);

    // CLI Test State
    const [cliTestResult, setCliTestResult] = useState<{
        success: boolean;
        raw_output?: string;
        extracted_value?: string | null;
        numeric_value?: number | null;
        status: string;
    } | null>(null);

    // Hardware Models for selection
    const [hardwareModels, setHardwareModels] = useState<{ brand: string, model: string }[]>([]);
    const [filterBrand, setFilterBrand] = useState('');
    const [allNodes, setAllNodes] = useState<any[]>([]);

    // Usage Data
    const [usageData, setUsageData] = useState<any>(null);
    const [usageLoading, setUsageLoading] = useState(false);
    const [showRegexHelp, setShowRegexHelp] = useState(false);

    useEffect(() => {
        if (selectedMetric) {
            fetchUsage(selectedMetric.id);
        } else {
            setUsageData(null);
        }
    }, [selectedMetric]);

    const fetchUsage = async (id: string) => {
        setUsageLoading(true);
        try {
            const data = await api.get<any>(`/metrics/${id}/usage`);
            setUsageData(data);
        } catch (e) {
            console.error(e);
        } finally {
            setUsageLoading(false);
        }
    };

    useEffect(() => {
        fetchMetrics();
        fetchHardwareModels();
        fetchNodes();
    }, []);

    const fetchNodes = async () => {
        try {
            const data = await api.get<any[]>('/nodes');
            setAllNodes(Array.isArray(data) ? data : []);
        } catch (e) {
            console.error(e);
        }
    };

    const fetchHardwareModels = async () => {
        try {
            const data = await api.get<any[]>('/hardware');
            setHardwareModels(Array.isArray(data) ? data : []);
        } catch (e) {
            console.error("Error fetching hardware models", e);
        }
    };

    const fetchMetrics = async () => {
        setLoading(true);
        try {
            const data = await api.get<MetricDef[]>('/metrics');
            setMetrics(Array.isArray(data) ? data : []);
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    };

    const loadMetricDetail = async (metricId: string) => {
        const detail = await api.get<MetricDef>(`/metrics/${metricId}`);
        setSelectedMetric(detail);
        setFormData(detail);
        const app = detail.applicable_to || {};
        setCriteria({
            brands: (app.brands || []).join(', '),
            models: (app.models || []).join(', '),
            layers: (app.layers || []).join(', '),
            names: (app.names || []).join(', '),
            excluded_names: (app.excluded_names || []).join(', '),
        });
        setIsEditing(true);
    };

    const handleEdit = async (metric: MetricDef) => {
        try {
            await loadMetricDetail(metric.id);
        } catch (e) {
            console.error(e);
            alert('Error loading metric details');
        }
    };

    const handleCreate = () => {
        setSelectedMetric(null);
        setFormData({ protocol: 'SNMP', dataType: 'INTEGER', operator: '>=', criticality: 1, applicable_to: {} });
        setCriteria({ brands: '', models: '', layers: '', names: '', excluded_names: '' });
        setIsEditing(true);
        setTestResult(null);
    };

    const handleSave = async (overrideCriteria?: any) => {
        // Prepare applicable_to
        const crit = overrideCriteria && typeof overrideCriteria === 'object' && 'brands' in overrideCriteria
            ? overrideCriteria
            : criteria;

        const appTo = {
            brands: (crit.brands || '').split(',').map((s: string) => s.trim()).filter((s: string) => s),
            models: (crit.models || '').split(',').map((s: string) => s.trim()).filter((s: string) => s),
            layers: (crit.layers || '').split(',').map((s: string) => s.trim()).filter((s: string) => s),
            names: (crit.names || '').split(',').map((s: string) => s.trim()).filter((s: string) => s),
            excluded_names: (crit.excluded_names || '').split(',').map((s: string) => s.trim()).filter((s: string) => s)
        };

        const payload = {
            ...formData,
            warning: formData.warning === undefined || formData.warning === null || String(formData.warning) === '' ? null : Number(formData.warning),
            critical: formData.critical === undefined || formData.critical === null || String(formData.critical) === '' ? null : Number(formData.critical),
            applicable_to: appTo
        };

        try {
            await api.post('/metrics', payload);
            alert('Metric Saved');
            setIsEditing(false);
            setFormData({});
            setCriteria({ brands: '', models: '', layers: '', names: '', excluded_names: '' });
            fetchMetrics();
        } catch (e) {
            alert('Error saving metric');
        }
    };

    const buildCriteriaStrings = (applicableTo?: MetricDef['applicable_to']) => ({
        brands: (applicableTo?.brands || []).join(', '),
        models: (applicableTo?.models || []).join(', '),
        layers: (applicableTo?.layers || []).join(', '),
        names: (applicableTo?.names || []).join(', '),
        excluded_names: (applicableTo?.excluded_names || []).join(', ')
    });

    const buildMetricPayload = (applicableTo: MetricDef['applicable_to']) => ({
        ...formData,
        warning: formData.warning === undefined || formData.warning === null || String(formData.warning) === '' ? null : Number(formData.warning),
        critical: formData.critical === undefined || formData.critical === null || String(formData.critical) === '' ? null : Number(formData.critical),
        applicable_to: applicableTo,
    });

    const handleExcludeAssociatedCI = async (ci: any) => {
        if (!selectedMetric) return;

        const currentNames = criteria.names.split(',').map(s => s.trim()).filter(s => s);
        const newNames = currentNames.filter(n => n !== ci.name && n !== ci.id);

        const currentExcluded = criteria.excluded_names.split(',').map(s => s.trim()).filter(s => s);
        const newExcluded = [...currentExcluded];
        if (!newExcluded.includes(ci.name)) newExcluded.push(ci.name);
        if (!newExcluded.includes(ci.id)) newExcluded.push(ci.id);

        const updatedApplicableTo = {
            brands: criteria.brands.split(',').map(s => s.trim()).filter(s => s),
            models: criteria.models.split(',').map(s => s.trim()).filter(s => s),
            layers: criteria.layers.split(',').map(s => s.trim()).filter(s => s),
            names: newNames,
            excluded_names: newExcluded,
        };

        const payload = buildMetricPayload(updatedApplicableTo);

        try {
            await api.post('/metrics', payload);

            const updatedMetric = {
                ...selectedMetric,
                ...payload,
                applicable_to: updatedApplicableTo,
            };

            const nextCriteria = {
                ...criteria,
                names: newNames.join(', '),
                excluded_names: newExcluded.join(', '),
            };

            setFormData(payload);
            setSelectedMetric(updatedMetric);
            setCriteria(nextCriteria);
            setUsageData((prev: any) => prev ? {
                ...prev,
                count: Math.max((prev.count || 1) - 1, 0),
                cis: Array.isArray(prev.cis) ? prev.cis.filter((item: any) => item.id !== ci.id) : [],
            } : prev);
            fetchMetrics();
        } catch (e) {
            alert('Error saving metric');
        }
    };

    // ... (rest of component until handleRemoveCI logic update)

    // Updated Remove Logic inside the existing button handler in render or separate function?
    // I'll update the button onClick logic directly in the replacement chunk below if possible, but safer to replace entire block including render of table.

    // ... skipping to render part logic modification ...

    // No, I need to replace the state definition first, then I'll handle the button logic in a second replace or inside this one if context allows.
    // Given the size, I'll do state first.


    const handleTestOID = async () => {
        if (!testIp || !formData.oid) return alert("IP and OID required");
        setTestResult(null);
        try {
            const data = await api.post<any>('/metrics/validate', {
                ip: testIp,
                community: testCommunity,
                oid: formData.oid
            });
            setTestResult(data);
            if (data.success && data.detectedType) {
                setFormData(prev => ({ ...prev, dataType: data.detectedType }));
            }
        } catch (e) {
            alert("Test Failed");
        }
    };

    const handleTestCLI = async () => {
        if (!formData.cli_command || !formData.cli_test_ip || !formData.cli_test_user || !formData.cli_test_pass) {
            return alert("CLI command, device IP, username, and password are all required to test.");
        }
        setCliTestResult(null);
        try {
            const data = await api.post<any>('/cli/test', {
                ip: formData.cli_test_ip,
                cli_protocol: formData.cli_protocol || 'SSH',
                username: formData.cli_test_user,
                password: formData.cli_test_pass,
                cli_command: formData.cli_command,
                cli_value_extractor: formData.cli_value_extractor || '',
                cli_timeout: formData.cli_timeout || 30,
                escalation_script: formData.cli_escalation_script || undefined,
            });
            setCliTestResult(data);
        } catch (e: any) {
            setCliTestResult({
                success: false,
                status: e?.message || 'REQUEST_FAILED',
                raw_output: e?.detail || String(e),
            });
        }
    };

    const handleSaveCLI = async () => {
        if (!formData.id || !formData.cli_command) {
            return alert("Metric ID and CLI command are required to save.");
        }
        await handleSave({
            ...formData,
            protocol: 'CLI',
            cli_protocol: formData.cli_protocol || 'SSH',
            cli_timeout: formData.cli_timeout || 30,
        });
    };

    const toggleModel = (modelName: string) => {
        const currentModels = (criteria.models || '').split(',').map(s => s.trim()).filter(s => s);
        let newModels;
        if (currentModels.includes(modelName)) {
            newModels = currentModels.filter(m => m !== modelName);
        } else {
            newModels = [...currentModels, modelName];
        }
        setCriteria({ ...criteria, models: newModels.join(', ') });
    };

    return (
        <div className="h-full flex gap-6">
            {/* Sidebar List */}
            <div className="w-1/3 glass rounded-2xl border border-white/5 flex flex-col overflow-hidden">
                <div className="p-4 border-b border-white/5 flex justify-between items-center bg-black/20">
                    <h3 className="font-bold text-white uppercase tracking-wider text-sm">Metrics Definitions</h3>
                    <button onClick={handleCreate} className="bg-brand-600 hover:bg-brand-500 text-white rounded p-1">
                        <span className="material-symbols-outlined text-sm">add</span>
                    </button>
                </div>
                <div className="flex-1 overflow-y-auto custom-scrollbar p-2 space-y-2">
                    {metrics.map((m, i) => (
                        <div key={i} onClick={() => handleEdit(m)}
                            className={`p-3 rounded-lg border border-white/5 cursor-pointer hover:bg-white/5 transition-colors ${selectedMetric?.id === m.id ? 'bg-brand-500/10 border-brand-500/50' : 'bg-transparent'}`}>
                            <div className="flex justify-between">
                                <span className="font-bold text-white text-sm">{m.id}</span>
                                <span className="text-[10px] bg-white/10 px-1.5 rounded text-neutral-300">{m.dataType}</span>
                            </div>
                            <div className="text-xs text-neutral-500 font-mono mt-1 truncate">{m.protocol === 'CLI' ? (m.cli_command || 'CLI') : (m.oid || 'NO OID')}</div>
                        </div>
                    ))}
                </div>
            </div>

            {/* Editor Area */}
            <div className="flex-1 glass rounded-2xl border border-white/5 p-6 overflow-y-auto custom-scrollbar">
                {isEditing ? (
                    <div className="space-y-6">
                        <h2 className="text-2xl font-black text-white uppercase tracking-tighter">{selectedMetric ? 'Edit Metric' : 'New Metric'}</h2>

                        <div className="grid grid-cols-2 gap-4">
                            <div className="space-y-2">
                                <label className="text-xs font-bold text-neutral-500 uppercase">Metric ID (Name)</label>
                                <input className="input-field w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                                    value={formData.id || ''} onChange={e => setFormData({ ...formData, id: e.target.value })} disabled={!!selectedMetric} />
                            </div>
                            <div className="space-y-2">
                                <label className="text-xs font-bold text-neutral-500 uppercase">Protocol</label>
                                <select className="input-field w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                                    value={formData.protocol || 'SNMP'} onChange={e => setFormData({ ...formData, protocol: e.target.value })}>
                                    <option value="SNMP">SNMP</option>
                                    <option value="ICMP">ICMP</option>
                                    <option value="HTTP">HTTP</option>
                                    <option value="TOKEN">TOKEN</option>
                                    <option value="API">API</option>
                                    <option value="SSH">SSH</option>
                                    <option value="CLI">CLI</option>
                                </select>
                            </div>
                        </div>

                        <div className="grid grid-cols-2 gap-4">
                            <div className="space-y-2">
                                <label className="text-xs font-bold text-neutral-500 uppercase">Criticality (Alert Level)</label>
                                <select className="w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                                    value={formData.criticality || 1} onChange={e => setFormData({ ...formData, criticality: parseInt(e.target.value) as 1 | 2 | 3 })}>
                                    <option value={1}>1 - Informational</option>
                                    <option value={2}>2 - Warning</option>
                                    <option value={3}>3 - Exception (Critical)</option>
                                </select>
                            </div>
                        </div>

                        <div className="space-y-2">
                            <label className="text-xs font-bold text-neutral-500 uppercase">Description</label>
                            <input className="input-field w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                                value={formData.description || ''} onChange={e => setFormData({ ...formData, description: e.target.value })} />
                        </div>

                        <div className="p-4 bg-white/5 rounded-xl border border-white/5 space-y-4">
                            <div className="flex justify-between items-center">
                                <h3 className="text-sm font-bold text-white uppercase">OID Configuration</h3>
                                <button onClick={handleTestOID} className="text-xs bg-brand-600 text-white px-3 py-1 rounded hover:bg-brand-500">Auto-Detect Type</button>
                            </div>
                            <div className="flex gap-2">
                                <input className="input-field flex-1 bg-black/40 border border-white/10 p-2 rounded text-white font-mono text-sm"
                                    placeholder="Examples: .1.3.6.1.2... or sysDescr.0"
                                    value={formData.oid || ''} onChange={e => setFormData({ ...formData, oid: e.target.value })} />
                            </div>



                            <div className="grid grid-cols-2 gap-4">
                                <input className="bg-black/40 border border-white/10 p-2 rounded text-white text-xs"
                                    placeholder="Test IP (e.g. 192.168.1.1)" value={testIp} onChange={e => setTestIp(e.target.value)} />
                                <input className="bg-black/40 border border-white/10 p-2 rounded text-white text-xs"
                                    placeholder="Community (public)" value={testCommunity} onChange={e => setTestCommunity(e.target.value)} />
                            </div>

                            {testResult && (
                                <div className={`p-2 rounded text-xs font-mono border ${testResult.success ? 'bg-green-500/10 border-green-500/50 text-green-400' : 'bg-red-500/10 border-red-500/50 text-red-500'}`}>
                                    {testResult.success ? `Value: ${testResult.value} (Detected: ${testResult.detectedType})` : `Error: ${testResult.error}`}
                                </div>
                            )}
                        </div>

                        {/* ── CLI Configuration Panel ─────────────────────────────────── */}
                        {formData.protocol === 'CLI' && (
                            <div className="p-4 bg-white/5 rounded-xl border border-white/5 space-y-4">
                                <h3 className="text-sm font-bold text-white uppercase">CLI Configuration</h3>

                                <div className="grid grid-cols-2 gap-4">
                                    <div className="space-y-2">
                                        <label className="text-xs font-bold text-neutral-500 uppercase">Credential Ref</label>
                                        <input className="input-field w-full bg-black/40 border border-white/10 p-2 rounded text-white text-xs"
                                            placeholder="e.g. CLI_DEFAULT (env: CLI_DEFAULT_USER / CLI_DEFAULT_PASS)"
                                            value={formData.cli_credential_ref || ''}
                                            onChange={e => setFormData({ ...formData, cli_credential_ref: e.target.value })} />
                                    </div>
                                    <div className="space-y-2">
                                        <label className="text-xs font-bold text-neutral-500 uppercase">Transport</label>
                                        <select className="input-field w-full bg-black/40 border border-white/10 p-2 rounded text-white text-xs"
                                            value={formData.cli_protocol || 'SSH'}
                                            onChange={e => setFormData({ ...formData, cli_protocol: e.target.value as 'SSH' | 'Telnet' })}>
                                            <option value="SSH">SSH</option>
                                            <option value="Telnet">Telnet</option>
                                        </select>
                                    </div>
                                </div>

                                <div className="space-y-2">
                                    <label className="text-xs font-bold text-neutral-500 uppercase">CLI Command</label>
                                    <input className="input-field w-full bg-black/40 border border-white/10 p-2 rounded text-white text-xs font-mono"
                                        placeholder="e.g. show interfaces GigabitEthernet0/0 status | include {target}"
                                        value={formData.cli_command || ''}
                                        onChange={e => setFormData({ ...formData, cli_command: e.target.value })} />
                                </div>

                                <div className="grid grid-cols-2 gap-4">
                                    <div className="space-y-2">
                                        <label className="text-xs font-bold text-neutral-500 uppercase">Target (optional)</label>
                                        <input className="input-field w-full bg-black/40 border border-white/10 p-2 rounded text-white text-xs"
                                            placeholder="e.g. GigabitEthernet0/0"
                                            value={formData.cli_target || ''}
                                            onChange={e => setFormData({ ...formData, cli_target: e.target.value })} />
                                    </div>
                                    <div className="space-y-2">
                                        <label className="text-xs font-bold text-neutral-500 uppercase">Timeout (seconds)</label>
                                        <input type="number" className="input-field w-full bg-black/40 border border-white/10 p-2 rounded text-white text-xs"
                                            placeholder="30"
                                            value={formData.cli_timeout ?? 30}
                                            onChange={e => setFormData({ ...formData, cli_timeout: parseInt(e.target.value) || 30 })} />
                                    </div>
                                </div>

                                <div className="space-y-2">
                                    <div className="flex items-center justify-between">
                                        <label className="text-xs font-bold text-neutral-500 uppercase">Regex Extractor</label>
                                        <button
                                            type="button"
                                            onClick={() => setShowRegexHelp(!showRegexHelp)}
                                            className="text-[10px] text-brand-400 hover:text-brand-300 underline"
                                        >
                                            {showRegexHelp ? 'Hide help' : 'Need help?'}
                                        </button>
                                    </div>
                                    <input className="input-field w-full bg-black/40 border border-white/10 p-2 rounded text-white text-xs font-mono"
                                        placeholder="e.g. regex:is (up|down)  or  regex:load (\d+)"
                                        value={formData.cli_value_extractor || ''}
                                        onChange={e => setFormData({ ...formData, cli_value_extractor: e.target.value })} />
                                    {showRegexHelp && (
                                        <div className="bg-black/60 border border-white/10 rounded p-3 text-[10px] text-neutral-400 space-y-2">
                                            <div>
                                                <span className="font-bold text-brand-400">Recommended:</span> Ask AI to generate the regex. Example: <span className="font-mono text-neutral-300">"Generate a regex to extract FULL/ state from: Neighbor ID     Pri   State\nX.X.X.X        0   FULL/  -"</span>
                                            </div>
                                            <div className="border-t border-white/5 pt-2 space-y-1">
                                                <div><span className="font-bold text-neutral-300">Format:</span> <span className="font-mono">regex:pattern</span> or <span className="font-mono">regex:pattern (group)</span></div>
                                                <div><span className="font-bold text-neutral-300">Numeric keywords:</span> up/full/enabled/ok→<span className="text-brand-400">1.0</span>, down/disabled/error/fail→<span className="text-red-400">0.0</span>, drother→<span className="text-yellow-400">0.5</span></div>
                                                <div><span className="font-bold text-neutral-300">For numbers:</span> <span className="font-mono">regex:(\d+\.\d+)</span> or <span className="font-mono">regex:(\d+)</span></div>
                                            </div>
                                            <div className="border-t border-white/5 pt-2">
                                                <span className="font-bold text-neutral-300">OSPF examples:</span>
                                                <div className="font-mono mt-1">FULL (up): <span className="text-brand-300">regex:FULL</span> → 1.0</div>
                                                <div className="font-mono">Dead Time: <span className="text-brand-300">regex:(\d+:\d+:\d+)</span></div>
                                                <div className="font-mono">Neighbor IP: <span className="text-brand-300">regex:(\d+\.\d+\.\d+\.\d+)</span></div>
                                            </div>
                                        </div>
                                    )}
                                </div>

                                <div className="space-y-2">
                                    <label className="text-xs font-bold text-neutral-500 uppercase">Escalation Script (optional)</label>
                                    <textarea className="input-field w-full bg-black/40 border border-white/10 p-2 rounded text-white text-xs font-mono"
                                        placeholder="One command per line, e.g.:&#10;enable&#10;secret_password"
                                        rows={2}
                                        value={formData.cli_escalation_script || ''}
                                        onChange={e => setFormData({ ...formData, cli_escalation_script: e.target.value })} />
                                </div>

                                {/* ── CLI Test Section ──────────────────────────────────────── */}
                                <div className="border-t border-white/10 pt-4 space-y-3">
                                    <div className="flex justify-between items-center">
                                        <h4 className="text-xs font-bold text-white uppercase">Test Query</h4>
                                    </div>
                                    <div className="grid grid-cols-2 gap-4">
                                        <input className="bg-black/40 border border-white/10 p-2 rounded text-white text-xs"
                                            placeholder="Device IP (e.g. 192.168.1.1)"
                                            value={formData.cli_test_ip || ''}
                                            onChange={e => setFormData({ ...formData, cli_test_ip: e.target.value })} />
                                        <input className="bg-black/40 border border-white/10 p-2 rounded text-white text-xs"
                                            placeholder="Username"
                                            value={formData.cli_test_user || ''}
                                            onChange={e => setFormData({ ...formData, cli_test_user: e.target.value })} />
                                        <input className="bg-black/40 border border-white/10 p-2 rounded text-white text-xs"
                                            placeholder="Password"
                                            type="password"
                                            value={formData.cli_test_pass || ''}
                                            onChange={e => setFormData({ ...formData, cli_test_pass: e.target.value })} />
                                    </div>

                                    <div className="flex gap-2">
                                        <button
                                            onClick={handleTestCLI}
                                            disabled={!formData.cli_command || !formData.cli_test_ip || !formData.cli_test_user || !formData.cli_test_pass}
                                            className="text-xs bg-brand-600 hover:bg-brand-500 disabled:bg-neutral-600 disabled:cursor-not-allowed text-white px-3 py-1.5 rounded transition-colors">
                                            Test CLI Query
                                        </button>
                                        <button
                                            onClick={() => handleSaveCLI()}
                                            disabled={!formData.cli_command}
                                            className="text-xs bg-green-600/80 hover:bg-green-600 disabled:bg-neutral-600 disabled:cursor-not-allowed text-white px-3 py-1.5 rounded transition-colors">
                                            Save as Metric
                                        </button>
                                    </div>

                                    {cliTestResult && (
                                        <div className={`p-3 rounded text-xs font-mono border ${cliTestResult.success ? 'bg-green-500/10 border-green-500/50 text-green-400' : 'bg-red-500/10 border-red-500/50 text-red-400'}`}>
                                            <div className="flex justify-between items-center mb-1">
                                                <span className="font-bold">Status:</span>
                                                <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${cliTestResult.success ? 'bg-green-500/30' : 'bg-red-500/30'}`}>
                                                    {cliTestResult.status}
                                                </span>
                                            </div>
                                            {cliTestResult.raw_output !== undefined && (
                                                <div className="mb-1">
                                                    <span className="font-bold text-neutral-400">Raw Output:</span>
                                                    <pre className="whitespace-pre-wrap break-all mt-1 text-[10px] text-neutral-300">{cliTestResult.raw_output}</pre>
                                                </div>
                                            )}
                                            {cliTestResult.extracted_value !== undefined && cliTestResult.extracted_value !== null && (
                                                <div className="mb-1">
                                                    <span className="font-bold text-neutral-400">Extracted:</span> {cliTestResult.extracted_value}
                                                </div>
                                            )}
                                            {cliTestResult.numeric_value !== undefined && cliTestResult.numeric_value !== null && (
                                                <div>
                                                    <span className="font-bold text-neutral-400">Numeric:</span> {String(cliTestResult.numeric_value)}
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}

                        <div className="grid grid-cols-4 gap-4">
                            <div className="space-y-2">
                                <label className="text-xs font-bold text-neutral-500 uppercase">Data Type</label>
                                <select className="w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                                    value={formData.dataType || 'INTEGER'} onChange={e => setFormData({ ...formData, dataType: e.target.value })}>
                                    <option value="INTEGER">Integer</option>
                                    <option value="FLOAT">Float</option>
                                    <option value="STRING">String</option>
                                    <option value="BOOLEAN">Boolean</option>
                                </select>
                            </div>
                            {formData.protocol !== 'ICMP' && (
                                <>
                                    <div className="space-y-2">
                                        <label className="text-xs font-bold text-neutral-500 uppercase">Threshold Rule</label>
                                        <select className="w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                                            value={formData.operator || '>='}
                                            onChange={e => {
                                                const newOperator = e.target.value;
                                                const updates = { operator: newOperator };
                                                if (newOperator === '==' || newOperator === '!=') {
                                                    updates['warning'] = null;
                                                }
                                                setFormData({ ...formData, ...updates });
                                            }}>
                                            <option value=">=">&ge; (Greater/Eq) - For upper limits (e.g. Temp &ge; 90)</option>
                                            <option value="<=">&le; (Less/Eq) - For lower limits (e.g. Free Space &le; 10)</option>
                                            <option value="==">== (Equals) - For exact states (e.g. Status == 1)</option>
                                            <option value="!=">&ne; (Not Equals) - For deviations (e.g. Status &ne; 200)</option>
                                        </select>
                                        <div className="mt-2 text-[10px] text-neutral-500 leading-tight">
                                            <p><strong className="text-neutral-400">Tip:</strong> Use &ge; for metrics like CPU load. Use == for discrete states (e.g., if OID returns 1 for UP and 0 for DOWN, use == 0 for Critical).</p>
                                        </div>
                                    </div>
                                    <div className="space-y-2">
                                        <label className={`text-xs font-bold uppercase transition-colors ${(formData.operator === '==' || formData.operator === '!=') ? 'text-neutral-600' : 'text-neutral-500'}`}>
                                            Warning Threshold
                                        </label>
                                        <input type="number" className="w-full bg-black/40 border border-white/10 p-2 rounded text-white disabled:opacity-30 disabled:cursor-not-allowed"
                                            placeholder={(formData.operator === '==' || formData.operator === '!=') ? "N/A for Exact States" : "Optional"}
                                            disabled={formData.operator === '==' || formData.operator === '!='}
                                            value={formData.warning ?? ''} onChange={e => setFormData({ ...formData, warning: e.target.value ? parseFloat(e.target.value) : null })} />
                                    </div>
                                    <div className="space-y-2">
                                        <label className="text-xs font-bold text-neutral-500 uppercase">Critical Threshold</label>
                                        <input type="number" className="w-full bg-black/40 border border-white/10 p-2 rounded text-white"
                                            placeholder="Optional"
                                            value={formData.critical ?? ''} onChange={e => setFormData({ ...formData, critical: e.target.value ? parseFloat(e.target.value) : null })} />
                                    </div>
                                </>
                            )}
                        </div>

                        <div className="p-4 bg-white/5 rounded-xl border border-white/5 space-y-2">
                            <h3 className="text-sm font-bold text-white uppercase">Applicability</h3>
                            <p className="text-xs text-neutral-500">Select which hardware models this metric applies to.</p>

                            {/* Catalog Selection */}
                            <div className="bg-black/20 p-3 rounded-lg border border-white/5 space-y-3">
                                <div className="grid grid-cols-2 gap-2">
                                    <div>
                                        <label className="text-[10px] font-bold text-neutral-500 uppercase">Filter by Brand</label>
                                        <select className="input-field w-full bg-black/40 border border-white/10 p-2 rounded text-white text-xs"
                                            value={filterBrand}
                                            onChange={e => setFilterBrand(e.target.value)}>
                                            <option value="">All Brands</option>
                                            {Array.from(new Set(hardwareModels.map(h => h.brand))).sort().map(b => (
                                                <option key={b} value={b}>{b}</option>
                                            ))}
                                        </select>
                                    </div>
                                    <div>
                                        <label className="text-[10px] font-bold text-neutral-500 uppercase">Quick Add Model</label>
                                        <select className="input-field w-full bg-black/40 border border-white/10 p-2 rounded text-white text-xs"
                                            onChange={e => {
                                                if (e.target.value) toggleModel(e.target.value);
                                                e.target.value = ""; // Reset
                                            }}>
                                            <option value="">Select Model to Add...</option>
                                            {hardwareModels
                                                .filter(h => !filterBrand || h.brand === filterBrand)
                                                .sort((a, b) => a.brand.localeCompare(b.brand) || a.model.localeCompare(b.model))
                                                .map((hm, idx) => (
                                                    <option key={idx} value={hm.model}>
                                                        {hm.brand} - {hm.model}
                                                    </option>
                                                ))}
                                        </select>
                                    </div>
                                </div>
                            </div>

                            {/* Selected Chips */}
                            <div className="flex flex-wrap gap-2 mt-2 max-h-32 overflow-y-auto p-2 bg-black/10 rounded-lg">
                                {(criteria.models || '').split(',').map(s => s.trim()).filter(s => s).length === 0 && (
                                    <p className="text-xs text-neutral-600 italic">No models selected.</p>
                                )}
                                {hardwareModels.map((hm, idx) => {
                                    const isSelected = (criteria.models || '').includes(hm.model);
                                    if (!isSelected) return null; // Only show selected here? 
                                    // User wants "combos ... aparescan". 
                                    // Let's show currently selected chips, and use combos to ADD.
                                    return (
                                        <button key={idx}
                                            onClick={() => toggleModel(hm.model)}
                                            className="text-xs px-2 py-1 rounded border bg-brand-600 text-white border-brand-500 hover:bg-red-500 hover:border-red-500 transition-colors flex items-center gap-1">
                                            {hm.brand} {hm.model}
                                            <span className="material-symbols-outlined text-[10px]">close</span>
                                        </button>
                                    )
                                })}
                            </div>

                            <div className="mt-4 pt-4 border-t border-white/10">
                                <label className="text-xs font-bold text-neutral-500 uppercase block mb-1">Advanced Criteria</label>
                                <div className="grid grid-cols-2 gap-4">
                                    <input className="w-full bg-black/40 border border-white/10 p-2 rounded text-white text-xs"
                                        placeholder="Target Brands (e.g. Cisco, Dell)" value={criteria.brands} onChange={e => setCriteria({ ...criteria, brands: e.target.value })} />
                                    <input className="w-full bg-black/40 border border-white/10 p-2 rounded text-white text-xs"
                                        placeholder="Target Layers (e.g. INFRASTRUCTURE)" value={criteria.layers} onChange={e => setCriteria({ ...criteria, layers: e.target.value })} />
                                    <div className="col-span-2 space-y-2">
                                        <label className="text-[10px] font-bold text-neutral-500 uppercase block">Quick Add Explicit CIs</label>
                                        <select className="w-full bg-black/40 border border-white/10 p-2 rounded text-white text-xs"
                                            onChange={e => {
                                                if (e.target.value) {
                                                    const currentNames = (criteria.names || '').split(',').map(s => s.trim()).filter(s => s);
                                                    if (!currentNames.includes(e.target.value)) {
                                                        setCriteria({ ...criteria, names: [...currentNames, e.target.value].join(', ') });
                                                    }
                                                }
                                                e.target.value = ""; // Reset
                                            }}>
                                            <option value="">Select Specific CI from Registry...</option>
                                            {allNodes
                                                .sort((a, b) => ((a.label || a.name) || '').localeCompare((b.label || b.name) || ''))
                                                .map((n, idx) => {
                                                    const displayName = n.label || n.name || n.id;
                                                    return (
                                                        <option key={idx} value={displayName}>
                                                            {displayName} ({n.ip || 'No IP'})
                                                        </option>
                                                    );
                                                })}
                                        </select>

                                        {/* Name Chips */}
                                        <div className="flex flex-wrap gap-2 max-h-32 overflow-y-auto p-2 bg-black/10 rounded-lg">
                                            {(criteria.names || '').split(',').map(s => s.trim()).filter(s => s).length === 0 && (
                                                <p className="text-xs text-neutral-600 italic">No explicit CIs added.</p>
                                            )}
                                            {(criteria.names || '').split(',').map(s => s.trim()).filter(s => s).map((name, idx) => (
                                                <button key={idx} title="Remove"
                                                    onClick={() => {
                                                        const newNames = criteria.names.split(',').map(n => n.trim()).filter(n => n && n !== name);
                                                        setCriteria({ ...criteria, names: newNames.join(', ') });
                                                    }}
                                                    className="text-xs px-2 py-1 rounded border bg-blue-600/30 text-blue-300 border-blue-500/50 hover:bg-red-500 hover:border-red-500 hover:text-white transition-colors flex items-center gap-1">
                                                    {name}
                                                    <span className="material-symbols-outlined text-[10px]">close</span>
                                                </button>
                                            ))}
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        {/* Associated CIs (CRUD / Visibility) */}
                        <div className="p-4 bg-white/5 rounded-xl border border-white/5 space-y-4">
                            <h3 className="text-sm font-bold text-white uppercase flex items-center gap-2">
                                <span className="material-symbols-outlined text-sm">link</span>
                                Associated CIs (Preview)
                            </h3>
                            <p className="text-xs text-neutral-500">
                                This metric applies to the following CIs based on the criteria above.
                            </p>

                            <div className="bg-black/20 rounded-lg p-2 max-h-40 overflow-y-auto custom-scrollbar border border-white/5">
                                {usageLoading ? (
                                    <div className="text-center py-4 text-xs text-neutral-500">Loading coverage...</div>
                                ) : usageData?.cis && usageData.cis.length > 0 ? (
                                    <table className="w-full text-left border-collapse">
                                        <thead>
                                            <tr className="text-[10px] text-neutral-500 border-b border-white/10">
                                                <th className="p-2">NAME</th>
                                                <th className="p-2">IP</th>
                                                <th className="p-2">MODEL</th>
                                                <th className="p-2 text-right">ACTION</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {usageData.cis.map((ci: any, idx: number) => (
                                                <tr key={idx} className="text-xs text-neutral-300 hover:bg-white/5 group">
                                                    <td className="p-2 font-mono">{ci.name}</td>
                                                    <td className="p-2 font-mono text-neutral-500">{ci.ip}</td>
                                                    <td className="p-2 text-neutral-400">{ci.brand} {ci.model}</td>
                                                    <td className="p-2 text-right">
                                                        <button
                                                            onClick={(e) => {
                                                                e.stopPropagation();
                                                                if (confirm(`Are you sure you want to remove '${ci.name}' from this metric's applicability list?`)) {
                                                                    handleExcludeAssociatedCI(ci);
                                                                }
                                                            }}
                                                            className="text-neutral-600 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity"
                                                            title="Remove specific association"
                                                        >
                                                            <span className="material-symbols-outlined text-sm">delete</span>
                                                        </button>
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                ) : (
                                    <div className="text-center py-4 text-xs text-neutral-500 italic">
                                        No CIs currently match these criteria.
                                    </div>
                                )}
                            </div>
                        </div>

                        <div className="flex gap-4 pt-4">
                            <button onClick={() => handleSave()} className="flex-1 bg-brand-600 hover:bg-brand-500 text-white font-bold py-3 rounded-xl transition-colors">
                                SAVE METRIC
                            </button>
                            {selectedMetric && (
                                <button onClick={async () => {
                                    // 1. Check Usage
                                    try {
                                        const usage = await api.get<any>(`/metrics/${selectedMetric.id}/usage`);
                                        const count = usage.count || 0;
                                        const msg = `Are you sure you want to delete metric '${selectedMetric.id}'?\n\n` +
                                            `This metric is currently applicable to ${count} devices.\n` +
                                            `Deleting it will stop monitoring this data point for all affected devices.\n\n` +
                                            `This action cannot be undone.`;

                                        if (confirm(msg)) {
                                            await api.delete(`/metrics/${selectedMetric.id}`);
                                            setIsEditing(false);
                                            fetchMetrics();
                                        }
                                    } catch (e) {
                                        alert('Error checking metric usage');
                                    }
                                }} className="px-6 bg-red-600/20 hover:bg-red-600/40 text-red-500 font-bold py-3 rounded-xl transition-colors">
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
                        <span className="material-symbols-outlined text-6xl mb-4">analytics</span>
                        <p className="uppercase font-bold tracking-widest text-sm">Select a Metric to Edit</p>
                    </div>
                )}
            </div>
        </div >
    );
};

export default MetricsManager;
