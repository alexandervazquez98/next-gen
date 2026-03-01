import { useNavigate } from 'react-router-dom';

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

    const headers = {
        ...getHeaders(config.headers ? false : true), // Default to JSON unless overridden
        ...config.headers,
    };

    const response = await fetch(url, {
        ...config,
        headers,
    });

    // Handle 404
    if (response.status === 404) {
        return null as any;
    }

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

    // Return JSON if content exists
    const contentType = response.headers.get("content-type");
    if (contentType && contentType.indexOf("application/json") !== -1) {
        return response.json();
    }

    return response.text() as unknown as T;
}

export const api = {
    get: <T>(endpoint: string) => request<T>(endpoint, { method: 'GET' }),
    post: <T>(endpoint: string, body: any) => request<T>(endpoint, { method: 'POST', body: JSON.stringify(body) }),
    put: <T>(endpoint: string, body: any) => request<T>(endpoint, { method: 'PUT', body: JSON.stringify(body) }),
    delete: <T>(endpoint: string, body?: any) => request<T>(endpoint, {
        method: 'DELETE',
        body: body ? JSON.stringify(body) : undefined
    }),
    // raw request for custom config
    request
};
