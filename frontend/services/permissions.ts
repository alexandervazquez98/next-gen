import { useState, useEffect } from 'react';
import { api } from './api';

export interface PermissionsResponse {
  human: string[];
  ai: string[];
}

export interface UsePermissionsResult extends PermissionsResponse {
  loading: boolean;
  error: string | null;
}

export function usePermissions(): UsePermissionsResult {
  const [human, setHuman] = useState<string[]>([]);
  const [ai, setAi] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.get<PermissionsResponse>('/permissions/')
      .then((data) => {
        if (!cancelled) {
          setHuman(data.human);
          setAi(data.ai);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err?.message ?? 'Failed to load permissions');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  return { human, ai, loading, error };
}
