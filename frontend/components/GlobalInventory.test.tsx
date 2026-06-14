import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import GlobalInventory from './GlobalInventory';
import type { GraphNode } from '../types';

const mockUseNodesQuery = vi.fn();
const mockUseCategoriesQuery = vi.fn();

vi.mock('../hooks/queries/useNodesQuery', () => ({
  useNodesQuery: () => mockUseNodesQuery(),
}));

vi.mock('../hooks/queries/useCategoriesQuery', () => ({
  useCategoriesQuery: () => mockUseCategoriesQuery(),
}));

const makeNode = (overrides: Partial<GraphNode> = {}): GraphNode => ({
  id: overrides.id ?? 'node-1',
  label: overrides.label ?? 'Router-01',
  type: overrides.type ?? 'INFRASTRUCTURE',
  status: overrides.status ?? 'ACTIVE',
  metadata: overrides.metadata ?? {},
  ip: overrides.ip ?? '10.0.0.1',
  category: overrides.category ?? 'Network',
  metrics: overrides.metrics ?? [],
  ...overrides,
});

describe('GlobalInventory', () => {
  let nodes: GraphNode[];

  beforeEach(() => {
    mockUseNodesQuery.mockReset();
    mockUseCategoriesQuery.mockReset();
    nodes = [];
    mockUseNodesQuery.mockImplementation(() => ({ data: nodes, isLoading: false }));
    mockUseCategoriesQuery.mockReturnValue({ data: [{ name: 'Network' }] });
  });

  it('renders shared nodes and categories from query hooks', () => {
    nodes = [makeNode({ id: 'node-1', label: 'Router-01' }), makeNode({ id: 'node-2', label: 'Switch-01', ip: '10.0.0.2' })];

    render(<GlobalInventory />);

    expect(screen.getByText('Router-01')).toBeInTheDocument();
    expect(screen.getByText('Switch-01')).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'Network' })).toBeInTheDocument();
  });

  it('preserves the selected ci by identifier across refreshes', () => {
    const selectedId = 'node-1';
    nodes = [makeNode({ id: selectedId, metrics: [{ name: 'CPU Load', protocol: 'SNMP', oid: '1', value: '42', status: 'OK', last_updated: '2026-04-04T10:00:00.000Z' }] })];

    const { rerender } = render(<GlobalInventory />);

    fireEvent.click(screen.getByText('Router-01'));
    expect(screen.getByText('42')).toBeInTheDocument();

    nodes = [makeNode({ id: selectedId, metrics: [{ name: 'CPU Load', protocol: 'SNMP', oid: '1', value: '95', status: 'CRITICAL', last_updated: '2026-04-04T10:05:00.000Z' }] })];

    rerender(<GlobalInventory />);

    expect(screen.getByText('ID: node-1')).toBeInTheDocument();
    expect(screen.getByText('95')).toBeInTheDocument();
  });

  it('clears the selected ci when the refreshed dataset no longer contains that id', () => {
    nodes = [makeNode({ id: 'node-1', label: 'Router-01' })];

    const { rerender } = render(<GlobalInventory />);

    fireEvent.click(screen.getByText('Router-01'));
    expect(screen.getByText('ID: node-1')).toBeInTheDocument();

    nodes = [makeNode({ id: 'node-2', label: 'Switch-01', ip: '10.0.0.2' })];

    rerender(<GlobalInventory />);

    expect(screen.queryByText('ID: node-1')).not.toBeInTheDocument();
    expect(screen.getByText('Select a CI to view telemetry')).toBeInTheDocument();
  });

  it('renders explicit category technology icons while keeping critical status separate', () => {
    nodes = [makeNode({
      id: 'router-1',
      label: 'Edge Router',
      category: 'Network',
      category_icon_key: 'router',
      metrics: [{ name: 'CPU Load', protocol: 'SNMP', oid: '1', value: '95', status: 'CRITICAL', last_updated: '2026-04-04T10:05:00.000Z' }],
    })];

    render(<GlobalInventory />);

    expect(screen.getByRole('img', { name: 'Router technology icon' })).toBeInTheDocument();

    fireEvent.click(screen.getByText('Edge Router'));

    expect(screen.getAllByRole('img', { name: 'Router technology icon' })).toHaveLength(2);
    expect(screen.getByText('warning')).toBeInTheDocument();
  });

  it('falls back to a category-name technology icon when icon metadata is missing', () => {
    nodes = [makeNode({
      id: 'switch-1',
      label: 'Access Switch',
      category: 'Layer 2 Switch',
      category_icon_key: null,
    })];

    render(<GlobalInventory />);

    expect(screen.getByRole('img', { name: 'Layer 2 Switch technology icon' })).toBeInTheDocument();

    fireEvent.click(screen.getByText('Access Switch'));

    expect(screen.getAllByRole('img', { name: 'Layer 2 Switch technology icon' })).toHaveLength(2);
  });
});
