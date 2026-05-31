import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "../../services/queryKeys";
import {
	fetchGraphTopology,
	type FetchGraphTopologyOptions,
} from "../../services/queryResources";

export type GraphTopologyFilters = Pick<
	FetchGraphTopologyOptions,
	"layer" | "location" | "owner"
>;

export const useGraphTopologyQuery = (filters: GraphTopologyFilters = {}) =>
	useQuery({
		queryKey: queryKeys.graphTopology(filters),
		queryFn: ({ signal }) => fetchGraphTopology({ ...filters, signal }),
		refetchInterval: 30000,
	});
