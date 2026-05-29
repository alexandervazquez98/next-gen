import { describe, expect, it } from 'vitest';
import type { GraphNode } from '../types';
import { buildAnchoredVisualLayout } from './visualRelationshipLayout';

const baseNode = (id: string, extra: Partial<GraphNode> = {}): GraphNode => ({
  id,
  label: id,
  type: 'INFRASTRUCTURE',
  status: 'OK',
  metadata: {},
  ...extra,
});

describe('visual relationship layout', () => {
  it('prefers explicit x/y coordinates over location coordinates', () => {
    const [left, right] = buildAnchoredVisualLayout([
      baseNode('left', { x: 0, y: 0, location: { lat: 1, long: 1 } }),
      baseNode('right', { x: 10, y: 10, location: { lat: 1, long: 1 } }),
    ]);

    expect(left.anchorX).toBeLessThan(right.anchorX);
    expect(left.anchorY).toBeLessThan(right.anchorY);
  });

  it('uses CMDB location projection when explicit coordinates are missing', () => {
    const [origin, east] = buildAnchoredVisualLayout([
      baseNode('origin', { location: { lat: 32.5, long: -117 } }),
      baseNode('east', { location: { lat: 32.5, long: -116.9 } }),
    ]);

    expect(origin.anchorX).toBeGreaterThan(east.anchorX);
    expect(origin.anchorY).toBe(east.anchorY);
  });

  it('separates colocated nodes with deterministic collision forces', () => {
    const colocated = Array.from({ length: 6 }, (_, index) =>
      baseNode(`ci-${index}`, { x: 10, y: 10 }),
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
