import { useMemo } from "react";
import { useActiveEventsQuery } from "./useActiveEventsQuery";
import { useAvailabilityReportQuery } from "./useAvailabilityReportQuery";
import { useCategoriesQuery } from "./useCategoriesQuery";
import { useLinksQuery } from "./useLinksQuery";
import { useNodesQuery } from "./useNodesQuery";

export const useMonitoringConsoleData = () => {
	const nodesQuery = useNodesQuery();
	const linksQuery = useLinksQuery();
	const eventsQuery = useActiveEventsQuery();
	const availabilityReportQuery = useAvailabilityReportQuery();
	const categoriesQuery = useCategoriesQuery();

	const nodes = nodesQuery.data ?? [];
	const categoryNames = useMemo(
		() =>
			(categoriesQuery.data ?? [])
				.map((category) => category.name)
				.filter(Boolean),
		[categoriesQuery.data],
	);
	const fallbackNames = useMemo(
		() =>
			Array.from(
				new Set(
					nodes.map((node) => node.category ?? node.type).filter(Boolean),
				),
			).sort(),
		[nodes],
	);

	const categories = useMemo(() => {
		const source = categoryNames.length > 0 ? categoryNames : fallbackNames;
		return Array.from(new Set(source)).sort();
	}, [categoryNames, fallbackNames]);

	return {
		nodes,
		links: linksQuery.data ?? [],
		events: eventsQuery.data ?? [],
		availabilityReport: availabilityReportQuery.data ?? null,
		availabilityReportIsLoading: availabilityReportQuery.isLoading,
		availabilityReportError: availabilityReportQuery.error ?? null,
		categories,
		isLoading:
			nodesQuery.isLoading ||
			linksQuery.isLoading ||
			eventsQuery.isLoading ||
			categoriesQuery.isLoading,
		error:
			nodesQuery.error ??
			linksQuery.error ??
			eventsQuery.error ??
			categoriesQuery.error ??
			null,
	};
};
