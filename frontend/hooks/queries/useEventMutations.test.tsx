import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { queryKeys } from '../../services/queryKeys';
import { useEventMutations } from './useEventMutations';

const { mockApiPost } = vi.hoisted(() => ({
  mockApiPost: vi.fn(),
}));

vi.mock('../../services/api', () => ({
  api: {
    post: mockApiPost,
  },
}));

function Probe() {
  const mutations = useEventMutations();

  return (
    <div>
      <button onClick={() => mutations.ackEvent('evt-1')}>ack</button>
      <button onClick={() => mutations.commentEvent('evt-1', { message: 'note', user: 'admin' })}>comment</button>
      <button onClick={() => mutations.takeEvent('evt-1', { user: 'admin', tier: 'T1' })}>take</button>
      <button onClick={() => mutations.closeEvent('evt-1', { forced: true })}>close</button>
      <button onClick={() => mutations.pruneEvents()}>prune</button>
      <button onClick={() => mutations.diagnoseEvent('evt-1', { user: 'admin' })}>diagnose</button>
    </div>
  );
}

describe('useEventMutations', () => {
  let client: QueryClient;

  beforeEach(() => {
    client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    vi.spyOn(client, 'invalidateQueries');
    mockApiPost.mockReset();
    mockApiPost.mockResolvedValue({ ok: true });
  });

  it.each([
    ['ack', '/events/evt-1/ack'],
    ['comment', '/events/evt-1/comment'],
    ['take', '/events/evt-1/comment'],
    ['close', '/events/evt-1/close'],
    ['prune', '/events/prune'],
    ['diagnose', '/events/evt-1/diagnose'],
  ] as const)('invalidates active events after %s succeeds', async (buttonName, endpoint) => {
    render(
      <QueryClientProvider client={client}>
        <Probe />
      </QueryClientProvider>
    );

    fireEvent.click(screen.getByRole('button', { name: buttonName }));

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalled();
    });

    await waitFor(() => {
      expect(client.invalidateQueries).toHaveBeenCalledWith({ queryKey: queryKeys.activeEvents() });
    });

    expect(mockApiPost).toHaveBeenCalledWith(endpoint, expect.anything());
  });
});
