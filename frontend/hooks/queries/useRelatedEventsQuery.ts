import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '../../services/queryKeys';
import { fetchRelatedEvents } from '../../services/queryResources';

export const useRelatedEventsQuery = (ciId?: string, enabled = true) => useQuery({
  queryKey: ciId ? queryKeys.relatedEvents(ciId) : ['events', 'related', 'unknown'],
  queryFn: ({ signal }) => fetchRelatedEvents(ciId as string, { signal }),
  enabled: Boolean(ciId) && enabled,
  refetchInterval: 10000,
});
