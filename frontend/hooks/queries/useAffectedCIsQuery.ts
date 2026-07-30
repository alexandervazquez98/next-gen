import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '../../services/queryKeys';
import { fetchAffectedCIs } from '../../services/queryResources';

/**
 * P2 REQ-004 / REQ-005: drill-down hook for the operator "Total Active"
 * modal. The query is opt-in via `enabled` so the dashboard only fetches
 * affected CIs when the user actually opens the modal.
 */
export const useAffectedCIsQuery = (eventId: string | null | undefined, enabled = true) =>
  useQuery({
    queryKey: eventId ? queryKeys.affectedCIs(eventId) : ['events', 'affected', 'unknown'],
    queryFn: ({ signal }: { signal?: AbortSignal }) =>
      fetchAffectedCIs(eventId as string, { signal }),
    enabled: Boolean(eventId) && enabled,
  });
