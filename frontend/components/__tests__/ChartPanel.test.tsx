/**
 * ChartPanel.test.tsx
 * Unit tests for ChartPanel component.
 * Tests: renders AreaChart, emits onBrushChange on zoom.
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import ChartPanel from '../ChartPanel';
import { DataPoint } from '../../types';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const SAMPLE_DATA: DataPoint[] = [
  { time: '2026-05-12T10:00:00Z', value: 42 },
  { time: '2026-05-12T10:00:30Z', value: 43 },
  { time: '2026-05-12T10:01:00Z', value: 45 },
  { time: '2026-05-12T10:01:30Z', value: 44 },
  { time: '2026-05-12T10:02:00Z', value: 46 },
];

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ChartPanel', () => {
  it('renders label in header', async () => {
    render(
      <ChartPanel
        nodeId="ci-001"
        label="Router-01"
        data={SAMPLE_DATA}
        brushRange={null}
        onBrushChange={vi.fn()}
      />
    );

    expect(screen.getByText('Router-01')).toBeDefined();
  });

  it('shows "No telemetry data" when data is empty', async () => {
    render(
      <ChartPanel
        nodeId="ci-001"
        label="Router-01"
        data={[]}
        brushRange={null}
        onBrushChange={vi.fn()}
      />
    );

    expect(screen.getByText('No telemetry data')).toBeDefined();
  });

  it('shows point count when data is loaded', async () => {
    render(
      <ChartPanel
        nodeId="ci-001"
        label="Router-01"
        data={SAMPLE_DATA}
        brushRange={null}
        onBrushChange={vi.fn()}
      />
    );

    expect(screen.getByText('5 data points')).toBeDefined();
  });

  it('shows selected point count when brush is applied', async () => {
    render(
      <ChartPanel
        nodeId="ci-001"
        label="Router-01"
        data={SAMPLE_DATA}
        brushRange={{ startTime: '2026-05-12T10:00:00Z', endTime: '2026-05-12T10:01:00Z' }}
        onBrushChange={vi.fn()}
      />
    );

    expect(screen.getByText('3 points selected')).toBeDefined();
  });

  it('renders reset button when brush is applied', async () => {
    render(
      <ChartPanel
        nodeId="ci-001"
        label="Router-01"
        data={SAMPLE_DATA}
        brushRange={{ startTime: '2026-05-12T10:00:00Z', endTime: '2026-05-12T10:01:00Z' }}
        onBrushChange={vi.fn()}
      />
    );

    expect(screen.getByRole('button', { name: /reset/i })).toBeDefined();
  });

  it('calls onBrushChange with null when reset is clicked', async () => {
    const onBrushChange = vi.fn();
    render(
      <ChartPanel
        nodeId="ci-001"
        label="Router-01"
        data={SAMPLE_DATA}
        brushRange={{ startTime: '2026-05-12T10:00:00Z', endTime: '2026-05-12T10:01:00Z' }}
        onBrushChange={onBrushChange}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: /reset/i }));
    expect(onBrushChange).toHaveBeenCalledWith(null);
  });
});