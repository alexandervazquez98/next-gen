import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { api } from '../services/api';

interface User {
    username: string;
    role: string;
    permissions: string[];
    allowed_locations: string[];
    force_password_change?: boolean;
    tier: string;
}

interface AuthContextType {
    user: User | null;
    login: (user: User) => void;
    logout: () => void;
    hasPermission: (perm: string) => boolean;
    isAuthenticated: boolean;
    loading: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [user, setUser] = useState<User | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        // Hydrate user from cookie-authenticated endpoint on mount
        api.get<User>('/auth/users/me')
            .then(userData => setUser(userData))
            .catch(() => {
                setUser(null);
            })
            .finally(() => {
                setLoading(false);
            });
    }, []);

    const login = useCallback((newUser: User) => {
        setUser(newUser);
        setLoading(false);
    }, []);

    const logout = useCallback(async () => {
        try {
            await api.post('/auth/logout', {});
        } catch {
            // Best effort — still clear local state
        } finally {
            setUser(null);
        }
    }, []);

    const hasPermission = (perm: string) => {
        if (!user) return false;
        if (user.role === 'ADMIN') return true;
        return user.permissions.includes(perm);
    };

    return (
        <AuthContext.Provider value={{
            user,
            login,
            logout,
            hasPermission,
            isAuthenticated: !!user,
            loading
        }}>
            {children}
        </AuthContext.Provider>
    );
};

export const useAuth = () => {
    const context = useContext(AuthContext);
    if (!context) throw new Error("useAuth must be used within an AuthProvider");
    return context;
};