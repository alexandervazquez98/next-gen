import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import AIAgentConsole from './AIAgentConsole';
import { chatWithAIAgent } from '../services/geminiService';

vi.mock('../services/geminiService', () => ({
  chatWithAIAgent: vi.fn(),
}));

describe('AIAgentConsole', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('preserves multiline deterministic harness responses in the chat bubble', async () => {
    vi.mocked(chatWithAIAgent).mockResolvedValueOnce(
      'Eventos observados:\n- [INFO / OPEN] SWITCH C2: Service/Host Down\n\nLímites:\n- No confirma causa raíz.',
    );

    render(<AIAgentConsole />);

    fireEvent.change(screen.getByPlaceholderText(/Describe action/i), {
      target: { value: 'que eventos hay abiertos?' },
    });
    fireEvent.click(screen.getByRole('button'));

    const response = await screen.findByText(/Eventos observados:/);
    expect(response).toHaveTextContent('SWITCH C2');
    expect(response).toHaveTextContent('No confirma causa raíz.');
    expect(response).toHaveClass('whitespace-pre-wrap');
    expect(response).toHaveClass('break-words');

    await waitFor(() => expect(chatWithAIAgent).toHaveBeenCalledOnce());
  });
});
