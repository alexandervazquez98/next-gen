// frontend/hooks/useDictionaries.ts — Feature #480 S2/S5.
//
// React hook wrapper around `fetchDictionaryValues(...)` for the ITIL
// Service Catalog create/edit form. Exposes three focused hook names so
// call sites read naturally without sprinkling query-key strings.
//
// The backend contract is the root dictionary endpoint:
// `GET /api/dictionaries?key=<key>&active=true` → `[{value, label}]`.

import { useQuery } from "@tanstack/react-query";

import { fetchDictionaryValues, type DictionaryValueRecord } from "../services/queryResources";
import { queryKeys } from "../services/queryKeys";

export interface UseDictionaryValuesOptions {
  active?: boolean;
}

export function useDictionaryValues(
  key: string,
  { active = true }: UseDictionaryValuesOptions = {},
) {
  return useQuery({
    queryKey: queryKeys.dictionaryValues(key, active),
    queryFn: ({ signal }) => fetchDictionaryValues(key, { signal, active }),
    staleTime: 60_000,
  });
}

export function useValueStreams() {
  return useDictionaryValues("value_stream");
}

export function useTiers(): ReturnType<typeof useDictionaryValues> {
  return useDictionaryValues("tier");
}

export function useCriticalities(): ReturnType<typeof useDictionaryValues> {
  return useDictionaryValues("criticality");
}

export type { DictionaryValueRecord };
