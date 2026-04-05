import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '../../services/queryKeys';
import { fetchCategories } from '../../services/queryResources';

export const useCategoriesQuery = () => useQuery({
  queryKey: queryKeys.categories(),
  queryFn: ({ signal }) => fetchCategories({ signal }),
  refetchInterval: 5000,
  staleTime: 5000,
});
