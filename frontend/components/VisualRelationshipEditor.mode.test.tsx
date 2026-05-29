import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { GraphNode } from '../types';
import VisualRelationshipEditor from './VisualRelationshipEditor';

const { mockApiPost, mockApiDelete } = vi.hoisted(() => ({
  mockApiPost: vi.fn(),
  mockApiDelete: vi.fn(),
}));

vi.mock('../services/api', () => ({
  api: {
    post: mockApiPost,
    delete: mockApiDelete,
  },
}));

const nodes: GraphNode[] = [
  { id: 'ci-a', label: 'Router A', type: 'INFRASTRUCTURE', status: 'OK', metadata: {} },
];

describe('VisualRelationshipEditor page mode', () => {
  beforeEach(() => {
    mockApiPost.mockReset();
    mockApiDelete.mockReset();
  });

  it('renders as a full-page workspace without modal overlay constraints', () => {
    const { container } = render(
      <VisualRelationshipEditor
        nodes={nodes}
        links={[]}
        mode="page"
        onClose={vi.fn()}
        onMutated={vi.fn()}
      />,
    );

    expect(screen.getByText('Visual Relationship Editor')).toBeInTheDocument();
    expect(screen.getByLabelText('Visual CI relationship map')).toBeInTheDocument();
    expect(container.querySelector('.fixed.inset-0')).not.toBeInTheDocument();
  });
});
