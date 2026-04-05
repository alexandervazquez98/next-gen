import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '../../services/queryKeys';
import { fetchGraphTopology } from '../../services/queryResources';

export const useGraphTopologyQuery = () => useQuery({
  queryKey: queryKeys.graphTopology(),
  queryFn: ({ signal }) => fetchGraphTopology({ signal }),
  refetchInterval: 30000,
});
