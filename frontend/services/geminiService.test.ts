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
    });
    expect(answer).toBe('Check the active Redis incident first.');
  });

  it('returns an empty string when the backend answer is empty', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ answer: '', model: 'local-model' });

    const answer = await chatWithAIAgent('Hello', '');

    expect(answer).toBe('');
  });
});
