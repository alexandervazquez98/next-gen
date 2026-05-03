import React from 'react';

interface CiRelationships {
  asSource: Array<{ otherId: string; otherLabel: string; type: string }>;
  asTarget: Array<{ otherId: string; otherLabel: string; type: string }>;
}

interface RelationshipBadgeProps {
  ciId: string;
  relationships: Map<string, CiRelationships>;
}

/**
 * RelationshipBadge — renders colored dot badges for a CI's relationship types.
 * - Green dot: CI is a source of DEPENDS_ON relationships
 * - Blue dot: CI is a source of CONNECTED_TO relationships
 * Only renders when the CI has relevant outgoing relationships.
 */
const RelationshipBadge: React.FC<RelationshipBadgeProps> = ({ ciId, relationships }) => {
  const rels = relationships.get(ciId);
  if (!rels || (rels.asSource.length === 0 && rels.asTarget.length === 0)) return null;

  const hasDepends = rels.asSource.some(r => r.type === 'DEPENDS_ON');
  const hasConnected = rels.asSource.some(r => r.type === 'CONNECTED_TO');

  return (
    <span className="flex items-center gap-1 ml-2" aria-label="Has relationships">
      {hasDepends && (
        <span
          className="inline-block w-2 h-2 rounded-full bg-green-500"
          title="DEPENDS_ON"
          aria-label="Has DEPENDS_ON relationships"
        />
      )}
      {hasConnected && (
        <span
          className="inline-block w-2 h-2 rounded-full bg-blue-500"
          title="CONNECTED_TO"
          aria-label="Has CONNECTED_TO relationships"
        />
      )}
    </span>
  );
};

export default RelationshipBadge;