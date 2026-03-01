import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { useNavigate } from 'react-router-dom';

const ChangePasswordPage: React.FC = () => {
    const { token, logout, user } = useAuth();
    const navigate = useNavigate();
    const [oldPassword, setOldPassword] = useState('');
    const [newPassword, setNewPassword] = useState('');
    const [confirmPassword, setConfirmPassword] = useState('');
    const [error, setError] = useState('');
    const [success, setSuccess] = useState('');

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        setSuccess('');

        if (newPassword !== confirmPassword) {
            setError("New passwords do not match");
            return;
        }

        try {
            const res = await fetch('/api/auth/change-password', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify({
                    old_password: oldPassword,
                    new_password: newPassword
                })
            });

            const data = await res.json();

            if (!res.ok) {
                throw new Error(data.detail || 'Failed to change password');
            }

            setSuccess('Password changed successfully. Redirecting...');

            // Update local user state if possible, or just force re-login?
            // AuthContext doesn't expose a setUser that updates generic fields easily without re-fetch.
            // But usually we can just navigate home and let the context refresh or just proceed.
            // If we enforced a redirect, we need to clear that flag in the context.
            // Simplest is to reload page or re-fetch user.

            setTimeout(() => {
                window.location.href = '/'; // Force reload to refresh user context
            }, 1000);

        } catch (err: any) {
            setError(err.message);
        }
    };

    return (
        <div className="flex h-screen w-screen items-center justify-center bg-surface-950">
            <div className="w-full max-w-md p-8 glass rounded-2xl border border-white/5 space-y-6">
                <div className="text-center">
                    <h2 className="text-2xl font-black text-white uppercase tracking-tight">Change Password</h2>
                    {user?.force_password_change && (
                        <p className="text-yellow-500 text-sm mt-2">You must change your password to proceed.</p>
                    )}
                </div>

                {error && <div className="p-3 bg-red-500/20 text-red-400 text-sm rounded-lg border border-red-500/20">{error}</div>}
                {success && <div className="p-3 bg-green-500/20 text-green-400 text-sm rounded-lg border border-green-500/20">{success}</div>}

                <form onSubmit={handleSubmit} className="space-y-4">
                    <div>
                        <label className="block text-xs font-bold text-neutral-400 uppercase tracking-widest mb-1">Current Password</label>
                        <input
                            type="password"
                            value={oldPassword}
                            onChange={e => setOldPassword(e.target.value)}
                            className="w-full bg-neutral-900/50 border border-white/10 rounded-lg px-4 py-3 text-white focus:outline-none focus:border-brand-500 transition-colors"
                            required
                        />
                    </div>
                    <div>
                        <label className="block text-xs font-bold text-neutral-400 uppercase tracking-widest mb-1">New Password</label>
                        <input
                            type="password"
                            value={newPassword}
                            onChange={e => setNewPassword(e.target.value)}
                            className="w-full bg-neutral-900/50 border border-white/10 rounded-lg px-4 py-3 text-white focus:outline-none focus:border-brand-500 transition-colors"
                            required
                        />
                    </div>
                    <div>
                        <label className="block text-xs font-bold text-neutral-400 uppercase tracking-widest mb-1">Confirm New Password</label>
                        <input
                            type="password"
                            value={confirmPassword}
                            onChange={e => setConfirmPassword(e.target.value)}
                            className="w-full bg-neutral-900/50 border border-white/10 rounded-lg px-4 py-3 text-white focus:outline-none focus:border-brand-500 transition-colors"
                            required
                        />
                    </div>

                    <button
                        type="submit"
                        className="w-full bg-brand-600 hover:bg-brand-500 text-white font-bold py-3 rounded-xl transition-all shadow-lg shadow-brand-900/20 uppercase tracking-wide"
                    >
                        Update Password
                    </button>

                    {!user?.force_password_change && (
                        <button
                            type="button"
                            onClick={() => navigate('/')}
                            className="w-full text-neutral-500 hover:text-white text-xs font-bold uppercase tracking-widest mt-4"
                        >
                            Cancel
                        </button>
                    )}
                </form>
            </div>
        </div>
    );
};

export default ChangePasswordPage;
