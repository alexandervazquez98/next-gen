// frontend/hooks/useCategories.ts — Feature #480 S4.
//
// Wraps the React-Query categories hook for the Service Catalog
// create/edit form. The ITIL-aligned helper text lives in the form
// component and references docs/itsm/service-catalog.md.

import { useCategoriesQuery } from "./queries/useCategoriesQuery";
import type { CategoryRecord } from "../services/queryResources";

export interface UseCategoriesResult {
  categories: CategoryRecord[];
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  isEmpty: boolean;
}

export const useCategories = (): UseCategoriesResult => {
  const query = useCategoriesQuery();
  const categories = (query.data ?? []) as CategoryRecord[];
  return {
    categories,
    isLoading: query.isLoading,
    isError: Boolean(query.isError),
    error: query.error,
    isEmpty: !query.isLoading && !query.isError && categories.length === 0,
  };
};

export type { CategoryRecord };
