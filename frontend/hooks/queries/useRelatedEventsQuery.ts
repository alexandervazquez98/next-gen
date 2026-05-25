import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '../../services/queryKeys';
import { fetchRelatedEvents } from '../../services/queryResources';

export const useRelatedEventsQuery = (ciId: string, enabled = true) => useQuery({
  queryKey: queryKeys.relatedEvents(ciId),
  queryFn: ({ signal }) => fetchRelatedEvents(ciId, { signal }),
  enabled,
  refetchInterval: 10000,
});
