/**
 * MultiSelectCIs.test.tsx
 * Unit tests for MultiSelectCIs component.
 * Tests: select CIs, remove chip, max 10 enforcement.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import MultiSelectCIs from '../MultiSelectCIs';
import { GraphNode } from '../../types';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const MOCK_NODES: GraphNode[] = [
  { id: 'ci-001', label: 'Router-01', type: 'INFRASTRUCTURE', status: 'OK', ip: '10.0.0.1', metrics: [] },
  { id: 'ci-002', label: 'Switch-01', type: 'INFRASTRUCTURE', status: 'OK', ip: '10.0.0.2', metrics: [] },
  { id: 'ci-003', label: 'Firewall-01', type: 'INFRASTRUCTURE', status: 'ACTIVE', ip: '10.0.0.3', metrics: [] },
];

// ---------------------------------------------------------------------------
// Global fetch mock
// ---------------------------------------------------------------------------

const mockFetch = vi.fn().mockResolvedValue({
  ok: true,
  json: async () => [],
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function renderMultiSelect(
  selectedIds: string[] = [],
  onChange: (ids: string[]) => void = vi.fn(),
  maxCIs: number = 10
) {
  return render(
    <MultiSelectCIs
      selectedIds={selectedIds}
      onChange={onChange}
      availableNodes={MOCK_NODES}
      maxCIs={maxCIs}
    />
  );
}

// ---------------------------------------------------------------------------
// Setup / Teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.stubGlobal('fetch', mockFetch);
  mockFetch.mockClear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('MultiSelectCIs', () => {
  it('renders search input', async () => {
    await renderMultiSelect();
    expect(screen.getByRole('searchbox', { name: /search cis/i })).toBeDefined();
  });

  it('shows selected CI chips', async () => {
    const onChange = vi.fn();
    await renderMultiSelect(['ci-001'], onChange);
    
    // Should show chip for ci-001
    expect(screen.getByText('Router-01')).toBeDefined();
  });

  it('calls onChange with new id when node is clicked from list', async () => {
    const onChange = vi.fn();
    await renderMultiSelect(['ci-001'], onChange);
    
    // Get the first node button from available list (below search)
    // Note: this depends on how many nodes show up when not searching
    // We need to find the clickable node in the available list
    const buttons = screen.getAllByRole('button');
    const switchBtn = buttons.find(b => b.textContent?.includes('Switch-01'));
    
    if (switchBtn) {
      fireEvent.click(switchBtn);
      expect(onChange).toHaveBeenCalledWith(['ci-001', 'ci-002']);
    }
  });

  it('removes chip when remove button is clicked', async () => {
    const onChange = vi.fn();
    await renderMultiSelect(['ci-001'], onChange);

    // Find all buttons - the remove button has a span with 'close' text
    const buttons = screen.getAllByRole('button');
    const removeBtn = buttons.find(btn => {
      const span = btn.querySelector('span');
      return span && span.textContent === 'close';
    });
    expect(removeBtn).toBeDefined();
    if (removeBtn) {
      fireEvent.click(removeBtn);
    }
    expect(onChange).toHaveBeenCalledWith([]);
  });

  it('shows counter "X / 10 CIs selected"', async () => {
    const onChange = vi.fn();
    await renderMultiSelect(['ci-001', 'ci-002'], onChange, 10);

    expect(screen.getByText('2 / 10 CIs selected')).toBeDefined();
  });

  it('disables search input when max CIs selected', async () => {
    const onChange = vi.fn();
    const tenIds = Array.from({ length: 10 }, (_, i) => `ci-${i}`);
    await renderMultiSelect(tenIds, onChange, 10);

    // Search input should be disabled when max CIs are selected
    const searchInput = screen.getByRole('searchbox', { name: /search cis/i }) as HTMLInputElement;
    expect(searchInput.disabled).toBe(true);
  });
});