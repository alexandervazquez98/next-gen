export const READ_ONLY_RELATIONSHIP_TYPES = new Set(["RUNS_ON"]);

export const isReadOnlyRelationship = (relationship: string) =>
	READ_ONLY_RELATIONSHIP_TYPES.has(relationship);

export const canDeleteRelationship = (relationship: string) =>
	!isReadOnlyRelationship(relationship);
