import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '../../services/queryKeys';
import { fetchActiveEvents } from '../../services/queryResources';

/**
 * P2 REQ-006 / REQ-008: poll the root-only feed by default. The
 * `include_children` boolean is part of the query key so the polling
 * cache never mixes root-only and raw rows.
 */
export const useActiveEventsQuery = (include_children: boolean = false) =>
  useQuery({
    queryKey: queryKeys.activeEvents({ includeChildren: include_children }),
    queryFn: ({ signal }) =>
      fetchActiveEvents({ include_children, signal }),
    refetchInterval: 10000,
  });
