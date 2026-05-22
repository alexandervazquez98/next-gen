import React from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../../services/api';

interface CommentPayload {
  message: string;
  user: string;
}

interface TakePayload {
  user: string;
  tier: string;
}

interface ClosePayload {
  forced: boolean;
  comment_message?: string;
}

interface DiagnosePayload {
  user: string;
}

interface PruneProgress {
  total: number;
  processed: number;
  remaining: number;
  batch: number;
  error?: string;
}

export const useEventMutations = () => {
  const queryClient = useQueryClient();

  const refreshEventQueries = async () => {
    await queryClient.invalidateQueries({ queryKey: ['events'] });
  };

  return {
    ackEvent: async (id: string) => {
      const result = await api.post(`/events/${id}/ack`, {});
      await refreshEventQueries();
      return result;
    },
    commentEvent: async (id: string, payload: CommentPayload) => {
      const result = await api.post(`/events/${id}/comment`, payload);
      await refreshEventQueries();
      return result;
    },
    takeEvent: async (id: string, payload: TakePayload) => {
      const result = await api.post(`/events/${id}/ack`, { comment_message: `[AUDIT][OWNERSHIP] ${payload.user} (${payload.tier})` });
      await refreshEventQueries();
      return result;
    },
    closeEvent: async (id: string, payload: ClosePayload) => {
      const result = await api.post(`/events/${id}/close`, payload);
      await refreshEventQueries();
      return result;
    },
    pruneEvents: async () => {
      const result = await api.post('/events/prune', {});
      await refreshEventQueries();
      return result;
    },
    usePruneRecovered: () => {
      const queryClient = useQueryClient();
      type UsePruneState =
        | { status: 'idle' }
        | { status: 'streaming'; progress: PruneProgress }
        | { status: 'complete'; progress: PruneProgress }
        | { status: 'error'; message: string };

      const [state, setState] = React.useState<UsePruneState>({ status: 'idle' });
      const abortRef = React.useRef<AbortController | null>(null);

      const start = React.useCallback(async () => {
        // Cancel any existing stream
        abortRef.current?.abort();
        const controller = new AbortController();
        abortRef.current = controller;

        setState({ status: 'streaming', progress: { total: 0, processed: 0, remaining: 0, batch: 0 } });

        try {
          const response = await fetch('/api/events/bulk/stream-progress', {
            signal: controller.signal,
            headers: {
              Accept: 'text/event-stream',
            },
            credentials: 'include',
          });

          if (!response.ok) {
            const text = await response.text();
            setState({ status: 'error', message: text || `HTTP ${response.status}` });
            return;
          }

          const reader = response.body?.getReader();
          if (!reader) {
            setState({ status: 'error', message: 'No response body' });
            return;
          }

          const decoder = new TextDecoder();
          let buffer = '';

          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() ?? '';

            for (const line of lines) {
              if (line.startsWith('data: ')) {
                try {
                  const progress: PruneProgress = JSON.parse(line.slice(6));
                  setState({ status: 'streaming', progress });
                } catch {
                  // Skip malformed JSON
                }
              }
            }
          }

          // Stream complete
          setState((prev) =>
            prev.status === 'streaming'
              ? { status: 'complete', progress: prev.progress }
              : prev
          );
          await queryClient.invalidateQueries({ queryKey: ['events'] });
        } catch (err) {
          if (err instanceof Error && err.name === 'AbortError') {
            setState({ status: 'idle' });
          } else {
            setState({ status: 'error', message: err instanceof Error ? err.message : 'Unknown error' });
          }
        }
      }, [queryClient]);

      const cancel = React.useCallback(() => {
        abortRef.current?.abort();
        setState({ status: 'idle' });
      }, []);

      React.useEffect(() => {
        return () => abortRef.current?.abort();
      }, []);

      return {
        state,
        start,
        cancel,
        isIdle: state.status === 'idle',
        isStreaming: state.status === 'streaming',
        isComplete: state.status === 'complete',
        isError: state.status === 'error',
        progress: state.status === 'streaming' || state.status === 'complete' ? state.progress : null,
        errorMessage: state.status === 'error' ? state.message : null,
      };
    },
    diagnoseEvent: async (id: string, _payload: DiagnosePayload) => {
      const result = await api.post(`/events/${id}/diagnose`, {});
      await refreshEventQueries();
      return result;
    },
  };
};
