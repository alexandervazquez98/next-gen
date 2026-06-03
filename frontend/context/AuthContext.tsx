import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { api, type ApiRequestConfig } from '../services/api';
import { publishAuthSessionEvent, subscribeAuthSessionEvents } from '../services/sessionBus';

export interface SessionPolicy {
    profile: string;
    idle_timeout_minutes: number | null;
    persistent: boolean;
}

export interface User {
    username: string;
    role: string;
    permissions: string[];
    allowed_locations: string[];
    force_password_change?: boolean;
    tier: string;
    session_id?: string | null;
    session_policy?: SessionPolicy | null;
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

const ACTIVITY_EVENTS: Array<keyof WindowEventMap> = ['click', 'keydown', 'mousemove', 'focus', 'visibilitychange'];
let redirectedToLogin = false;

function redirectToLoginOnce() {
    if (typeof window === 'undefined') return;

    const isLoginPage = window.location.pathname === '/login' || window.location.hash.startsWith('#/login');
    if (isLoginPage) return;

    const alreadyPointingAtLogin = window.location.href.endsWith('/login') || window.location.hash.startsWith('#/login');
    if (redirectedToLogin && alreadyPointingAtLogin) return;

    redirectedToLogin = true;
    if (window.location.hash) {
        window.location.hash = '#/login';
    } else {
        window.location.href = '/login';
    }
}

function shouldArmInactivityTimer(user: User | null): user is User & { session_policy: SessionPolicy } {
    if (!user?.session_policy) return false;
    return !user.session_policy.persistent && !!user.session_policy.idle_timeout_minutes && user.session_policy.idle_timeout_minutes > 0;
}

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [user, setUser] = useState<User | null>(null);
    const [loading, setLoading] = useState(true);
    const inactivityTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const clearInactivityTimer = useCallback(() => {
        if (inactivityTimerRef.current) {
            clearTimeout(inactivityTimerRef.current);
            inactivityTimerRef.current = null;
        }
    }, []);

    const endLocalSession = useCallback((reason: string, broadcastType?: 'logout' | 'session-expired', sessionId?: string | null) => {
        clearInactivityTimer();
        setUser(null);
        setLoading(false);

        if (broadcastType) {
            publishAuthSessionEvent({ type: broadcastType, reason, sessionId: sessionId ?? undefined });
        }

        if (broadcastType === 'session-expired') {
            redirectToLoginOnce();
        }
    }, [clearInactivityTimer]);

    useEffect(() => {
        // Hydrate user from cookie-authenticated endpoint on mount
        api.get<User>('/auth/users/me')
            .then(userData => {
                setUser(userData);
                redirectedToLogin = false;
            })
            .catch(() => {
                setUser(null);
            })
            .finally(() => {
                setLoading(false);
            });
    }, []);

    useEffect(() => {
        const currentSessionId = user?.session_id ?? undefined;
        return subscribeAuthSessionEvents(event => {
            if (event.sessionId && currentSessionId && event.sessionId !== currentSessionId) {
                return;
            }

            if (event.type === 'logout' || event.type === 'session-expired') {
                endLocalSession(event.reason ?? event.type);
            }
        });
    }, [endLocalSession, user?.session_id]);

    useEffect(() => {
        clearInactivityTimer();

        if (!shouldArmInactivityTimer(user)) {
            return undefined;
        }

        const timeoutMs = user.session_policy.idle_timeout_minutes * 60 * 1000;
        let disposed = false;

        const expireForInactivity = async () => {
            if (disposed) return;

            try {
                await api.post('/auth/logout', {}, { skipAuthRefresh: true } as ApiRequestConfig);
            } catch {
                // Best effort — backend remains the security authority.
            } finally {
                if (!disposed) {
                    endLocalSession('idle_timeout', 'session-expired', user.session_id);
                }
            }
        };

        const resetTimer = () => {
            if (inactivityTimerRef.current) {
                clearTimeout(inactivityTimerRef.current);
            }
            inactivityTimerRef.current = setTimeout(expireForInactivity, timeoutMs);
        };

        ACTIVITY_EVENTS.forEach(eventName => window.addEventListener(eventName, resetTimer, { passive: true }));
        resetTimer();

        return () => {
            disposed = true;
            clearInactivityTimer();
            ACTIVITY_EVENTS.forEach(eventName => window.removeEventListener(eventName, resetTimer));
        };
    }, [clearInactivityTimer, endLocalSession, user]);

    const login = useCallback((newUser: User) => {
        redirectedToLogin = false;
        setUser(newUser);
        setLoading(false);
    }, []);

    const logout = useCallback(async () => {
        const sessionId = user?.session_id;
        try {
            await api.post('/auth/logout', {});
        } catch {
            // Best effort — still clear local state
        } finally {
            endLocalSession('manual', 'logout', sessionId);
        }
    }, [endLocalSession, user?.session_id]);

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
