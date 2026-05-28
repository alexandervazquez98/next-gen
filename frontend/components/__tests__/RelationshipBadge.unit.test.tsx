/**
 * RelationshipBadge.unit.test.tsx
 *
 * BDD unit tests for RelationshipBadge component.
 * Tests badge rendering for DEPENDS_ON (green) and CONNECTS_TO (blue) relationship types.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import RelationshipBadge from '../RelationshipBadge';

const emptyMap = new Map();

const singleDependSourceMap = new Map([
  ['CI-A', { asSource: [{ otherId: 'CI-B', otherLabel: 'CI-B', type: 'DEPENDS_ON' }], asTarget: [] }],
]);

const singleConnectedSourceMap = new Map([
  ['CI-A', { asSource: [{ otherId: 'CI-C', otherLabel: 'CI-C', type: 'CONNECTS_TO' }], asTarget: [] }],
]);

const multiTypeMap = new Map([
  ['CI-A', {
    asSource: [
      { otherId: 'CI-B', otherLabel: 'CI-B', type: 'DEPENDS_ON' },
      { otherId: 'CI-C', otherLabel: 'CI-C', type: 'CONNECTS_TO' },
    ],
    asTarget: [
      { otherId: 'CI-D', otherLabel: 'CI-D', type: 'DEPENDS_ON' },
    ],
  }],
]);

beforeEach(() => {
  vi.stubGlobal('window', { innerWidth: 1920, innerHeight: 1080 });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('RelationshipBadge', () => {
  describe('GIVEN a CI with DEPENDS_ON relationships', () => {
    it('WHEN rendered THEN a green badge dot is displayed', () => {
      render(<RelationshipBadge ciId="CI-A" relationships={singleDependSourceMap} />);
      const dots = document.querySelectorAll('.bg-green-500');
      expect(dots.length).toBe(1);
    });

    it('WHEN rendered THEN badge has correct title attribute', () => {
      render(<RelationshipBadge ciId="CI-A" relationships={singleDependSourceMap} />);
      const dot = document.querySelector('[title="DEPENDS_ON"]');
      expect(dot).not.toBeNull();
    });
  });

  describe('GIVEN a CI with CONNECTS_TO relationships', () => {
    it('WHEN rendered THEN a blue badge dot is displayed', () => {
      render(<RelationshipBadge ciId="CI-A" relationships={singleConnectedSourceMap} />);
      const dots = document.querySelectorAll('.bg-blue-500');
      expect(dots.length).toBe(1);
    });

    it('WHEN rendered THEN badge has correct title attribute', () => {
      render(<RelationshipBadge ciId="CI-A" relationships={singleConnectedSourceMap} />);
      const dot = document.querySelector('[title="CONNECTS_TO"]');
      expect(dot).not.toBeNull();
    });
  });

  describe('GIVEN a CI with multiple relationship types', () => {
    it('WHEN rendered THEN both green and blue badge dots are displayed', () => {
      render(<RelationshipBadge ciId="CI-A" relationships={multiTypeMap} />);
      const greenDots = document.querySelectorAll('.bg-green-500');
      const blueDots = document.querySelectorAll('.bg-blue-500');
      expect(greenDots.length).toBe(1);
      expect(blueDots.length).toBe(1);
    });
  });

  describe('GIVEN a CI with no relationships', () => {
    it('WHEN rendered THEN no badge is rendered', () => {
      render(<RelationshipBadge ciId="CI-X" relationships={emptyMap} />);
      const dots = document.querySelectorAll('.bg-green-500, .bg-blue-500');
      expect(dots.length).toBe(0);
    });
  });

  describe('GIVEN a CI with no entry in relationship map', () => {
    it('WHEN rendered THEN no badge is rendered', () => {
      render(<RelationshipBadge ciId="NONEXISTENT" relationships={emptyMap} />);
      const dots = document.querySelectorAll('[title="DEPENDS_ON"], [title="CONNECTS_TO"]');
      expect(dots.length).toBe(0);
    });
  });
});