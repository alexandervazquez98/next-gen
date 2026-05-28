/**
 * computeRelationshipMap.unit.test.ts
 *
 * BDD unit tests for computeRelationshipMap utility function.
 * Verifies correct partitioning of links into asSource/asTarget per CI.
 */

import { describe, it, expect } from 'vitest';
import { computeRelationshipMap, LinkData } from '../RelationshipManager';

const makeLinks = (links: LinkData[]) => links;

// Minimal shape — only fields used by computeRelationshipMap
const link = (source: string, target: string, relationship: string): LinkData => ({
  source,
  source_label: `${source}-label`,
  target,
  target_label: `${target}-label`,
  relationship,
});

describe('computeRelationshipMap', () => {
  describe('GIVEN empty link array', () => {
    it('WHEN called THEN returns empty map', () => {
      const result = computeRelationshipMap([]);
      expect(result.size).toBe(0);
    });
  });

  describe('GIVEN a single DEPENDS_ON link', () => {
    it('WHEN called THEN source CI has asSource entry, target CI has asTarget entry', () => {
      const links = [link('A', 'B', 'DEPENDS_ON')];
      const map = computeRelationshipMap(links);

      // A → B: A is source of B (A has B as target), B is target of A (B has A as source)
      const aRels = map.get('A');
      const bRels = map.get('B');

      expect(aRels).toBeDefined();
      expect(aRels!.asSource).toHaveLength(1);
      expect(aRels!.asSource[0].otherId).toBe('B');
      expect(aRels!.asSource[0].type).toBe('DEPENDS_ON');
      expect(aRels!.asTarget).toHaveLength(0);

      expect(bRels).toBeDefined();
      expect(bRels!.asTarget).toHaveLength(1);
      expect(bRels!.asTarget[0].otherId).toBe('A');
      expect(bRels!.asTarget[0].type).toBe('DEPENDS_ON');
      expect(bRels!.asSource).toHaveLength(0);
    });
  });

  describe('GIVEN a single CONNECTS_TO link', () => {
    it('WHEN called THEN correctly partitions asSource/asTarget with CONNECTS_TO type', () => {
      const links = [link('X', 'Y', 'CONNECTS_TO')];
      const map = computeRelationshipMap(links);

      const xRels = map.get('X');
      const yRels = map.get('Y');

      expect(xRels!.asSource).toHaveLength(1);
      expect(xRels!.asSource[0].type).toBe('CONNECTS_TO');
      expect(xRels!.asSource[0].otherId).toBe('Y');
      expect(yRels!.asTarget).toHaveLength(1);
      expect(yRels!.asTarget[0].type).toBe('CONNECTS_TO');
    });
  });

  describe('GIVEN multiple links for same CI', () => {
    it('WHEN called THEN CI has multiple asSource entries', () => {
      const links = [
        link('CI1', 'CI2', 'DEPENDS_ON'),
        link('CI1', 'CI3', 'CONNECTS_TO'),
        link('CI4', 'CI1', 'DEPENDS_ON'),  // CI1 as target
      ];
      const map = computeRelationshipMap(links);

      const ci1Rels = map.get('CI1');
      expect(ci1Rels!.asSource).toHaveLength(2);
      expect(ci1Rels!.asTarget).toHaveLength(1);
    });
  });

  describe('GIVEN HAS_METRIC links', () => {
    it('WHEN called THEN skips HAS_METRIC links entirely', () => {
      const links = [
        link('CI1', 'CI2', 'HAS_METRIC'),
        link('CI1', 'CI3', 'DEPENDS_ON'),
      ];
      const map = computeRelationshipMap(links);

      const ci1Rels = map.get('CI1');
      expect(ci1Rels!.asSource).toHaveLength(1);
      expect(ci1Rels!.asSource[0].type).toBe('DEPENDS_ON');
      expect(map.get('CI2')).toBeUndefined(); // HAS_METRIC skipped, CI2 not in map
    });
  });

  describe('GIVEN CIs with no relationships', () => {
    it('WHEN called THEN isolated CIs are not present in map', () => {
      const links = [link('A', 'B', 'DEPENDS_ON')];
      const map = computeRelationshipMap(links);

      expect(map.has('A')).toBe(true);
      expect(map.has('B')).toBe(true);
      expect(map.has('C')).toBe(false); // Isolated CI
    });
  });
});