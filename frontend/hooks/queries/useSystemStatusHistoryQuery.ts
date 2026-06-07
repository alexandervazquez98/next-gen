import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '../../services/queryKeys';
import { fetchSystemStatusHistory } from '../../services/queryResources';

export const useSystemStatusHistoryQuery = (options: { hours?: number; limit?: number } = {}) => {
  const { hours = 168, limit = 24 } = options;

  return useQuery({
    queryKey: queryKeys.systemStatusHistory({ hours, limit }),
    queryFn: ({ signal }) => fetchSystemStatusHistory({ hours, limit, signal }),
    refetchInterval: 60000,
  });
};
