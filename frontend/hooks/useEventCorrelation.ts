import { useMemo } from 'react';
import { Event } from '../types';

export type GroupedEvent = Event & {
    relatedEvents: GroupedEvent[];
    isRoot: boolean;
    cause?: string;
};

/**
 * useEventCorrelation Hook
 * 
 * Analyzes the stream of events and the topology links to group related events.
 * 
 * Logic:
 * 1. Same-Host Correlation: If "Host Unreachable", all other events on that host are children.
 * 2. Topology Correlation: If a Provider CI has a Critical event, downstream Consumer CI events are children.
 * 
 * @param events - List of active events
 * @param links - List of topology relationships
 * @returns Sorted list of Root Cause events with nested children.
 */
export const useEventCorrelation = (events: Event[], links: any[]) => {

const groupedEvents = useMemo(() => {
        const eventMap = new Map<string, GroupedEvent>();
        
        // 1. Initialize Map
        events.forEach(e => {
            eventMap.set(e.id, { ...e, relatedEvents: [], isRoot: true });
        });

        // Helper to check severity weight
        const getSeverityWeight = (s: string) => {
            if (s === 'CRITICAL') return 3;
            if (s === 'WARNING') return 2;
            return 1;
        };

        // 2. Intra-CI Correlation (Same-Host Grouping)
        // Group events occurring on the same CI. Pick a "Dominant" event as root.
        const eventsByCi = new Map<string, GroupedEvent[]>();
        
        events.forEach(e => {
            const list = eventsByCi.get(e.ci_id) || [];
            list.push(eventMap.get(e.id)!);
            eventsByCi.set(e.ci_id, list);
        });

        eventsByCi.forEach((ciEvents) => {
            if (ciEvents.length <= 1) return;

            // Sort events to find the "Dominant" one
            // Priority: Has "Unreachable" -> Highest Severity -> Earliest Time
            ciEvents.sort((a, b) => {
                const aUnreachable = a.message.includes("Unreachable") || a.message.includes("Down");
                const bUnreachable = b.message.includes("Unreachable") || b.message.includes("Down");
                
                if (aUnreachable && !bUnreachable) return -1;
                if (!aUnreachable && bUnreachable) return 1;

                const weightA = getSeverityWeight(a.severity);
                const weightB = getSeverityWeight(b.severity);
                
                if (weightA !== weightB) return weightB - weightA; // Higher severity first

                return new Date(a.created_at).getTime() - new Date(b.created_at).getTime(); // Oldest first
            });

            const dominant = ciEvents[0];
            const secondary = ciEvents.slice(1);

            secondary.forEach(child => {
                if (child.id === dominant.id) return;
                
                // If child is already nested (shouldn't happen in this phase but good for safety), skip
                if (!child.isRoot) return;

                dominant.relatedEvents.push(child);
                child.isRoot = false;
                child.cause = "SAME_HOST_SECONDARY_FAILURE";
            });
        });

        // 3. Topology Correlation (Dependency-Based)
        // If Provider CI has a Dominant Event, Consumer CI's Dominant Events become children
        links.forEach(link => {
            // If Source (Consumer) depends on Target (Provider)
            // P2 REQ-007: include CONNECTS_TO so network-link topology can
            // also suppress consumer ROOT events. The backend
            // `correlation_type` remains the authoritative "is root"
            // signal; this client-side hook is a safety-net.
            if (
                link.relationship === 'DEPENDS_ON' ||
                link.relationship === 'HOSTED_ON' ||
                link.relationship === 'CONNECTS_TO'
            ) {
                const providerId = link.target;
                const consumerId = link.source;

                // Find roots for provider and consumer
                // We filter by isRoot because non-root events are already grouped
                const providerRoots = Array.from(eventMap.values())
                    .filter(e => e.ci_id === providerId && e.isRoot && getSeverityWeight(e.severity) >= 2); // Critical or Warning Provider

                const consumerRoots = Array.from(eventMap.values())
                    .filter(e => e.ci_id === consumerId && e.isRoot);

                providerRoots.forEach(pEvt => {
                    consumerRoots.forEach(cEvt => {
                        // Avoid circular dependency logic
                        if (pEvt.id === cEvt.id) return;

                        pEvt.relatedEvents.push(cEvt);
                        cEvt.isRoot = false;
                        cEvt.cause = "UPSTREAM_DEPENDENCY_FAILURE";
                    });
                });
            }
        });

        return Array.from(eventMap.values())
            .filter(e => e.isRoot)
            .sort((a, b) => {
                // Sort Critical first, then by date
                if (a.severity === 'CRITICAL' && b.severity !== 'CRITICAL') return -1;
                if (a.severity !== 'CRITICAL' && b.severity === 'CRITICAL') return 1;
                return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
            });

    }, [events, links]);

    return groupedEvents;
};
