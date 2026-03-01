
import React, { useState, useEffect } from 'react';
import { api } from '../services/api';
import { useAuth } from '../context/AuthContext';
import RoleManager from './RoleManager';

interface User {
    username: string;
    role: string;
    permissions: string[];
    allowed_locations: string[];
    force_password_change?: boolean;
    phone?: string | null;
    email?: string | null;
}

interface Role {
    name: string;
    permissions: string[];
}

const ALL_PERMISSIONS = [
    { category: "Event Management", perms: ["EVENT_VIEW", "EVENT_ACK", "EVENT_CLOSE"] },
    { category: "CI Management", perms: ["CI_VIEW", "CI_EDIT", "CI_DELETE"] },
    { category: "Diagnostics", perms: ["RUN_DIAGNOSTICS"] },
    { category: "System", perms: ["USER_MANAGE", "ROLE_MANAGE"] }
];

const UserManager: React.FC = () => {
    const { token, hasPermission } = useAuth();
    const [activeTab, setActiveTab] = useState<'users' | 'roles'>('users');
    const [users, setUsers] = useState<User[]>([]);
    const [roles, setRoles] = useState<Role[]>([]);

    // User Form State
    const [editingUser, setEditingUser] = useState<User | null>(null);
    const [newUser, setNewUser] = useState({
        username: '',
        password: '',
        role: 'VIEWER',
        permissions: [] as string[],
        phone: null as string | null,
        email: null as string | null
    });
    const [showPerms, setShowPerms] = useState(false);

    useEffect(() => {
        if (token) {
            fetchUsers();
            fetchRoles();
        }
    }, [token, activeTab]); // Refresh when tab changes

    const fetchUsers = async () => {
        try {
            const data = await api.get<User[]>('/users/');
            setUsers(data);
        } catch (e) { console.error(e); }
    };

    const fetchRoles = async () => {
        try {
            const data = await api.get<Role[]>('/roles/');
            setRoles(data);
            if (newUser.permissions.length === 0) {
                const currentRole = data.find(r => r.name === newUser.role);
                if (currentRole) setNewUser(prev => ({ ...prev, permissions: currentRole.permissions }));
            }
        } catch (e) { console.error(e); }
    };

    const handleRoleChange = (roleName: string) => {
        const role = roles.find(r => r.name === roleName);
        if (editingUser) {
            setEditingUser(prev => prev ? ({
                ...prev,
                role: roleName,
                permissions: role ? role.permissions : []
            }) : null);
        } else {
            setNewUser(prev => ({
                ...prev,
                role: roleName,
                permissions: role ? role.permissions : []
            }));
        }
    };

    const togglePermission = (perm: string) => {
        if (editingUser) {
            const current = new Set(editingUser.permissions);
            if (current.has(perm)) current.delete(perm);
            else current.add(perm);
            setEditingUser(prev => prev ? ({ ...prev, permissions: Array.from(current) }) : null);
        } else {
            const current = new Set(newUser.permissions);
            if (current.has(perm)) current.delete(perm);
            else current.add(perm);
            setNewUser(prev => ({ ...prev, permissions: Array.from(current) }));
        }
    };

    const resetNewUserForm = () => {
        const defRole = roles.find(r => r.name === 'VIEWER');
        setNewUser({
            username: '',
            password: '',
            role: 'VIEWER',
            permissions: defRole ? defRole.permissions : [],
            phone: null,
            email: null
        });
        setEditingUser(null);
        setShowPerms(false);
    };

    const handleCreateOrUpdate = async () => {
        if (!token) return;

        // Update handling
        if (editingUser) {
            try {
                await api.put(`/users/${editingUser.username}`, {
                    role: editingUser.role,
                    permissions: editingUser.permissions,
                });

                fetchUsers();
                resetNewUserForm();
            } catch (e: any) {
                console.error(e);
                alert(`Update failed: ${e.message}`);
            }
            return;
        }

        // Create handling
        try {
            await api.post('/users/', {
                username: newUser.username,
                password: newUser.password,
                role: newUser.role,
                permissions: newUser.permissions,
                allowed_locations: []
            });
            fetchUsers();
            resetNewUserForm();
        } catch (e: any) {
            console.error(e);
            alert(`Failed: ${e.message}`);
        }
    };

    const startEdit = (user: User) => {
        setEditingUser(user);
        setShowPerms(true);
    };

    const handleDelete = async (username: string) => {
        if (!confirm(`Delete user ${username}?`)) return;
        await api.delete(`/users/${username}`);
        fetchUsers();
    };

    const handleResetPassword = async (username: string) => {
        const newPass = prompt(`Enter new password for ${username}:`);
        if (!newPass) return;
        await api.post(`/users/${username}/reset`, { new_password: newPass });
    };

    if (!hasPermission('USER_MANAGE') && !hasPermission('ADMIN')) {
        return <div className="p-8 text-neutral-500">Access Denied.</div>;
    }

    const activeUser = editingUser || newUser;

    return (
        <div className="h-full flex flex-col p-8 space-y-6">
            <div className="flex justify-between items-end border-b border-white/5 pb-6">
                <div>
                    <h2 className="text-3xl font-black text-white uppercase tracking-tighter">User Management</h2>
                    <p className="text-xs text-neutral-400 font-bold uppercase tracking-widest mt-1">Access Control & Security</p>
                </div>

                {/* Tabs */}
                <div className="flex bg-black/40 p-1 rounded-xl border border-white/5">
                    <button
                        onClick={() => setActiveTab('users')}
                        className={`px-4 py-2 rounded-lg text-xs font-bold uppercase tracking-wider transition-all ${activeTab === 'users' ? 'bg-brand-600 text-white shadow-lg' : 'text-neutral-500 hover:text-white'}`}
                    >
                        Users
                    </button>
                    {(hasPermission('ADMIN') || hasPermission('ROLE_MANAGE')) && (
                        <button
                            onClick={() => setActiveTab('roles')}
                            className={`px-4 py-2 rounded-lg text-xs font-bold uppercase tracking-wider transition-all ${activeTab === 'roles' ? 'bg-brand-600 text-white shadow-lg' : 'text-neutral-500 hover:text-white'}`}
                        >
                            Access Roles
                        </button>
                    )}
                </div>
            </div>

            {activeTab === 'roles' ? (
                <RoleManager />
            ) : (
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    {/* Create/Edit User Form */}
                    <div className="glass p-6 rounded-2xl border border-white/5 h-fit">
                        <div className="flex justify-between items-center mb-6">
                            <h3 className="text-xl font-bold text-white uppercase tracking-wider">
                                {editingUser ? 'Edit User' : 'Create New User'}
                            </h3>
                            {editingUser && (
                                <button onClick={resetNewUserForm} className="text-xs text-neutral-400 hover:text-white border border-white/10 px-2 py-1 rounded">
                                    CANCEL
                                </button>
                            )}
                        </div>

                        <div className="space-y-4">
                            <div>
                                <label className="block text-xs font-bold text-neutral-500 uppercase tracking-widest mb-1">Username</label>
                                <input
                                    className="w-full bg-black/40 border border-white/10 p-3 rounded-lg text-white focus:border-brand-500 outline-none disabled:opacity-50"
                                    placeholder="e.g. jdoe"
                                    value={activeUser.username}
                                    onChange={e => !editingUser && setNewUser({ ...newUser, username: e.target.value })}
                                    disabled={!!editingUser}
                                />
                            </div>

                            {!editingUser && (
                                <div>
                                    <label className="block text-xs font-bold text-neutral-500 uppercase tracking-widest mb-1">Password</label>
                                    <input
                                        className="w-full bg-black/40 border border-white/10 p-3 rounded-lg text-white focus:border-brand-500 outline-none"
                                        type="password"
                                        placeholder="••••••••"
                                        value={newUser.password}
                                        onChange={e => setNewUser({ ...newUser, password: e.target.value })}
                                    />
                                </div>
                            )}

                            <div>
                                <label className="block text-xs font-bold text-neutral-500 uppercase tracking-widest mb-1">Role / Profile</label>
                                <select
                                    className="w-full bg-black/40 border border-white/10 p-3 rounded-lg text-white focus:border-brand-500 outline-none appearance-none"
                                    value={activeUser.role}
                                    onChange={e => handleRoleChange(e.target.value)}
                                >
                                    {roles.map(r => (
                                        <option key={r.name} value={r.name}>{r.name}</option>
                                    ))}
                                </select>
                            </div>

                            {/* Granular Permissions Toggle */}
                            <div className="border border-white/10 rounded-xl overflow-hidden">
                                <button
                                    onClick={() => setShowPerms(!showPerms)}
                                    className="w-full flex items-center justify-between p-3 bg-white/5 hover:bg-white/10 text-xs font-bold text-neutral-300 uppercase tracking-wide"
                                >
                                    <span>Specific Permissions ({activeUser.permissions.length})</span>
                                    <span className="material-symbols-outlined text-sm">{showPerms ? 'expand_less' : 'expand_more'}</span>
                                </button>

                                {showPerms && (
                                    <div className="p-3 bg-black/20 max-h-64 overflow-y-auto space-y-4">
                                        {ALL_PERMISSIONS.map(cat => (
                                            <div key={cat.category}>
                                                <h5 className="text-[10px] text-neutral-500 font-bold uppercase mb-2">{cat.category}</h5>
                                                <div className="space-y-1">
                                                    {cat.perms.map(p => (
                                                        <label key={p} className="flex items-center gap-2 cursor-pointer">
                                                            <input
                                                                type="checkbox"
                                                                checked={activeUser.permissions.includes(p)}
                                                                onChange={() => togglePermission(p)}
                                                                className="w-3 h-3 rounded bg-black/40 text-brand-500 border-white/10"
                                                            />
                                                            <span className="text-[10px] text-neutral-400">{p}</span>
                                                        </label>
                                                    ))}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>

                            <div className="pt-4">
                                <button
                                    onClick={handleCreateOrUpdate}
                                    disabled={!activeUser.username || (!editingUser && !newUser.password)}
                                    className={`w-full font-bold py-3.5 rounded-xl transition-all uppercase tracking-widest text-xs flex items-center justify-center gap-2 ${(!activeUser.username) ? 'bg-white/5 text-neutral-500 cursor-not-allowed' : 'bg-brand-600 hover:bg-brand-500 text-white'}`}
                                >
                                    <span className="material-symbols-outlined text-sm">{editingUser ? 'save' : 'person_add'}</span>
                                    {editingUser ? 'Update User' : 'Create User'}
                                </button>
                            </div>
                        </div>
                    </div>

                    {/* Users List */}
                    <div className="lg:col-span-2 glass rounded-2xl border border-white/5 overflow-hidden">
                        <table className="w-full text-left text-sm text-neutral-400">
                            <thead className="bg-white/5 text-xs uppercase font-bold text-neutral-300">
                                <tr>
                                    <th className="p-4">Username</th>
                                    <th className="p-4">Role</th>
                                    <th className="p-4 text-right">Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                {users.map(u => (
                                    <tr key={u.username} className="border-b border-white/5 hover:bg-white/5 transition-colors">
                                        <td className="p-4 font-bold text-white">{u.username}</td>
                                        <td className="p-4">
                                            <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-neutral-700 text-neutral-400">
                                                {u.role}
                                            </span>
                                        </td>
                                        <td className="p-4 text-right flex items-center justify-end gap-2">
                                            <button onClick={() => startEdit(u)} className="text-brand-400 hover:text-white" title="Edit User">
                                                <span className="material-symbols-outlined">edit</span>
                                            </button>
                                            <button onClick={() => handleResetPassword(u.username)} className="text-neutral-500 hover:text-white" title="Reset Password">
                                                <span className="material-symbols-outlined">lock_reset</span>
                                            </button>
                                            <button onClick={() => handleDelete(u.username)} className="text-red-500 hover:text-red-400" title="Delete User">
                                                <span className="material-symbols-outlined">delete</span>
                                            </button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}
        </div>
    );
};

export default UserManager;
