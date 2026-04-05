import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '../../services/queryKeys';
import { fetchLinks } from '../../services/queryResources';

export const useLinksQuery = () => useQuery({
  queryKey: queryKeys.links(),
  queryFn: ({ signal }) => fetchLinks({ signal }),
  refetchInterval: 10000,
});
