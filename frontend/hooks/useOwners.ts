// frontend/hooks/useOwners.ts — Feature #480 S3.
//
// Wraps the React-Query owners hook with an empty-state-aware surface
// for the Service Catalog create/edit form.

import { useOwnersQuery } from "./queries/useOwnersQuery";
import type { OwnerRecord } from "../services/queryResources";

export interface UseOwnersResult {
  owners: OwnerRecord[];
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  isEmpty: boolean;
}

export const useOwners = (): UseOwnersResult => {
  const query = useOwnersQuery();
  const owners = (query.data ?? []) as OwnerRecord[];
  return {
    owners,
    isLoading: query.isLoading,
    isError: Boolean(query.isError),
    error: query.error,
    isEmpty: !query.isLoading && !query.isError && owners.length === 0,
  };
};

export type { OwnerRecord };
