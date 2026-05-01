import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '../../services/queryKeys';
import { fetchEventDetail } from '../../services/queryResources';

export const useEventDetailQuery = (eventId?: string | null, enabled = true) => useQuery({
  queryKey: eventId ? queryKeys.eventDetail(eventId) : ['events', 'detail', 'unknown'],
  queryFn: ({ signal }: { signal?: AbortSignal }) => fetchEventDetail(eventId as string, { signal }),
  enabled: Boolean(eventId) && enabled,
});
