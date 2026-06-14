import React, { useMemo, useState, useEffect } from 'react';
import { api } from '../services/api';
import CategoryIcon from './CategoryIcon';
import {
	CategoryIconKey,
	findCategoryIcons,
	resolveCategoryIconKey,
} from '../utils/categoryIcons';

// Types
interface HardwareModel {
	brand: string;
	model: string;
	category?: string;
	owner?: string;
}

interface Category {
	name: string;
	icon_key?: string | null;
}

interface OwnerGroup {
	name: string;
	users: { name: string, email?: string, phone?: string }[];
}

const normalizeCategoryForIcon = (category?: Category | null): CategoryIconKey =>
	resolveCategoryIconKey({
		iconKey: category?.icon_key,
		categoryName: category?.name,
	});

const CatalogManager: React.FC = () => {
	type Tab = 'HARDWARE' | 'CATEGORIES' | 'OWNERS';
	const [activeTab, setActiveTab] = useState<Tab>('HARDWARE');

	// Data State
	const [models, setModels] = useState<HardwareModel[]>([]);
	const [categories, setCategories] = useState<Category[]>([]);
	const [owners, setOwners] = useState<OwnerGroup[]>([]);

	// Editor State
	const [isEditing, setIsEditing] = useState(false);
	const [selectedItem, setSelectedItem] = useState<any>(null);
	const [formData, setFormData] = useState<any>({});
	const [iconSearchQuery, setIconSearchQuery] = useState('');
	const [selectedIconKey, setSelectedIconKey] = useState<CategoryIconKey>('generic');

	const visibleIcons = useMemo(
		() => findCategoryIcons(iconSearchQuery),
		[iconSearchQuery],
	);

	useEffect(() => {
		fetchData();
	}, []);

	const clearEditorState = () => {
		setSelectedItem(null);
		setFormData({});
		setIconSearchQuery('');
		setSelectedIconKey('generic');
	};

	const fetchData = async () => {
		try {
			const [resModels, resCats, resOwners] = await Promise.all([
				api.get<HardwareModel[]>('/hardware'),
				api.get<Category[]>('/categories'),
				api.get<OwnerGroup[]>('/owners'),
			]);
			setModels(Array.isArray(resModels) ? resModels : []);
			setCategories(Array.isArray(resCats) ? resCats : []);
			setOwners(Array.isArray(resOwners) ? resOwners : []);
		} catch (e) {
			console.error('Error fetching catalog data', e);
		}
	};

	// --- Actions ---

	const handleEdit = (item: any) => {
		setSelectedItem(item);
		setFormData({ ...item });
		if (activeTab === 'CATEGORIES') {
			setIconSearchQuery('');
			setSelectedIconKey(normalizeCategoryForIcon(item));
		}
		setIsEditing(true);
	};

	const handleCreate = () => {
		clearEditorState();
		setIsEditing(true);
	};

	const closeEditor = () => {
		setIsEditing(false);
		clearEditorState();
	};

	const handleSave = async () => {
		let url = '';
		let method = 'POST';
		let body = { ...formData }; // Clone to avoid mutation

		try {
			if (activeTab === 'HARDWARE') {
				if (selectedItem) {
					// Update
					url = `/hardware/${selectedItem.brand}/${selectedItem.model}`;
					method = 'PUT';
					// Body matches HardwareModelUpdate
					body = {
						brand: formData.brand, // Allow rename
						model: formData.model,
						category: formData.category,
						owner: formData.owner,
					};
				} else {
					// Create
					url = '/hardware';
				}
			} else if (activeTab === 'CATEGORIES') {
				if (selectedItem) {
					url = `/categories/${selectedItem.name}`;
					method = 'PUT';
					body = {
						name: formData.name,
						icon_key: selectedIconKey,
					};
				} else {
					url = '/categories';
					body = {
						name: formData.name,
						icon_key: selectedIconKey,
					};
				}
			} else if (activeTab === 'OWNERS') {
				if (selectedItem) {
					url = `/owners/${selectedItem.name}`;
					method = 'PUT';
					// Ensure users is a list if present
					if (formData.users && typeof formData.users === 'string') {
						// Parse or handle string? Assuming basic object here.
					}
				} else {
					url = '/owners';
				}
			}

			if (method === 'POST') {
				await api.post(url, body);
			} else {
				await api.put(url, body);
			}

			setIsEditing(false);
			clearEditorState();
			fetchData();
		} catch (e) {
			alert('Error saving: ' + e);
		}
	};

	const handleDelete = async (item: any) => {
		if (!confirm(`Are you sure you want to delete ${item.name || (item.brand + ' ' + item.model)}?`)) return;

		let url = '';
		if (activeTab === 'HARDWARE') url = `/hardware/${item.brand}/${item.model}`;
		else if (activeTab === 'CATEGORIES') url = `/categories/${item.name}`;
		else if (activeTab === 'OWNERS') url = `/owners/${item.name}`;

		try {
			await api.delete(url);
			fetchData();
		} catch (e) {
			alert('Error deleting: ' + e);
		}
	};

	const renderCategoryIconSelector = () => (
		<div className="space-y-3">
			<label className="text-xs font-bold text-neutral-500 uppercase">Current icon</label>
			<div className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 bg-black/40">
				<CategoryIcon
					iconKey={selectedIconKey}
					categoryName={formData.name}
					className="text-2xl"
					iconClassName="text-brand-200"
				/>
				<span className="text-sm text-neutral-300">
					{selectedIconKey === 'generic' ? 'Generic/default' : selectedIconKey.replace('_', ' ')}
				</span>
			</div>

			<div className="space-y-2">
				<label className="text-xs font-bold text-neutral-500 uppercase" htmlFor="icon-search">
					Search icons
				</label>
				<input
					id="icon-search"
					type="text"
					className="w-full bg-black/40 border border-white/10 p-2 rounded text-white"
					placeholder="Search icon names..."
					value={iconSearchQuery}
					onChange={(event) => setIconSearchQuery(event.target.value)}
				/>
			</div>

			<div className="grid grid-cols-3 gap-2 max-h-56 overflow-y-auto pr-1">
				{visibleIcons.map((icon) => (
					<button
						type="button"
						key={icon.key}
						className={`rounded-lg border p-2 text-left transition ${selectedIconKey === icon.key ? 'border-brand-400 bg-brand-500/20' : 'border-white/10 bg-white/5 hover:bg-white/10'}`}
						onClick={() => setSelectedIconKey(icon.key)}
						aria-label={`Select ${icon.label} icon`}
					>
						<div className="flex items-center gap-2">
							<CategoryIcon iconKey={icon.key} className="text-xl" />
							<span className="text-xs text-neutral-300">{icon.label}</span>
						</div>
					</button>
				))}
			</div>
		</div>
	);

	const categoryEditHeader = selectedItem ? 'Edit' : 'New';

	return (
		<div className="h-full flex flex-col p-6">
			<div className="flex justify-between items-center mb-6">
				<h2 className="text-3xl font-black text-white tracking-tighter uppercase">Catalog Manager</h2>
				<div className="flex gap-2">
					{(['HARDWARE', 'CATEGORIES', 'OWNERS'] as Tab[]).map((tab) => (
						<button
							key={tab}
							onClick={() => {
								setActiveTab(tab);
								setIsEditing(false);
								clearEditorState();
							}}
							className={`px-4 py-2 rounded-lg font-bold text-sm tracking-wider transition-colors ${activeTab === tab ? 'bg-brand-500 text-white' : 'bg-white/5 text-neutral-400 hover:bg-white/10'
								}`}
						>
							{tab}
						</button>
					))}
				</div>
			</div>

			<div className={`flex-1 glass rounded-2xl border border-white/5 overflow-hidden flex flex-col`}>
				{/* Toolbar */}
				<div className="p-4 border-b border-white/5 bg-black/20 flex justify-end">
					<button
						onClick={handleCreate}
						className="bg-brand-600 hover:bg-brand-500 text-white px-4 py-2 rounded-lg font-bold text-sm flex items-center gap-2"
					>
						<span className="material-symbols-outlined text-sm">add</span>
						NEW {activeTab.slice(0, -1)}
					</button>
				</div>

				{/* List Content */}
				<div className="flex-1 overflow-y-auto custom-scrollbar p-2 space-y-2">
					{/* HARDWARE LIST */}
					{activeTab === 'HARDWARE' &&
						models.map((m, i) => (
							<div key={i} className="p-4 rounded-xl border border-white/5 bg-white/5 flex justify-between items-center hover:bg-white/10 transition-colors">
								<div>
									<div className="font-bold text-white">{m.brand} <span className="text-neutral-400 font-normal">{m.model}</span></div>
									<div className="flex gap-2 mt-1">
										<span className="text-xs bg-white/10 px-2 py-0.5 rounded text-neutral-300">{m.category || 'No Category'}</span>
										<span className="text-xs bg-white/10 px-2 py-0.5 rounded text-neutral-300">{m.owner || 'No Owner'}</span>
									</div>
								</div>
								<div className="flex gap-2">
							<button
								onClick={() => handleEdit(m)}
								className="text-neutral-500 hover:text-white"
								aria-label="edit"
							>
										<span className="material-symbols-outlined">edit</span>
									</button>
									<button
										onClick={() => handleDelete(m)}
										className="text-neutral-500 hover:text-red-500"
										aria-label={`delete hardware ${m.brand} ${m.model}`}
									>
										<span className="material-symbols-outlined">delete</span>
									</button>
								</div>
							</div>
						))}

					{/* CATEGORIES LIST */}
					{activeTab === 'CATEGORIES' &&
						categories.map((c, i) => (
							<div key={i} className="p-4 rounded-xl border border-white/5 bg-white/5 flex justify-between items-center hover:bg-white/10 transition-colors">
								<div className="flex items-center gap-3">
									<CategoryIcon
										iconKey={c.icon_key}
										categoryName={c.name}
										className="text-xl"
									/>
									<span className="font-bold text-white">{c.name}</span>
								</div>
								<div className="flex gap-2">
										<button
											onClick={() => handleEdit(c)}
											className="text-neutral-500 hover:text-white"
											aria-label={`edit category ${c.name}`}
										>
										<span className="material-symbols-outlined">edit</span>
									</button>
									<button
										onClick={() => handleDelete(c)}
										className="text-neutral-500 hover:text-red-500"
										aria-label={`delete category ${c.name}`}
									>
										<span className="material-symbols-outlined">delete</span>
									</button>
								</div>
							</div>
						))}

					{/* OWNERS LIST */}
					{activeTab === 'OWNERS' &&
						owners.map((o, i) => (
							<div key={i} className="p-4 rounded-xl border border-white/5 bg-white/5 flex justify-between items-center hover:bg-white/10 transition-colors">
								<div>
									<div className="font-bold text-white">{o.name}</div>
									<div className="text-xs text-neutral-500 mt-1">{o.users?.length || 0} users</div>
								</div>
								<div className="flex gap-2">
							<button
								onClick={() => handleEdit(o)}
								className="text-neutral-500 hover:text-white"
								aria-label="edit"
							>
										<span className="material-symbols-outlined">edit</span>
									</button>
									<button
										onClick={() => handleDelete(o)}
										className="text-neutral-500 hover:text-red-500"
										aria-label={`delete owner ${o.name}`}
									>
										<span className="material-symbols-outlined">delete</span>
									</button>
								</div>
							</div>
						))}
				</div>
			</div>

			{/* Edit Modal (Simple Inline Overlay for speed) */}
			{isEditing && (
				<div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50">
					<div className="bg-[#0a0a0a] border border-white/10 rounded-2xl p-6 w-[620px] max-h-[80vh] overflow-y-auto">
						<h3 className="text-xl font-bold text-white mb-6 uppercase">
							{categoryEditHeader} {activeTab.slice(0, -1)}
						</h3>

						<div className="space-y-4">
							{/* Hardware Form */}
							{activeTab === 'HARDWARE' && (
								<>
									<div className="grid grid-cols-2 gap-4">
										<div className="space-y-2">
											<label className="text-xs font-bold text-neutral-500 uppercase">Brand</label>
											<input
												className="input-field w-full bg-black/40 border border-white/10 p-2 rounded text-white"
												value={formData.brand || ''}
												onChange={(e) => setFormData({ ...formData, brand: e.target.value })}
										/>
									</div>
									<div className="space-y-2">
										<label className="text-xs font-bold text-neutral-500 uppercase">Model</label>
										<input
											className="input-field w-full bg-black/40 border border-white/10 p-2 rounded text-white"
											value={formData.model || ''}
											onChange={(e) => setFormData({ ...formData, model: e.target.value })}
										/>
									</div>
								</div>
								<div className="space-y-2">
									<label className="text-xs font-bold text-neutral-500 uppercase">Category</label>
									<select
										className="w-full bg-black/40 border border-white/10 p-2 rounded text-white"
										value={formData.category || ''}
										onChange={(e) => setFormData({ ...formData, category: e.target.value })}
									>
										<option value="">Select...</option>
										{categories.map((c) => (
											<option key={c.name} value={c.name}>{c.name}</option>
										))}
									</select>
								</div>
								<div className="space-y-2">
									<label className="text-xs font-bold text-neutral-500 uppercase">Default Owner</label>
									<select
										className="w-full bg-black/40 border border-white/10 p-2 rounded text-white"
										value={formData.owner || ''}
										onChange={(e) => setFormData({ ...formData, owner: e.target.value })}
									>
										<option value="">Select...</option>
										{owners.map((o) => (
											<option key={o.name} value={o.name}>{o.name}</option>
										))}
									</select>
								</div>
							</>
							)}

							{/* Category Form */}
							{activeTab === 'CATEGORIES' && (
								<div className="space-y-4">
									<div className="space-y-2">
										<label className="text-xs font-bold text-neutral-500 uppercase">Name</label>
										<input
											className="input-field w-full bg-black/40 border border-white/10 p-2 rounded text-white"
											value={formData.name || ''}
											onChange={(e) => setFormData({ ...formData, name: e.target.value })}
										/>
									</div>

									{renderCategoryIconSelector()}
								</div>
							)}

							{/* Owner Form */}
							{activeTab === 'OWNERS' && (
								<div className="space-y-2">
									<label className="text-xs font-bold text-neutral-500 uppercase">Name</label>
									<input
										className="input-field w-full bg-black/40 border border-white/10 p-2 rounded text-white"
										value={formData.name || ''}
										onChange={(e) => setFormData({ ...formData, name: e.target.value })}
									/>
									<div className="text-xs text-brand-400 mt-2">
										* To manage users, please use the User Management tab (future feature).
									</div>
								</div>
							)}

							<div className="flex gap-4 mt-6">
								<button onClick={closeEditor} className="flex-1 bg-white/5 hover:bg-white/10 text-white font-bold py-3 rounded-xl transition-colors">
									CANCEL
								</button>
								<button onClick={handleSave} className="flex-1 bg-brand-600 hover:bg-brand-500 text-white font-bold py-3 rounded-xl transition-colors">
									SAVE
								</button>
							</div>
						</div>
					</div>
				</div>
			)}
		</div>
	);
};

export default CatalogManager;
