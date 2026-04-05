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
    takeEvent: async (id: string, _payload: TakePayload) => {
      const result = await api.post(`/events/${id}/ack`, {});
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
    diagnoseEvent: async (id: string, _payload: DiagnosePayload) => {
      const result = await api.post(`/events/${id}/diagnose`, {});
      await refreshEventQueries();
      return result;
    },
  };
};
