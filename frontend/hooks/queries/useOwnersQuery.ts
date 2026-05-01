import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '../../services/queryKeys';
import { fetchOwners } from '../../services/queryResources';

export const useOwnersQuery = () => useQuery({
  queryKey: queryKeys.owners(),
  queryFn: ({ signal }) => fetchOwners({ signal }),
  staleTime: 10000,
});