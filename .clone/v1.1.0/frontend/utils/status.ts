/**
 * Utility functions for status color mapping.
 * Used across GraphCMDB, MonitoringConsole, and GlobalInventory.
 */

// Hex Colors for D3 / Canvas / Leaflet / Charts
export const STATUS_COLORS = {
    CRITICAL: '#ef4444', // red-500
    WARNING: '#f59e0b',  // amber-500
    OK: '#10b981',       // emerald-500
    ACTIVE: '#10b981',   // emerald-500
    UNKNOWN: '#4b5563',  // gray-600
    DEFAULT: '#4b5563'
};

/**
 * Returns the hex color for a given status.
 * Useful for canvas-based rendering (D3, Leaflet, Recharts).
 */
export const getStatusColorHex = (status?: string | null): string => {
    if (!status) return STATUS_COLORS.UNKNOWN;
    const s = status.toUpperCase();
    if (s === 'CRITICAL') return STATUS_COLORS.CRITICAL;
    if (s === 'WARNING') return STATUS_COLORS.WARNING;
    if (s === 'OK' || s === 'ACTIVE') return STATUS_COLORS.OK;
    return STATUS_COLORS.UNKNOWN;
};

/**
 * Returns Tailwind CSS classes for a given status.
 * Usage: `className={\`... ${getStatusClasses(status)}\`}`
 * Includes text color, background tint, and border tint.
 */
export const getStatusClasses = (status?: string | null): string => {
    if (!status) return 'text-neutral-500 bg-neutral-500/10 border-neutral-500/20';
    const s = status.toUpperCase();
    if (s === 'CRITICAL') return 'text-red-500 bg-red-500/10 border-red-500/20';
    if (s === 'WARNING') return 'text-yellow-500 bg-yellow-500/10 border-yellow-500/20';
    if (s === 'OK' || s === 'ACTIVE') return 'text-emerald-500 bg-emerald-500/10 border-emerald-500/20';
    return 'text-neutral-500 bg-neutral-500/10 border-neutral-500/20';
};
