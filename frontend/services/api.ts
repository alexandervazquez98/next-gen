import { publishAuthSessionEvent } from './sessionBus';

const API_BASE = '/api';
const MAX_AUTH_RETRY_COUNT = 1;

export type ApiRequestConfig = RequestInit & {
    responseType?: string;
    isSSE?: boolean;
    skipAuthRefresh?: boolean;
    authRetryCount?: number;
};

/**
 * Custom error class for API errors
 */
export class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
        super(message);
        this.status = status;
    }
}

/**
 * SSE stream marker — set by SSE clients so we know to queue retries
 * instead of forcing logout.
 */
export const SSE_STREAM_HEADER = 'x-sse-stream';

let refreshPromise: Promise<void> | null = null;
let redirectedToLogin = false;

function normalizeEndpoint(endpoint: string): string {
    return endpoint.startsWith('/') ? endpoint : '/' + endpoint;
}

function isLoginPage(): boolean {
    if (typeof window === 'undefined') return false;
    return window.location.pathname === '/login' || window.location.hash.startsWith('#/login');
}

function redirectToLoginOnce() {
    if (typeof window === 'undefined' || isLoginPage()) return;

    const alreadyPointingAtLogin = window.location.href.endsWith('/login') || window.location.hash.startsWith('#/login');
    if (redirectedToLogin && alreadyPointingAtLogin) return;

    redirectedToLogin = true;
    if (window.location.hash) {
        window.location.hash = '#/login';
    } else {
        window.location.href = '/login';
    }
}

function base64UrlDecode(value: string): string {
    const normalized = value.replace(/-/g, '+').replace(/_/g, '/');
    const padded = normalized.padEnd(normalized.length + ((4 - normalized.length % 4) % 4), '=');
    return atob(padded);
}

function readCookie(name: string): string | undefined {
    if (typeof document === 'undefined') return undefined;
    const prefix = `${name}=`;
    return document.cookie
        .split(';')
        .map(cookie => cookie.trim())
        .find(cookie => cookie.startsWith(prefix))
        ?.slice(prefix.length);
}

function getCurrentSessionIdFromAccessToken(): string | undefined {
    try {
        const token = readCookie('access_token');
        const payload = token?.split('.')[1];
        if (!payload) return undefined;
        const decoded = JSON.parse(base64UrlDecode(payload));
        return typeof decoded.sid === 'string' ? decoded.sid : undefined;
    } catch {
        return undefined;
    }
}

function publishSessionExpired(reason: string) {
    publishAuthSessionEvent({
        type: 'session-expired',
        reason,
        sessionId: getCurrentSessionIdFromAccessToken(),
    });
}

async function getErrorMessage(response: Response, fallback: string): Promise<string> {
    const errorData = await response.json().catch(() => ({}));
    const detail = errorData.detail;
    if (typeof detail === 'string') return detail;
    return detail?.message || response.statusText || fallback;
}

function shouldSkipAuthRefresh(endpoint: string, config: ApiRequestConfig): boolean {
    const normalizedEndpoint = normalizeEndpoint(endpoint);
    return !!config.skipAuthRefresh || normalizedEndpoint === '/auth/refresh' || normalizedEndpoint === '/auth/logout';
}

async function refreshSession(): Promise<void> {
    if (refreshPromise) return refreshPromise;

    refreshPromise = (async () => {
        const refreshResponse = await fetch(`${API_BASE}/auth/refresh`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
        });

        if (!refreshResponse.ok) {
            const message = await getErrorMessage(refreshResponse, 'Session expired');
            publishSessionExpired(message);
            throw new ApiError(message, refreshResponse.status);
        }
    })().finally(() => {
        refreshPromise = null;
    });

    return refreshPromise;
}

async function parseSuccessfulResponse<T>(response: Response, responseType?: string): Promise<T> {
    if (responseType === 'blob') {
        return response.blob() as unknown as T;
    }

    const contentType = response.headers.get("content-type");
    if (contentType && contentType.indexOf("application/json") !== -1) {
        return response.json();
    }

    // Handle binary data (Excel, etc.)
    if (contentType && (
        contentType.indexOf("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet") !== -1 ||
        contentType.indexOf("application/octet-stream") !== -1
    )) {
        return response.blob() as unknown as T;
    }

    return response.text() as unknown as T;
}

/**
 * Generic fetch wrapper to handle Auth and Errors
 *
 * Auth model: HttpOnly cookie is sent AUTOMATICALLY by the browser via
 * credentials: 'include'. No Authorization: Bearer header needed.
 * 401 retry: the browser re-sends the cookie automatically; we just retry once.
 */
async function request<T>(endpoint: string, config: ApiRequestConfig = {}): Promise<T> {
    const normalizedEndpoint = normalizeEndpoint(endpoint);
    const url = `${API_BASE}${normalizedEndpoint}`;
    const {
        responseType,
        isSSE,
        skipAuthRefresh: _skipAuthRefresh,
        authRetryCount = 0,
        ...fetchConfig
    } = config;
    const skipAuthRefresh = shouldSkipAuthRefresh(endpoint, config);

    // Build headers — start with any caller-provided headers, then apply defaults
    const callerHeaders = fetchConfig.headers as Record<string, string> || {};
    const headers: Record<string, string> = { ...callerHeaders };

    // Default to JSON if no body or if body is not FormData and no Content-Type set
    if (!(fetchConfig.body instanceof FormData) && !headers['Content-Type']) {
        headers['Content-Type'] = 'application/json';
    }

    const response = await fetch(url, {
        ...fetchConfig,
        headers,
        credentials: 'include',
    });

    // Handle 401 Unauthorized — call /auth/refresh to rotate tokens, then retry once.
    if (response.status === 401) {
        if (skipAuthRefresh || authRetryCount >= MAX_AUTH_RETRY_COUNT) {
            const message = await getErrorMessage(response, 'Unauthorized');
            if (!isSSE && !skipAuthRefresh) {
                publishSessionExpired(message);
                redirectToLoginOnce();
            }
            throw new ApiError(message, response.status);
        }

        try {
            await refreshSession();
        } catch (error) {
            if (!isSSE) {
                redirectToLoginOnce();
            }
            throw error;
        }

        return request<T>(endpoint, {
            ...config,
            authRetryCount: authRetryCount + 1,
        });
    }

    // Handle other errors
    if (!response.ok) {
        const message = await getErrorMessage(response, response.statusText);
        throw new ApiError(message, response.status);
    }

    redirectedToLogin = false;
    return parseSuccessfulResponse<T>(response, responseType);
}

export const api = {
    get: <T>(endpoint: string, config: ApiRequestConfig = {}) => request<T>(endpoint, { ...config, method: 'GET' }),
    post: <T>(endpoint: string, body: any, config: ApiRequestConfig = {}) => {
        let serializedBody: any = body;
        if (body instanceof FormData || body instanceof Blob || body instanceof ArrayBuffer) {
            serializedBody = body;
        } else {
            serializedBody = JSON.stringify(body);
        }
        return request<T>(endpoint, {
            ...config,
            method: 'POST',
            body: serializedBody,
        });
    },
    put: <T>(endpoint: string, body: any, config: ApiRequestConfig = {}) => request<T>(endpoint, {
        ...config,
        method: 'PUT',
        body: JSON.stringify(body),
    }),
    delete: <T>(endpoint: string, body?: any, config: ApiRequestConfig = {}) => request<T>(endpoint, {
        ...config,
        method: 'DELETE',
        body: body ? JSON.stringify(body) : undefined
    }),
    // SSE-aware get that marks the request so 401 surfaces terminal errors without forcing logout.
    getSSE: <T>(endpoint: string, config: ApiRequestConfig = {}) =>
        request<T>(endpoint, { ...config, method: 'GET', isSSE: true }),
    // Download a file with authentication (returns blob URL for download)
    download: (endpoint: string) => {
        return request<Blob>(endpoint, { responseType: 'blob', method: 'GET', credentials: 'include' })
            .then(blob => {
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'template.xlsx';
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                // Revoke after a tick so browser finishes reading
                setTimeout(() => URL.revokeObjectURL(url), 0);
            })
            .catch(err => {
                console.error('Download failed:', err);
                throw err;
            });
    },
    // raw request for custom config
    request
};
