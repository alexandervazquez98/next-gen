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
 * SSE stream marker — set by SSE clients so we know to queue retries
 * instead of forcing logout.
 */
export const SSE_STREAM_HEADER = 'x-sse-stream';

/**
 * Generic fetch wrapper to handle Auth and Errors
 *
 * Auth model: HttpOnly cookie is sent AUTOMATICALLY by the browser via
 * credentials: 'include'. No Authorization: Bearer header needed.
 * 401 retry: the browser re-sends the cookie automatically; we just retry once.
 */
async function request<T>(endpoint: string, config: RequestInit = {}): Promise<T> {
    const url = `${API_BASE}${endpoint.startsWith('/') ? endpoint : '/' + endpoint}`;
    const responseType = (config as RequestInit & { responseType?: string }).responseType;
    const isSSE = !!(config as RequestInit & { isSSE?: boolean }).isSSE;

    // Build headers — start with any caller-provided headers, then apply defaults
    const callerHeaders = config.headers as Record<string, string> || {};
    const headers: Record<string, string> = { ...callerHeaders };

    // Default to JSON if no body or if body is not FormData and no Content-Type set
    if (!(config.body instanceof FormData) && !headers['Content-Type']) {
        headers['Content-Type'] = 'application/json';
    }

    const response = await fetch(url, {
        ...config,
        headers,
        credentials: 'include',
    });

    // Handle 401 Unauthorized — call /auth/refresh to rotate tokens, then retry
    if (response.status === 401) {
        // Step 1: POST to /auth/refresh — browser sends refresh_token cookie automatically
        const refreshResponse = await fetch(`${API_BASE}/auth/refresh`, {
            method: 'POST',
            credentials: 'include', // Required to send the refresh_token cookie
        });

        // If refresh fails, the refresh cookie is expired — force logout
        if (!refreshResponse.ok) {
            if (!isSSE) {
                window.location.href = '/login';
            }
            throw new ApiError('Session expired', 401);
        }

        // Step 2: Refresh succeeded — new access_token cookie is set on the response
        // Retry the original request; browser sends the new access_token cookie automatically
        const retryResponse = await fetch(url, {
            ...config,
            headers,
            credentials: 'include',
        });

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

        // Retry still failed — refresh cookie may have expired during the retry window
        if (!isSSE) {
            window.location.href = '/login';
        }
        throw new ApiError('Unauthorized', 401);
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