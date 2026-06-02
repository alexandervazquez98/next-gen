
import React, { useState, useEffect } from 'react';
import { api } from '../services/api';
import { useAuth } from '../context/AuthContext';

interface Role {
    name: string;
    description: string;
    permissions: string[];
    is_system: boolean;
}

const ALL_PERMISSIONS = [
    { category: "Event Management", perms: ["EVENT_VIEW", "EVENT_ACK", "EVENT_CLOSE", "EVENT_FORCED_CLOSE"] },
    { category: "CI Management", perms: ["CI_VIEW", "CI_EDIT", "CI_DELETE"] },
    { category: "Diagnostics", perms: ["RUN_DIAGNOSTICS"] },
    { category: "System", perms: ["USER_MANAGE", "ROLE_MANAGE"] },
    { category: "Visualization", perms: ["METRICS_VIEW"] }
];

const RoleManager: React.FC = () => {
    const { hasPermission } = useAuth();
    const [roles, setRoles] = useState<Role[]>([]);
    const [view, setView] = useState<'list' | 'edit'>('list');
    const [currentRole, setCurrentRole] = useState<Role>({
        name: '', description: '', permissions: [], is_system: false
    });
    const [isNew, setIsNew] = useState(false);

    const canViewRoles = hasPermission('USER_MANAGE') || hasPermission('ROLE_MANAGE') || hasPermission('ADMIN');
    const canMutateRoles = hasPermission('ROLE_MANAGE') || hasPermission('ADMIN');

    useEffect(() => {
        if (!canViewRoles) {
            return;
        }
        fetchRoles();
    }, [canViewRoles]);

    const fetchRoles = async () => {
        try {
            const data = await api.get<Role[]>('/roles/');
            setRoles(data);
        } catch (e) {
            console.error(e);
        }
    };

    const handleEdit = (role: Role) => {
        if (role.is_system) {
            return;
        }
        setCurrentRole(role);
        setIsNew(false);
        setView('edit');
    };

    const handleCreate = () => {
        setCurrentRole({ name: '', description: '', permissions: [], is_system: false });
        setIsNew(true);
        setView('edit');
    };

    const handleSave = async () => {
        const url = isNew ? '/roles/' : `/roles/${currentRole.name}`;
        const payload = isNew
            ? {
                name: currentRole.name,
                description: currentRole.description,
                permissions: currentRole.permissions,
            }
            : {
                description: currentRole.description,
                permissions: currentRole.permissions,
            };

        try {
            if (isNew) {
                await api.post(url, payload);
            } else {
                await api.put(url, payload);
            }
            fetchRoles();
            setView('list');
        } catch (e: any) {
            console.error(e);
            alert(`Error: ${e.message}`);
        }
    };

    const handleDelete = async (name: string) => {
        if (!confirm(`Delete role ${name}?`)) return;
        try {
            await api.delete(`/roles/${name}`);
            fetchRoles();
        } catch (e: any) {
            alert(e.message);
        }
    };

    const togglePermission = (perm: string) => {
        const perms = new Set(currentRole.permissions);
        if (perms.has(perm)) perms.delete(perm);
        else perms.add(perm);
        setCurrentRole({ ...currentRole, permissions: Array.from(perms) });
    };

    if (!canViewRoles) {
        return <div className="p-8 text-neutral-500">Access Denied. Required: USER_MANAGE or ROLE_MANAGE</div>;
    }

    if (view === 'edit') {
        return (
            <div className="max-w-4xl mx-auto">
                <div className="flex justify-between items-center mb-6">
                    <h3 className="text-xl font-bold text-white uppercase tracking-wider">{isNew ? 'Create Role' : 'Edit Role'}</h3>
                    <button onClick={() => setView('list')} className="text-neutral-400 hover:text-white bg-white/5 px-4 py-2 rounded-lg text-xs font-bold uppercase">Cancel</button>
                </div>

                <div className="space-y-6 glass p-6 rounded-2xl border border-white/5">
                    <div>
                        <label className="block text-xs font-bold text-neutral-500 uppercase tracking-widest mb-1">Role Name</label>
                        <input
                            className="w-full bg-black/40 border border-white/10 p-3 rounded-lg text-white outline-none"
                            value={currentRole.name}
                            onChange={e => setCurrentRole({ ...currentRole, name: e.target.value })}
                            disabled={!isNew} // Name is ID, usually immutable or requires special handling
                        />
                    </div>
                    <div>
                        <label className="block text-xs font-bold text-neutral-500 uppercase tracking-widest mb-1">Description</label>
                        <input
                            className="w-full bg-black/40 border border-white/10 p-3 rounded-lg text-white outline-none"
                            value={currentRole.description || ''}
                            onChange={e => setCurrentRole({ ...currentRole, description: e.target.value })}
                        />
                    </div>

                    <div>
                        <label className="block text-xs font-bold text-neutral-500 uppercase tracking-widest mb-4">Permissions</label>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            {ALL_PERMISSIONS.map(cat => (
                                <div key={cat.category} className="bg-white/5 p-4 rounded-xl">
                                    <h4 className="text-sm font-bold text-neutral-300 uppercase mb-3 border-b border-white/10 pb-2">{cat.category}</h4>
                                    <div className="space-y-2">
                                        {cat.perms.map(p => (
                                            <label key={p} className="flex items-center gap-3 cursor-pointer hover:bg-white/5 p-2 rounded transition-colors">
                                                <input
                                                    type="checkbox"
                                                    checked={currentRole.permissions.includes(p)}
                                                    onChange={() => togglePermission(p)}
                                                    className="w-4 h-4 rounded border-white/10 bg-black/40 text-brand-500 focus:ring-brand-500"
                                                />
                                                <span className="text-xs font-medium text-neutral-400">{p}</span>
                                            </label>
                                        ))}
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>

                    <button
                        onClick={handleSave}
                        className="w-full bg-brand-600 hover:bg-brand-500 text-white font-bold py-3 rounded-xl uppercase tracking-widest shadow-lg shadow-brand-500/20"
                    >
                        Save Role
                    </button>
                </div>
            </div>
        );
    }

    return (
        <div>
            <div className="flex justify-between items-center mb-6">
                <h3 className="text-xl font-bold text-white uppercase tracking-wider">Available Roles</h3>
                {canMutateRoles && (
                    <button
                        onClick={handleCreate}
                        className="bg-brand-600 hover:bg-brand-500 text-white px-6 py-2 rounded-lg text-xs font-bold uppercase tracking-widest flex items-center gap-2"
                    >
                        <span className="material-symbols-outlined text-sm">add_security</span>
                        New Role
                    </button>
                )}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                {roles.map(role => (
                    <div key={role.name} className="glass p-6 rounded-2xl border border-white/5 hover:border-brand-500/30 transition-colors group">
                        <div className="flex justify-between items-start mb-4">
                            <h3 className="text-xl font-bold text-white">{role.name}</h3>
                            {role.is_system && <span className="text-[10px] bg-white/10 text-neutral-400 px-2 py-1 rounded uppercase font-bold">System</span>}
                        </div>
                        <p className="text-xs text-neutral-500 mb-6 min-h-[3rem]">{role.description}</p>

                        <div className="flex flex-wrap gap-1 mb-6">
                            {role.permissions.map(p => (
                                <span key={p} className="text-[10px] bg-black/40 text-neutral-400 px-1.5 py-0.5 rounded border border-white/5">
                                    {p.split('_')[0]}
                                </span>
                            ))}
                        </div>

                        <div className="flex justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                            {canMutateRoles && !role.is_system && (
                                <button onClick={() => handleDelete(role.name)} className="text-red-500 hover:text-red-400 p-2 hover:bg-white/5 rounded-lg" title="Delete">
                                    <span className="material-symbols-outlined text-lg">delete</span>
                                </button>
                            )}
                            {canMutateRoles && !role.is_system && (
                                <button onClick={() => handleEdit(role)} className="text-brand-400 hover:text-white p-2 hover:bg-white/5 rounded-lg" title="Edit">
                                    <span className="material-symbols-outlined text-lg">edit_note</span>
                                </button>
                            )}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
};

export default RoleManager;
