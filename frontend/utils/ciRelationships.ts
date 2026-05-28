export interface CiRelationshipEntry {
	otherId: string;
	otherLabel: string;
	type: string;
}

export interface CiRelationshipSummary {
	asSource: CiRelationshipEntry[];
	asTarget: CiRelationshipEntry[];
}

export type CiRelationshipState = "none" | "incoming" | "outgoing" | "both";

export interface CiRelationshipDetail {
	direction: "OUTGOING" | "INCOMING";
	type: string;
	otherId: string;
	otherLabel: string;
}

export const getCiRelationshipState = (
	summary?: CiRelationshipSummary,
): CiRelationshipState => {
	const hasOutgoing = Boolean(summary?.asSource?.length);
	const hasIncoming = Boolean(summary?.asTarget?.length);
	if (hasIncoming && hasOutgoing) return "both";
	if (hasIncoming) return "incoming";
	if (hasOutgoing) return "outgoing";
	return "none";
};

export const getCiRelationshipStateLabel = (
	state: CiRelationshipState,
): string => {
	if (state === "both") return "Incoming + outgoing";
	if (state === "incoming") return "Incoming";
	if (state === "outgoing") return "Outgoing";
	return "No correlations";
};

export const getCiRelationshipDetails = (
	summary?: CiRelationshipSummary,
): CiRelationshipDetail[] => [
	...(summary?.asSource ?? []).map((entry) => ({
		direction: "OUTGOING" as const,
		type: entry.type,
		otherId: entry.otherId,
		otherLabel: entry.otherLabel,
	})),
	...(summary?.asTarget ?? []).map((entry) => ({
		direction: "INCOMING" as const,
		type: entry.type,
		otherId: entry.otherId,
		otherLabel: entry.otherLabel,
	})),
];

export const formatCiRelationshipDetails = (
	summary?: CiRelationshipSummary,
): string => {
	const details = getCiRelationshipDetails(summary);
	if (!details.length) return "No CI correlations";
	return details
		.map(
			(detail) =>
				`${detail.direction}: ${detail.type} ${detail.otherLabel} (${detail.otherId})`,
		)
		.join("\n");
};
