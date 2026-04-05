import { useQueryClient } from '@tanstack/react-query';
import { api } from '../../services/api';
import { queryKeys } from '../../services/queryKeys';

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
}

interface DiagnosePayload {
  user: string;
}

export const useEventMutations = () => {
  const queryClient = useQueryClient();

  const refreshActiveEvents = async () => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.activeEvents() });
  };

  return {
    ackEvent: async (id: string) => {
      const result = await api.post(`/events/${id}/ack`, {});
      await refreshActiveEvents();
      return result;
    },
    commentEvent: async (id: string, payload: CommentPayload) => {
      const result = await api.post(`/events/${id}/comment`, payload);
      await refreshActiveEvents();
      return result;
    },
    takeEvent: async (id: string, payload: TakePayload) => {
      await api.post(`/events/${id}/comment`, {
        message: `[OWNERSHIP] Caso tomado por ${payload.user} - Tier ${payload.tier}`,
        user: payload.user,
      });
      const result = await api.post(`/events/${id}/ack`, {});
      await refreshActiveEvents();
      return result;
    },
    closeEvent: async (id: string, payload: ClosePayload) => {
      const result = await api.post(`/events/${id}/close`, payload);
      await refreshActiveEvents();
      return result;
    },
    pruneEvents: async () => {
      const result = await api.post('/events/prune', {});
      await refreshActiveEvents();
      return result;
    },
    diagnoseEvent: async (id: string, _payload: DiagnosePayload) => {
      const result = await api.post(`/events/${id}/diagnose`, {});
      await refreshActiveEvents();
      return result;
    },
  };
};
