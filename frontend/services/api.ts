const API_BASE = '/api';

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
 * Custom error for token expiry (distinct from generic 401)
 */
export class TokenExpiredError extends ApiError {
    constructor() {
        super('Token expired', 401);
    }
}

/**
 * Read access token from document.cookie.
 * Cookie format: access_token=<token>; HttpOnly (inaccessible to JS by spec,
 * but frontend reads it via the Set-Cookie from the server).
 */
const getToken = (): string | null => {
    const match = document.cookie.match(/(?:^|;\s*)access_token=([^;]*)/);
    return match ? match[1] : null;
};

/**
 * SSE stream marker — set by SSE clients so we know to queue retries
 * instead of forcing logout.
 */
export const SSE_STREAM_HEADER = 'x-sse-stream';

/**
 * Global refresh state for coordinating concurrent 401 retries.
 */
let isRefreshing = false;
let refreshPromise: Promise<string | null> | null = null;

/**
 * Attempt to refresh the access token using the refresh token from cookie.
 * Returns the new access token, or null if refresh failed.
 */
const attemptRefresh = async (): Promise<string | null> => {
    // Read refresh token from HTTP-only cookie (set by backend on /auth/refresh)
    const refreshToken = document.cookie.match(/(?:^|;\s*)refresh_token=([^;]*)/)?.[1];
    if (!refreshToken) return null;

    try {
        const res = await fetch(`${API_BASE}/auth/refresh`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_token: refreshToken }),
            credentials: 'include',
        });

        if (!res.ok) return null;

        const data = await res.json();
        return data.access_token ?? null;
    } catch {
        return null;
    }
};

/**
 * Get a new access token, or return existing if refresh fails.
 * Coordinates concurrent requests to avoid redundant refresh calls.
 */
const getNewToken = async (): Promise<string | null> => {
    if (!isRefreshing) {
        isRefreshing = true;
        refreshPromise = attemptRefresh()
            .finally(() => {
                isRefreshing = false;
                refreshPromise = null;
            });
    }
    return refreshPromise;
};

/**
 * Helper to get headers with Auth token from cookie.
 */
const getHeaders = (isJson = true) => {
    const headers: HeadersInit = {};
    const token = getToken();

    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    if (isJson) {
        headers['Content-Type'] = 'application/json';
    }

    return headers;
};

/**
 * Generic fetch wrapper to handle Auth and Errors
 */
async function request<T>(endpoint: string, config: RequestInit = {}): Promise<T> {
    const url = `${API_BASE}${endpoint.startsWith('/') ? endpoint : '/' + endpoint}`;
    const responseType = (config as RequestInit & { responseType?: string }).responseType;
    const isSSE = !!(config as RequestInit & { isSSE?: boolean }).isSSE;

    // Build headers — start with any caller-provided headers, then apply defaults
    const callerHeaders = config.headers as Record<string, string> || {};
    const headers: Record<string, string> = { ...callerHeaders };

    const token = getToken();
    if (token && !headers['Authorization']) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    // Default to JSON if no body or if body is not FormData and no Content-Type set
    if (!(config.body instanceof FormData) && !headers['Content-Type']) {
        headers['Content-Type'] = 'application/json';
    }

    const response = await fetch(url, {
        ...config,
        headers,
    });

    // Handle 401 Unauthorized
    if (response.status === 401) {
        if (isSSE) {
            // SSE: set refreshing flag and queue retry
            const newToken = await getNewToken();
            if (newToken) {
                // Retry with new token
                headers['Authorization'] = `Bearer ${newToken}`;
                const retryResponse = await fetch(url, { ...config, headers });
                if (retryResponse.ok) {
                    if (responseType === 'blob') {
                        return retryResponse.blob() as unknown as T;
                    }
                    const contentType = retryResponse.headers.get("content-type");
                    if (contentType && contentType.indexOf("application/json") !== -1) {
                        return retryResponse.json();
                    }
                    return retryResponse.text() as unknown as T;
                }
            }
            // Refresh failed or returned no token — don't logout for SSE, just let it fail
            throw new TokenExpiredError();
        } else {
            // Non-SSE: attempt single refresh, then retry
            const newToken = await getNewToken();
            if (newToken) {
                // Retry with new token
                headers['Authorization'] = `Bearer ${newToken}`;
                const retryResponse = await fetch(url, { ...config, headers });
                if (retryResponse.ok) {
                    if (responseType === 'blob') {
                        return retryResponse.blob() as unknown as T;
                    }
                    const contentType = retryResponse.headers.get("content-type");
                    if (contentType && contentType.indexOf("application/json") !== -1) {
                        return retryResponse.json();
                    }
                    return retryResponse.text() as unknown as T;
                }
            }
            // Refresh failed — force logout
            window.location.href = '/login';
            throw new ApiError('Unauthorized', 401);
        }
    }

    // Handle other errors
    if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new ApiError(errorData.detail || response.statusText, response.status);
    }

    if (responseType === 'blob') {
        return response.blob() as unknown as T;
    }

    // Return JSON if content exists
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

export const api = {
    get: <T>(endpoint: string, config: RequestInit = {}) => request<T>(endpoint, { ...config, method: 'GET' }),
    post: <T>(endpoint: string, body: any, config: RequestInit = {}) => {
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
    put: <T>(endpoint: string, body: any, config: RequestInit = {}) => request<T>(endpoint, {
        ...config,
        method: 'PUT',
        body: JSON.stringify(body),
    }),
    delete: <T>(endpoint: string, body?: any, config: RequestInit = {}) => request<T>(endpoint, {
        ...config,
        method: 'DELETE',
        body: body ? JSON.stringify(body) : undefined
    }),
    // SSE-aware get that marks the request so 401 triggers queue+wait instead of logout
    getSSE: <T>(endpoint: string, config: RequestInit = {}) =>
        request<T>(endpoint, { ...config, method: 'GET', isSSE: true } as RequestInit),
    // Download a file with authentication (returns blob URL for download)
    download: (endpoint: string) => {
        return request<Blob>(endpoint, { responseType: 'blob', method: 'GET' })
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