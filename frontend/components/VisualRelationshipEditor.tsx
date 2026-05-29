import type React from "react";
import { useMemo, useState } from "react";
import type { GraphNode } from "../types";
import { api } from "../services/api";
import type { LinkData } from "./RelationshipManager";
import {
	canDeleteRelationship,
	isReadOnlyRelationship,
} from "./relationshipCapabilities";

const SUPPORTED_RELATIONSHIP_TYPES = [
	"CONNECTS_TO",
	"DEPENDS_ON",
	"HOSTED_ON",
	"MANAGES",
	"USES",
	"PROVIDES",
] as const;

const CI_TYPES: GraphNode["type"][] = [
	"SERVICE",
	"INFRASTRUCTURE",
	"APPLICATION",
	"USER",
	"CLOUD_RESOURCE",
];

const CI_STATUSES: GraphNode["status"][] = [
	"OK",
	"ACTIVE",
	"EXCEPTION",
	"MAINTENANCE",
];

type CiFormState = {
	id: string;
	label: string;
	type: GraphNode["type"] | "";
	status: GraphNode["status"];
	ip: string;
	owner: string;
	location_name: string;
};

const EMPTY_CI_FORM: CiFormState = {
	id: "",
	label: "",
	type: "",
	status: "OK",
	ip: "",
	owner: "",
	location_name: "",
};

interface VisualRelationshipEditorProps {
	nodes: GraphNode[];
	links: LinkData[];
	onClose: () => void;
	onMutated: () => void | Promise<void>;
}

const nodeLabel = (node?: GraphNode) => node?.label || node?.id || "Unknown CI";

const toCiForm = (node: GraphNode): CiFormState => ({
	id: node.id,
	label: node.label,
	type: node.type,
	status: node.status || "OK",
	ip: node.ip || "",
	owner: node.owner || "",
	location_name: node.location_name || "",
});

const VisualRelationshipEditor: React.FC<VisualRelationshipEditorProps> = ({
	nodes,
	links,
	onClose,
	onMutated,
}) => {
	const [sourceId, setSourceId] = useState("");
	const [targetId, setTargetId] = useState("");
	const [relationship, setRelationship] =
		useState<(typeof SUPPORTED_RELATIONSHIP_TYPES)[number]>("CONNECTS_TO");
	const [error, setError] = useState("");
	const [saving, setSaving] = useState(false);
	const [selectedCiId, setSelectedCiId] = useState("");
	const [ciForm, setCiForm] = useState<CiFormState>(EMPTY_CI_FORM);
	const [ciError, setCiError] = useState("");
	const [ciSaving, setCiSaving] = useState(false);

	const ciLinks = useMemo(
		() => links.filter((link) => link.relationship !== "HAS_METRIC"),
		[links],
	);
	const nodeMap = useMemo(
		() => new Map(nodes.map((node) => [node.id, node])),
		[nodes],
	);
	const positionedNodes = useMemo(() => {
		const centerX = 500;
		const centerY = 300;
		const radius = nodes.length > 10 ? 250 : 210;
		return nodes.map((node, index) => {
			const angle =
				nodes.length <= 1
					? 0
					: (index / nodes.length) * Math.PI * 2 - Math.PI / 2;
			return {
				node,
				x: nodes.length <= 1 ? centerX : centerX + Math.cos(angle) * radius,
				y: nodes.length <= 1 ? centerY : centerY + Math.sin(angle) * radius,
			};
		});
	}, [nodes]);
	const positionMap = useMemo(
		() => new Map(positionedNodes.map((item) => [item.node.id, item])),
		[positionedNodes],
	);

	const selectedCi = selectedCiId ? nodeMap.get(selectedCiId) : undefined;
	const isEditingCi = Boolean(selectedCi);

	const updateCiForm = (field: keyof CiFormState, value: string) => {
		setCiForm((current) => ({ ...current, [field]: value }));
	};

	const startNewCi = () => {
		setSelectedCiId("");
		setCiForm(EMPTY_CI_FORM);
		setCiError("");
	};

	const validateCiForm = () => {
		if (!ciForm.id.trim()) return "CI ID is required.";
		if (!ciForm.label.trim()) return "Label is required.";
		if (!ciForm.type) return "Type is required.";
		return "";
	};

	const buildCiPayload = (): GraphNode => ({
		...(selectedCi ?? {}),
		id: ciForm.id.trim(),
		label: ciForm.label.trim(),
		type: ciForm.type as GraphNode["type"],
		status: ciForm.status || "OK",
		metadata: selectedCi?.metadata ?? {},
		ip: ciForm.ip.trim() || undefined,
		owner: ciForm.owner.trim() || undefined,
		location_name: ciForm.location_name.trim() || undefined,
	});

	const handleSaveCi = async () => {
		const validationError = validateCiForm();
		if (validationError) {
			setCiError(validationError);
			return;
		}
		setCiSaving(true);
		setCiError("");
		try {
			await api.post("/nodes", buildCiPayload());
			await onMutated();
		} catch (err) {
			console.error(err);
			setCiError("Could not save CI.");
		} finally {
			setCiSaving(false);
		}
	};

	const handleDeleteCi = async () => {
		if (!selectedCi) return;
		if (!confirm(`Delete CI ${selectedCi.id}?`)) return;
		setCiSaving(true);
		setCiError("");
		try {
			await api.delete(`/nodes/${encodeURIComponent(selectedCi.id)}`);
			setSelectedCiId("");
			setCiForm(EMPTY_CI_FORM);
			await onMutated();
		} catch (err) {
			console.error(err);
			setCiError("Could not delete CI.");
		} finally {
			setCiSaving(false);
		}
	};

	const selectNode = (id: string) => {
		setError("");
		setCiError("");
		const node = nodeMap.get(id);
		if (node) {
			setSelectedCiId(id);
			setCiForm(toCiForm(node));
		}
		if (!sourceId || (sourceId && targetId)) {
			setSourceId(id);
			setTargetId("");
			return;
		}
		if (id === sourceId) {
			setError("Source and target must be different CIs.");
			return;
		}
		setTargetId(id);
	};

	const handleCreate = async () => {
		if (!sourceId || !targetId) {
			setError("Select a source CI and a target CI.");
			return;
		}
		if (sourceId === targetId) {
			setError("Source and target must be different CIs.");
			return;
		}
		setSaving(true);
		setError("");
		try {
			await api.post("/links", {
				source: sourceId,
				target: targetId,
				relationship,
			});
			setTargetId("");
			await onMutated();
		} catch (err) {
			console.error(err);
			setError("Could not create relationship.");
		} finally {
			setSaving(false);
		}
	};

	const handleDelete = async (link: LinkData) => {
		if (!canDeleteRelationship(link.relationship)) return;

		setSaving(true);
		setError("");
		try {
			await api.delete("/links", link);
			await onMutated();
		} catch (err) {
			console.error(err);
			setError("Could not delete relationship.");
		} finally {
			setSaving(false);
		}
	};

	return (
		<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/90 p-6 backdrop-blur-xl">
			<div className="flex h-full w-full max-w-7xl flex-col rounded-2xl border border-white/10 bg-neutral-950 shadow-2xl">
				<div className="flex items-center justify-between border-b border-white/10 px-6 py-4">
					<div>
						<h2 className="text-xl font-black uppercase text-white">
							Visual Relationship Editor
						</h2>
						<p className="text-xs font-bold uppercase tracking-widest text-neutral-500">
							Click source CI, click target CI, choose type, then create link
						</p>
					</div>
					<button
						onClick={onClose}
						className="text-neutral-400 hover:text-white"
						aria-label="Close visual relationship editor"
					>
						<span className="material-symbols-outlined text-3xl">close</span>
					</button>
				</div>

				<div className="grid flex-1 min-h-0 grid-cols-[1fr_360px] gap-4 p-4">
					<div className="relative overflow-hidden rounded-2xl border border-white/10 bg-[radial-gradient(circle_at_center,rgba(59,130,246,0.16),rgba(0,0,0,0.15)_45%,rgba(0,0,0,0.55))]">
						<svg
							className="absolute inset-0 h-full w-full"
							viewBox="0 0 1000 620"
							aria-label="Existing CI relationship links"
						>
							{ciLinks.map((link) => {
								const source = positionMap.get(link.source);
								const target = positionMap.get(link.target);
								if (!source || !target) return null;
								return (
									<g key={`${link.source}-${link.target}-${link.relationship}`}>
										<line
											x1={source.x}
											y1={source.y}
											x2={target.x}
											y2={target.y}
											className="stroke-brand-400/40"
											strokeWidth={2}
										/>
										<text
											x={(source.x + target.x) / 2}
											y={(source.y + target.y) / 2}
											className="fill-neutral-300 text-[10px] font-bold"
										>
											{link.relationship}
										</text>
									</g>
								);
							})}
						</svg>
						{positionedNodes.map(({ node, x, y }) => {
							const selectedAsSource = sourceId === node.id;
							const selectedAsTarget = targetId === node.id;
							return (
								<button
									key={node.id}
									type="button"
									onClick={() => selectNode(node.id)}
									className={`absolute w-36 -translate-x-1/2 -translate-y-1/2 rounded-2xl border px-3 py-2 text-left shadow-xl transition-all ${selectedAsSource ? "border-brand-400 bg-brand-500/25 text-white" : selectedAsTarget ? "border-accent-cyan bg-cyan-500/20 text-white" : "border-white/10 bg-neutral-900/90 text-neutral-300 hover:border-white/30"}`}
									style={{
										left: `${(x / 1000) * 100}%`,
										top: `${(y / 620) * 100}%`,
									}}
									aria-label={`CI node ${nodeLabel(node)}`}
								>
									<span className="block truncate text-xs font-black uppercase">
										{nodeLabel(node)}
									</span>
									<span className="block truncate font-mono text-[10px] opacity-60">
										{node.id}
									</span>
								</button>
							);
						})}
					</div>

					<aside className="flex min-h-0 flex-col gap-4 rounded-2xl border border-white/10 bg-white/[0.03] p-4">
						<div className="rounded-xl border border-white/10 bg-black/20 p-3">
							<div className="flex items-center justify-between gap-2">
								<p className="text-[10px] font-black uppercase tracking-widest text-neutral-500">
									CI details — {isEditingCi ? "editing" : "new"}
								</p>
								<button
									type="button"
									onClick={startNewCi}
									className="text-[10px] font-black uppercase text-brand-300 hover:text-brand-200"
								>
									New CI
								</button>
							</div>
							<div className="mt-3 grid grid-cols-2 gap-2 text-xs text-neutral-300">
								<label className="col-span-2 space-y-1">
									<span className="text-neutral-500">CI ID</span>
									<input
										aria-label="CI ID"
										value={ciForm.id}
										disabled={isEditingCi || ciSaving}
										onChange={(event) => updateCiForm("id", event.target.value)}
										className="w-full rounded-lg border border-white/10 bg-black/30 p-2 font-mono text-white disabled:opacity-60"
									/>
								</label>
								<label className="col-span-2 space-y-1">
									<span className="text-neutral-500">Label</span>
									<input
										aria-label="CI label"
										value={ciForm.label}
										disabled={ciSaving}
										onChange={(event) =>
											updateCiForm("label", event.target.value)
										}
										className="w-full rounded-lg border border-white/10 bg-black/30 p-2 text-white"
									/>
								</label>
								<label className="space-y-1">
									<span className="text-neutral-500">Type</span>
									<select
										aria-label="CI type"
										value={ciForm.type}
										disabled={ciSaving}
										onChange={(event) =>
											updateCiForm("type", event.target.value)
										}
										className="w-full rounded-lg border border-white/10 bg-black/30 p-2 font-mono text-white"
									>
										<option value="">Select type</option>
										{CI_TYPES.map((type) => (
											<option key={type} value={type}>
												{type}
											</option>
										))}
									</select>
								</label>
								<label className="space-y-1">
									<span className="text-neutral-500">Status</span>
									<select
										aria-label="CI status"
										value={ciForm.status}
										disabled={ciSaving}
										onChange={(event) =>
											updateCiForm("status", event.target.value)
										}
										className="w-full rounded-lg border border-white/10 bg-black/30 p-2 font-mono text-white"
									>
										{CI_STATUSES.map((status) => (
											<option key={status} value={status}>
												{status}
											</option>
										))}
									</select>
								</label>
								{ciError && (
									<div className="col-span-2 rounded-lg border border-red-500/30 bg-red-500/10 p-2 text-red-300">
										{ciError}
									</div>
								)}
								<button
									type="button"
									onClick={handleSaveCi}
									disabled={ciSaving}
									className="col-span-2 rounded-xl bg-cyan-600 py-2 text-xs font-black uppercase text-white disabled:cursor-not-allowed disabled:opacity-40"
								>
									{ciSaving
										? "Saving CI..."
										: isEditingCi
											? "Save CI"
											: "Create CI"}
								</button>
								<button
									type="button"
									onClick={handleDeleteCi}
									disabled={!isEditingCi || ciSaving}
									className="col-span-2 rounded-xl border border-red-500/30 py-2 text-xs font-black uppercase text-red-300 disabled:cursor-not-allowed disabled:opacity-40"
								>
									Delete CI
								</button>
							</div>
						</div>

						<div className="rounded-xl border border-white/10 bg-black/20 p-3">
							<p className="text-[10px] font-black uppercase tracking-widest text-neutral-500">
								New relationship
							</p>
							<div className="mt-3 space-y-2 text-xs text-neutral-300">
								<div>
									<span className="text-neutral-500">Source:</span>{" "}
									{nodeLabel(nodeMap.get(sourceId))}
								</div>
								<div>
									<span className="text-neutral-500">Target:</span>{" "}
									{targetId
										? nodeLabel(nodeMap.get(targetId))
										: "Select target"}
								</div>
								<select
									value={relationship}
									onChange={(event) =>
										setRelationship(event.target.value as typeof relationship)
									}
									className="mt-2 w-full rounded-lg border border-white/10 bg-black/30 p-2 font-mono text-white"
									aria-label="Relationship type"
								>
									{SUPPORTED_RELATIONSHIP_TYPES.map((type) => (
										<option key={type} value={type}>
											{type}
										</option>
									))}
								</select>
								{error && (
									<div className="rounded-lg border border-red-500/30 bg-red-500/10 p-2 text-red-300">
										{error}
									</div>
								)}
								<button
									onClick={handleCreate}
									disabled={
										saving || !sourceId || !targetId || sourceId === targetId
									}
									className="w-full rounded-xl bg-brand-600 py-2 text-xs font-black uppercase text-white disabled:cursor-not-allowed disabled:opacity-40"
								>
									{saving ? "Saving..." : "Create relationship"}
								</button>
							</div>
						</div>

						<div className="min-h-0 flex-1 overflow-y-auto rounded-xl border border-white/10 bg-black/20">
							<div className="sticky top-0 bg-neutral-950/90 p-3 text-[10px] font-black uppercase tracking-widest text-neutral-500">
								Existing links
							</div>
							{ciLinks.map((link) => {
								const readOnly = isReadOnlyRelationship(link.relationship);

								return (
									<div
										key={`${link.source}-${link.target}-${link.relationship}`}
										className="border-t border-white/5 p-3 text-xs text-neutral-300"
									>
										<div className="font-bold text-white">
											{link.source_label || link.source} →{" "}
											{link.target_label || link.target}
										</div>
										<div className="mt-1 flex items-center justify-between gap-2">
											<span className="flex items-center gap-2">
												<span className="rounded bg-white/10 px-2 py-1 font-mono text-[10px]">
													{link.relationship}
												</span>
												{readOnly && (
													<span className="rounded border border-amber-400/30 bg-amber-400/10 px-2 py-1 text-[10px] font-black uppercase text-amber-200">
														Read-only
													</span>
												)}
											</span>
											{canDeleteRelationship(link.relationship) && (
												<button
													onClick={() => handleDelete(link)}
													className="text-red-300 hover:text-red-200"
													disabled={saving}
												>
													Delete
												</button>
											)}
										</div>
									</div>
								);
							})}
							{ciLinks.length === 0 && (
								<div className="p-6 text-center text-xs text-neutral-500">
									No CI links yet.
								</div>
							)}
						</div>
					</aside>
				</div>
			</div>
		</div>
	);
};

export default VisualRelationshipEditor;
