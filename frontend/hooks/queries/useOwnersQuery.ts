import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '../../services/queryKeys';
import { api } from '../../services/api';

export const useOwnersQuery = () => useQuery({
  queryKey: ['owners'],
  queryFn: () => api.get<{ name: string }[]>('/owners'),
});
