import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '../../services/queryKeys';
import { fetchNodes } from '../../services/queryResources';

export const useNodesQuery = () => useQuery({
  queryKey: queryKeys.nodes(),
  queryFn: ({ signal }) => fetchNodes({ signal }),
  refetchInterval: 5000,
});
