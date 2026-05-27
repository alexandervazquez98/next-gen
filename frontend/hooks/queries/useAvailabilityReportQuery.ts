import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "../../services/queryKeys";
import { fetchAvailabilityReport } from "../../services/queryResources";

export const useAvailabilityReportQuery = () =>
	useQuery({
		queryKey: queryKeys.availabilityReport(),
		queryFn: ({ signal }) => fetchAvailabilityReport({ signal }),
		refetchInterval: 60000,
	});
