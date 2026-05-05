import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '../../services/queryKeys';
import { fetchSystemStatus } from '../../services/queryResources';

export const useSystemStatusQuery = () => useQuery({
  queryKey: queryKeys.systemStatus(),
  queryFn: ({ signal }) => fetchSystemStatus({ signal }),
  refetchInterval: 3000,
});
