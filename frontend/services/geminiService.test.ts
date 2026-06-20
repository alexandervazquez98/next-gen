import { beforeEach, describe, expect, it, vi } from 'vitest';
import { chatWithAIAgent } from './geminiService';
import { api } from './api';

vi.mock('./api', () => ({
  api: {
    post: vi.fn(),
  },
}));

describe('chatWithAIAgent', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('posts chat requests to the backend AI endpoint and returns the answer', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({
      answer: 'Check the active Redis incident first.',
      model: 'local-model',
    });

    const answer = await chatWithAIAgent('What should I check?', 'Incident console context');

    expect(api.post).toHaveBeenCalledWith('/ai/chat', {
      query: 'What should I check?',
      context: 'Incident console context',
      intent: undefined,
    }, { signal: undefined });
    expect(answer).toBe('Check the active Redis incident first.');
  });

  it('returns an empty string when the backend answer is empty', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ answer: '', model: 'local-model' });

    const answer = await chatWithAIAgent('Hello', '');

    expect(answer).toBe('');
  });

  it('forwards signal to api.post config', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ answer: 'ok' });
    const controller = new AbortController();
    await chatWithAIAgent('hello', 'ctx', undefined, controller.signal);
    expect(api.post).toHaveBeenCalledWith(
      '/ai/chat',
      { query: 'hello', context: 'ctx', intent: undefined },
      { signal: controller.signal },
    );
  });

  it('passes undefined signal when not provided', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ answer: 'ok' });
    await chatWithAIAgent('hello', 'ctx');
    expect(api.post).toHaveBeenCalledWith(
      '/ai/chat',
      { query: 'hello', context: 'ctx', intent: undefined },
      { signal: undefined },
    );
  });

  it('propagates AbortError when signal is aborted', async () => {
    vi.mocked(api.post).mockRejectedValue(new DOMException('Aborted', 'AbortError'));
    const controller = new AbortController();
    controller.abort();
    await expect(chatWithAIAgent('hello', 'ctx', undefined, controller.signal))
      .rejects.toThrow('Aborted');
  });
});
