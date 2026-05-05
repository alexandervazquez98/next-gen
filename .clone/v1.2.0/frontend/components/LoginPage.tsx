import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { useNavigate } from 'react-router-dom';
import { api } from '../services/api';

const LoginPage: React.FC = () => {
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const { login } = useAuth();
    const navigate = useNavigate();

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');

        try {
            const formData = new URLSearchParams();
            formData.append('username', username);
            formData.append('password', password);

            const data: any = await api.request('/auth/token', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: formData
            });

            const token = data.access_token;

            // Temporarily set token for the next request
            localStorage.setItem('token', token);

            // Fetch user details
            const user = await api.get<any>('/auth/users/me');

            login(token, user);
            navigate('/');
        } catch (err: any) {
            setError(err.message || 'Login failed');
            localStorage.removeItem('token');
        }
    };

    return (
        <div className="h-screen w-screen flex items-center justify-center bg-surface-950 bg-[url('https://grainy-gradients.vercel.app/noise.svg')]">
            <div className="glass p-10 rounded-3xl w-full max-w-md border border-white/10 shadow-2xl relative overflow-hidden">
                {/* Decorative Glow */}
                <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-brand-500 via-accent-cyan to-brand-500 animate-pulse"></div>

                <div className="text-center mb-10">
                    <div className="w-16 h-16 bg-brand-600 rounded-2xl flex items-center justify-center text-white neon-glow mx-auto mb-4">
                        <span className="material-symbols-outlined text-4xl">hub</span>
                    </div>
                    <h1 className="text-3xl font-black text-white tracking-tighter uppercase">NEX-GEN</h1>
                    <p className="text-xs text-neutral-400 font-bold uppercase tracking-widest mt-2">Secure Access Gateway</p>
                </div>

                <form onSubmit={handleSubmit} className="space-y-6">
                    <div className="space-y-2">
                        <label className="text-xs font-bold text-neutral-500 uppercase tracking-wider">Username</label>
                        <input
                            type="text"
                            className="input-field w-full bg-black/40 border border-white/10 p-3 rounded-xl text-white focus:border-brand-500 focus:ring-1 focus:border-brand-500 transition-all"
                            value={username}
                            onChange={e => setUsername(e.target.value)}
                            placeholder="admin"
                        />
                    </div>
                    <div className="space-y-2">
                        <label className="text-xs font-bold text-neutral-500 uppercase tracking-wider">Password</label>
                        <input
                            type="password"
                            className="input-field w-full bg-black/40 border border-white/10 p-3 rounded-xl text-white focus:border-brand-500 focus:ring-1 focus:border-brand-500 transition-all"
                            value={password}
                            onChange={e => setPassword(e.target.value)}
                            placeholder="••••••••"
                        />
                    </div>

                    {error && (
                        <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-lg flex items-center gap-3 text-red-400 text-xs font-bold">
                            <span className="material-symbols-outlined text-sm">error</span>
                            {error}
                        </div>
                    )}

                    <button
                        type="submit"
                        className="w-full bg-brand-600 hover:bg-brand-500 text-white font-bold py-4 rounded-xl transition-all shadow-lg shadow-brand-900/20 flex items-center justify-center gap-2 group"
                    >
                        <span>AUTHENTICATE</span>
                        <span className="material-symbols-outlined group-hover:translate-x-1 transition-transform">login</span>
                    </button>
                </form>

                <div className="mt-8 text-center">
                    <p className="text-[10px] text-neutral-600 uppercase tracking-widest">Authorized Personnel Only</p>
                </div>
            </div>
        </div>
    );
};

export default LoginPage;
