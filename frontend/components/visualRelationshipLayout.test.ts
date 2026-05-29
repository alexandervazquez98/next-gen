import { describe, expect, it } from 'vitest';
import type { GraphNode } from '../types';
import { buildAnchoredVisualLayout, buildVisualRelationshipLayout, clusterIdForNode } from './visualRelationshipLayout';

const baseNode = (id: string, extra: Partial<GraphNode> = {}): GraphNode => ({
  id,
  label: id,
  type: 'INFRASTRUCTURE',
  status: 'OK',
  metadata: {},
  ...extra,
});

describe('visual relationship layout', () => {
  it('uses location_name as the primary cluster id', () => {
    expect(clusterIdForNode(baseNode('ci-a', { location_name: 'SITE-01', category: 'Network' }))).toBe('SITE-01');
    expect(clusterIdForNode(baseNode('ci-b', { category: 'Network' }))).toBe('Network');
  });

  it('creates one cluster per location and assigns nodes to cluster anchors', () => {
    const layout = buildVisualRelationshipLayout([
      baseNode('a-1', { location_name: 'A', x: 0, y: 0 }),
      baseNode('a-2', { location_name: 'A', x: 0, y: 0 }),
      baseNode('b-1', { location_name: 'B', x: 100, y: 100 }),
    ]);

    expect(layout.clusters.map((cluster) => cluster.id)).toEqual(['A', 'B']);
    expect(layout.clusters.find((cluster) => cluster.id === 'A')?.count).toBe(2);
    expect(layout.nodes.filter((node) => node.clusterId === 'A')).toHaveLength(2);
  });

  it('prefers explicit x/y coordinates over location coordinates', () => {
    const [left, right] = buildAnchoredVisualLayout([
      baseNode('left', { x: 0, y: 0, location: { lat: 1, long: 1 } }),
      baseNode('right', { x: 10, y: 10, location: { lat: 1, long: 1 } }),
    ]);

    expect(left.anchorX).toBeLessThan(right.anchorX);
  });

  it('uses CMDB location projection when explicit coordinates are missing', () => {
    const [east, origin] = buildAnchoredVisualLayout([
      baseNode('origin', { location: { lat: 32.5, long: -117 } }),
      baseNode('east', { location: { lat: 32.5, long: -116.9 } }),
    ]);

    expect(origin.anchorX).toBeGreaterThan(east.anchorX);
    expect(origin.anchorY).toBe(east.anchorY);
  });

  it('separates colocated nodes with deterministic collision forces', () => {
    const colocated = Array.from({ length: 6 }, (_, index) =>
      baseNode(`ci-${index}`, { location_name: 'SITE-A', x: 10, y: 10 }),
    );

    const layout = buildAnchoredVisualLayout(colocated);
    const roundedPositions = new Set(layout.map((node) => `${Math.round(node.mapX)}:${Math.round(node.mapY)}`));

    expect(roundedPositions.size).toBe(colocated.length);
  });

  it('keeps fallback placement stable across input order changes', () => {
    const nodes = [baseNode('b'), baseNode('a'), baseNode('c')];
    const first = buildAnchoredVisualLayout(nodes);
    const second = buildAnchoredVisualLayout([...nodes].reverse());

    expect(first.map((node) => node.id)).toEqual(second.map((node) => node.id));
    expect(first.map((node) => [node.anchorX, node.anchorY])).toEqual(
      second.map((node) => [node.anchorX, node.anchorY]),
    );
  });
});
