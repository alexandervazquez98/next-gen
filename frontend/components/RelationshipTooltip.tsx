import React, { useState, useRef, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';

interface CiRelationships {
  asSource: Array<{ otherId: string; otherLabel: string; type: string }>;
  asTarget: Array<{ otherId: string; otherLabel: string; type: string }>;
}

interface RelationshipTooltipProps {
  ciId: string;
  relationships: Map<string, CiRelationships>;
  children: React.ReactNode;
}

/**
 * RelationshipTooltip — floating hover card showing CI relationship topology.
 * Composed around the CI name wrapper; shows "Is source of" and "Is target of"
 * sections with relationship types and partner labels.
 * Uses CSS transform with viewport boundary clamping to stay in viewport.
 */
const RelationshipTooltip: React.FC<RelationshipTooltipProps> = ({ ciId, relationships, children }) => {
  const [visible, setVisible] = useState(false);
  const [pos, setPos] = useState({ x: 0, y: 0, flipped: false });
  const triggerRef = useRef<HTMLSpanElement>(null);
  const portalContainerRef = useRef<HTMLDivElement | null>(null);
  const tooltipId = `tooltip-${ciId.replace(/[^a-zA-Z0-9]/g, '')}`;

  const rels = relationships.get(ciId);

  // Early return AFTER all hooks — never before
  if (!rels || (rels.asSource.length === 0 && rels.asTarget.length === 0)) {
    return <>{children}</>;
  }

  // Portal DOM leak fix: manage portal via ref with useEffect cleanup
  // When visible becomes true, create the portal container; when false or unmount, remove it
  useEffect(() => {
    if (visible) {
      const container = document.createElement('div');
      container.id = tooltipId;
      container.setAttribute('role', 'tooltip');
      document.body.appendChild(container);
      portalContainerRef.current = container;
    }
    return () => {
      if (portalContainerRef.current) {
        portalContainerRef.current.remove();
        portalContainerRef.current = null;
      }
    };
  }, [visible, tooltipId]);

  const handleEnter = () => {
    if (triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      const viewportWidth = window.innerWidth;
      const flipped = rect.right + 320 > viewportWidth;
      setPos({ x: rect.left + rect.width / 2, y: rect.top - 10, flipped });
      setVisible(true);
    }
  };

  const handleLeave = () => setVisible(false);

  // Memoize renderRelationList to avoid recreation on every render
  const renderRelationList = useCallback((
    items: Array<{ otherId: string; otherLabel: string; type: string }>,
    emptyLabel: string
  ) => {
    if (items.length === 0) return <span className="text-neutral-600 italic">{emptyLabel}</span>;
    return (
      <ul className="space-y-1">
        {items.map((item, i) => (
          <li key={i} className="flex items-start gap-1">
            <span
              className={`inline-block text-[9px] font-bold px-1.5 py-0.5 rounded uppercase shrink-0 mt-0.5 ${
                item.type === 'DEPENDS_ON'
                  ? 'bg-green-500/20 text-green-400'
                  : item.type === 'CONNECTED_TO'
                  ? 'bg-blue-500/20 text-blue-400'
                  : 'bg-white/10 text-neutral-400'
              }`}
            >
              {item.type}
            </span>
            <span className="text-[11px] text-neutral-300 font-mono truncate" title={item.otherId}>
              {item.otherLabel}
            </span>
          </li>
        ))}
      </ul>
    );
  }, []);

  // Early return AFTER all hooks
  if (!rels || (rels.asSource.length === 0 && rels.asTarget.length === 0)) {
    return <>{children}</>;
  }

  return (
    <>
      <span
        ref={triggerRef}
        onMouseEnter={handleEnter}
        onMouseLeave={handleLeave}
        className="inline"
      >
        {children}
      </span>
      {visible && portalContainerRef.current && createPortal(
        <div
          id={tooltipId}
          role="tooltip"
          className="fixed z-[99999] bg-neutral-900 border border-white/10 rounded-xl shadow-2xl pointer-events-none w-72 p-3 space-y-3"
          style={{
            left: pos.x,
            top: pos.y,
            transform: pos.flipped ? 'translate(-100%, -100%)' : 'translate(-50%, -100%)',
          }}
        >
          {/* Header */}
          <div className="text-xs font-bold text-white uppercase tracking-wider border-b border-white/10 pb-2">
            <span className="text-neutral-400">Relationship Topology</span>
          </div>

          {/* Is source of */}
          <div className="space-y-1">
            <div className="text-[10px] text-brand-400 font-bold uppercase tracking-widest">
              Is source of
            </div>
            {renderRelationList(rels.asSource, 'No outgoing relationships')}
          </div>

          {/* Is target of */}
          <div className="space-y-1">
            <div className="text-[10px] text-accent-cyan font-bold uppercase tracking-widest">
              Is target of
            </div>
            {renderRelationList(rels.asTarget, 'No incoming relationships')}
          </div>

          {/* Tail */}
          <div
            className={`absolute top-full border-4 border-transparent ${
              pos.flipped
                ? 'right-full mr-[-2px] border-r-neutral-900'
                : 'left-1/2 -translate-x-1/2 border-t-neutral-900'
            }`}
          />
        </div>,
        portalContainerRef.current
      )}
    </>
  );
};

export default RelationshipTooltip;