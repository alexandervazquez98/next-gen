import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '../../services/queryKeys';
import { fetchActiveEvents } from '../../services/queryResources';

export const useActiveEventsQuery = () => useQuery({
  queryKey: queryKeys.activeEvents(),
  queryFn: ({ signal }) => fetchActiveEvents({ signal }),
  refetchInterval: 10000,
});
