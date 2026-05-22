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
    token: string | null;
    login: (accessToken: string, refreshToken: string, user: User) => void;
    logout: () => void;
    hasPermission: (perm: string) => boolean;
    isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

/**
 * Read access token from document.cookie.
 */
const getCookieToken = (): string | null => {
    const match = document.cookie.match(/(?:^|;\s*)access_token=([^;]*)/);
    return match ? match[1] : null;
};

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [user, setUser] = useState<User | null>(null);
    const [token, setToken] = useState<string | null>(null);

    useEffect(() => {
        // Hydrate from cookie on mount
        const cookieToken = getCookieToken();
        if (cookieToken) {
            setToken(cookieToken);
            api.get<User>('/auth/users/me')
                .then(userData => setUser(userData))
                .catch(() => {
                    setToken(null);
                    setUser(null);
                });
        }
    }, []);

    const login = useCallback((accessToken: string, refreshToken: string, newUser: User) => {
        // Refresh token is now set by the backend via HTTP-only cookie on /auth/refresh
        // No need to store it in localStorage
        setToken(accessToken);
        setUser(newUser);
    }, []);

    const logout = useCallback(async () => {
        try {
            await api.post('/auth/logout', {});
        } catch {
            // Best effort — still clear local state
        } finally {
            setToken(null);
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
            token,
            login,
            logout,
            hasPermission,
            isAuthenticated: !!user
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