import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
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
      <button onClick={() => mutations.commentEvent('evt-1', { message: 'note', user: 'admin' }).catch(() => undefined)}>comment</button>
      <button onClick={() => mutations.takeEvent('evt-1', { user: 'admin', tier: 'T1' }).catch(() => undefined)}>take</button>
      <button onClick={() => mutations.closeEvent('evt-1', { forced: true }).catch(() => undefined)}>close</button>
      <button onClick={() => mutations.pruneEvents().catch(() => undefined)}>prune</button>
      <button onClick={() => mutations.diagnoseEvent('evt-1', { user: 'admin' }).catch(() => undefined)}>diagnose</button>
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
    ['take', '/events/evt-1/ack'],
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
      expect(client.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['events'] });
    });

    expect(mockApiPost).toHaveBeenCalledWith(endpoint, expect.anything());
  });

  it('routes take-case through the ack endpoint without client-generated ownership text', async () => {
    render(
      <QueryClientProvider client={client}>
        <Probe />
      </QueryClientProvider>
    );

    fireEvent.click(screen.getByRole('button', { name: 'take' }));

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledTimes(1);
    });

    expect(mockApiPost.mock.calls[0]).toEqual([
      '/events/evt-1/ack',
      {},
    ]);
  });

  it('sends close audit data through the close endpoint atomically', async () => {
    render(
      <QueryClientProvider client={client}>
        <Probe />
      </QueryClientProvider>
    );

    fireEvent.click(screen.getByRole('button', { name: 'close' }));

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledTimes(1);
    });

    expect(mockApiPost.mock.calls[0]).toEqual([
      '/events/evt-1/close',
      { forced: true },
    ]);
  });

  it('does not attempt a separate ownership comment call', async () => {
    render(
      <QueryClientProvider client={client}>
        <Probe />
      </QueryClientProvider>
    );

    fireEvent.click(screen.getByRole('button', { name: 'take' }));

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledTimes(1);
    });

    expect(mockApiPost).not.toHaveBeenCalledWith(
      '/events/evt-1/comment',
      expect.anything(),
    );
  });

  it('does not attempt a separate ownership write when ack fails', async () => {
    mockApiPost.mockImplementation((url: string) => {
      if (url === '/events/evt-1/ack') {
        return Promise.reject(new Error('ack-down'));
      }
      return Promise.resolve({ ok: true });
    });

    render(
      <QueryClientProvider client={client}>
        <Probe />
      </QueryClientProvider>
    );

    fireEvent.click(screen.getByRole('button', { name: 'take' }));

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledTimes(1);
    });

    expect(mockApiPost).toHaveBeenCalledWith('/events/evt-1/ack', {});
    expect(mockApiPost).not.toHaveBeenCalledWith('/events/evt-1/comment', expect.anything());
    expect(client.invalidateQueries).not.toHaveBeenCalled();
  });
});
