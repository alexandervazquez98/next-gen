/**
 * MultiMetricChart.test.tsx
 * Unit tests for MultiMetricChart component.
 * Tests: stacked layout, synchronized brush updates multiple panels.
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import MultiMetricChart from '../MultiMetricChart';
import { NodeMetricData } from '../../types';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const SAMPLE_NODE_DATA: NodeMetricData[] = [
  {
    node_id: 'ci-001',
    label: 'Router-01',
    data: [
      { time: '2026-05-12T10:00:00Z', value: 42 },
      { time: '2026-05-12T10:00:30Z', value: 43 },
    ],
  },
  {
    node_id: 'ci-002',
    label: 'Switch-01',
    data: [
      { time: '2026-05-12T10:00:00Z', value: 10 },
      { time: '2026-05-12T10:00:30Z', value: 12 },
    ],
  },
];

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('MultiMetricChart', () => {
  it('shows "Select CIs to Compare" when no data provided', async () => {
    render(
      <MultiMetricChart
        nodeData={[]}
        brushRange={null}
        onBrushChange={vi.fn()}
      />
    );

    expect(screen.getByText('Select CIs to Compare')).toBeDefined();
  });

  it('renders one ChartPanel per node', async () => {
    render(
      <MultiMetricChart
        nodeData={SAMPLE_NODE_DATA}
        brushRange={null}
        onBrushChange={vi.fn()}
      />
    );

    expect(screen.getByText('Router-01')).toBeDefined();
    expect(screen.getByText('Switch-01')).toBeDefined();
  });

  it('shows "2 data points" per panel for sample data', async () => {
    render(
      <MultiMetricChart
        nodeData={SAMPLE_NODE_DATA}
        brushRange={null}
        onBrushChange={vi.fn()}
      />
    );

    const pointsLabels = screen.getAllByText('2 data points');
    expect(pointsLabels.length).toBe(2);
  });

  it('passes same brushRange to all ChartPanels', async () => {
    const onBrushChange = vi.fn();
    render(
      <MultiMetricChart
        nodeData={SAMPLE_NODE_DATA}
        brushRange={{ startTime: '2026-05-12T10:00:00Z', endTime: '2026-05-12T10:00:30Z' }}
        onBrushChange={onBrushChange}
      />
    );

    // Both panels should show "2 points selected"
    const selectedLabels = screen.getAllByText('2 points selected');
    expect(selectedLabels.length).toBe(2);
  });
});