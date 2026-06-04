import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "../../services/queryKeys";
import { fetchAvailabilitySnmpNoResponse } from "../../services/queryResources";

interface UseAvailabilitySnmpNoResponseQueryOptions {
	enabled?: boolean;
	limit?: number;
	offset?: number;
}

export const useAvailabilitySnmpNoResponseQuery = ({
	enabled = false,
	limit = 25,
	offset = 0,
}: UseAvailabilitySnmpNoResponseQueryOptions = {}) =>
	useQuery({
		queryKey: queryKeys.availabilitySnmpNoResponse({ limit, offset }),
		queryFn: ({ signal }) =>
			fetchAvailabilitySnmpNoResponse({ limit, offset, signal }),
		enabled,
		refetchOnWindowFocus: false,
		staleTime: 30000,
	});
