import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '../../services/queryKeys';
import { fetchGraphTopology } from '../../services/queryResources';

export const useGraphTopologyQuery = (filters: { layer?: string; location?: string; owner?: string } = {}) => useQuery({
  queryKey: [...queryKeys.graphTopology(), filters],
  queryFn: ({ signal }) => fetchGraphTopology({ ...filters, signal }),
  refetchInterval: 30000,
});
