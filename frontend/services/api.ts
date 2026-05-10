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
 * Helper to get headers with Auth token
 */
const getHeaders = (isJson = true) => {
    const headers: HeadersInit = {};
    const token = localStorage.getItem('token');

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

    // Build headers — start with any caller-provided headers, then apply defaults
    const callerHeaders = config.headers as Record<string, string> || {};
    const headers: Record<string, string> = { ...callerHeaders };

    const token = localStorage.getItem('token');
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
        localStorage.removeItem('token');
        window.location.href = '/login'; // Simple redirect, or use EventBus to notify App
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
    // raw request for custom config
    request
};
