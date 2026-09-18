/* global DOMException */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import AIAgentConsole from "../AIAgentConsole";
import { chatWithAIAgent, type AIChatResponse } from "../../services/geminiService";

vi.mock("../../services/geminiService", async () => {
  const actual = await vi.importActual<typeof import("../../services/geminiService")>(
    "../../services/geminiService",
  );
  return {
    chatWithAIAgent: vi.fn(actual.chatWithAIAgent),
  };
});

describe("AIAgentConsole", () => {
  beforeEach(() => {
    // mockReset clears any mockResolvedValue/mockImplementationOnce that
    // leaked from earlier tests, so each test starts from a clean slate.
    vi.mocked(chatWithAIAgent).mockReset();
    vi.clearAllMocks();
    cleanup();
  });

  it("passes an AbortSignal to chatWithAIAgent", async () => {
    const mockChat = vi
      .mocked(chatWithAIAgent)
      .mockResolvedValue({ answer: "response" } satisfies AIChatResponse);
    render(<AIAgentConsole />);
    const input = screen.getByPlaceholderText(/Describe action/i);
    fireEvent.change(input, { target: { value: "test message" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => expect(mockChat).toHaveBeenCalledTimes(1));
    expect(mockChat.mock.calls[0][3]).toBeInstanceOf(AbortSignal);
  });

  it("silently handles AbortError without showing error message", async () => {
    vi.mocked(chatWithAIAgent).mockRejectedValue(new DOMException("Aborted", "AbortError"));
    render(<AIAgentConsole />);
    const input = screen.getByPlaceholderText(/Describe action/i);
    fireEvent.change(input, { target: { value: "test" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => {
      expect(vi.mocked(chatWithAIAgent)).toHaveBeenCalledTimes(1);
    });
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByText("Network disruption in AI reasoning layer.")).toBeNull();
  });

  it("shows error message for non-abort errors", async () => {
    vi.mocked(chatWithAIAgent).mockRejectedValue(new Error("Server error"));
    render(<AIAgentConsole />);
    const input = screen.getByPlaceholderText(/Describe action/i);
    fireEvent.change(input, { target: { value: "test" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => {
      expect(screen.getByText("Network disruption in AI reasoning layer.")).toBeTruthy();
    });
  });

  it("aborts previous request when sending a new message", async () => {
    const firstCall = new Promise<AIChatResponse>(() => undefined);
    const mockChat = vi
      .mocked(chatWithAIAgent)
      .mockImplementationOnce(() => firstCall)
      .mockResolvedValueOnce({ answer: "second response" } satisfies AIChatResponse);

    render(<AIAgentConsole />);
    const input = screen.getByPlaceholderText(/Describe action/i);

    fireEvent.change(input, { target: { value: "first" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(mockChat).toHaveBeenCalledTimes(1));

    const firstSignal = mockChat.mock.calls[0][3] as unknown as AbortSignal;
    expect(firstSignal).toBeInstanceOf(AbortSignal);
  });

  // --- Typography bump tests (REQ-APL-005) ---

  it("renders the header label with text-sm (was text-xs)", () => {
    render(<AIAgentConsole />);
    const header = screen.getByText(/NEX-GEN Reasoning Engine/i);
    expect(header.className).toMatch(/text-sm/);
    expect(header.className).not.toMatch(/text-xs/);
  });

  it("renders the input with text-base (was text-sm)", () => {
    render(<AIAgentConsole />);
    const input = screen.getByPlaceholderText(/Describe action/i);
    expect(input.className).toMatch(/text-base/);
  });

  it("renders message bubbles with text-base after sending a message", async () => {
    vi.mocked(chatWithAIAgent).mockResolvedValue({
      answer: "assistant reply",
    } satisfies AIChatResponse);
    render(<AIAgentConsole />);
    const input = screen.getByPlaceholderText(/Describe action/i);
    fireEvent.change(input, { target: { value: "hello" } });
    fireEvent.keyDown(input, { key: "Enter" });
    // Wait for the assistant bubble to render
    await waitFor(() => {
      expect(screen.getByText("assistant reply")).toBeTruthy();
    });
    const bubble = screen.getByText("assistant reply").closest('div[class*="rounded-2xl"]');
    expect(bubble).not.toBeNull();
    expect(bubble!.className).toMatch(/text-base/);
  });

  // --- feat-489 propose_ci link rendering ---

  it("renders a per-message proposal link when harness_result is a successful propose_ci", async () => {
    vi.mocked(chatWithAIAgent).mockResolvedValue({
      answer: "Proposal drafted for review.",
      harness_result: {
        type: "propose_ci",
        status: "DRAFT",
        proposal_id: "prop-abc-123",
        ci_id: "edge-router-bogota-01",
        version: 1,
      },
    } satisfies AIChatResponse);
    render(<AIAgentConsole />);
    const input = screen.getByPlaceholderText(/Describe action/i);
    fireEvent.change(input, { target: { value: "add edge router" } });
    fireEvent.keyDown(input, { key: "Enter" });

    const link = await waitFor(() => screen.getByTestId("proposal-link-prop-abc-123"));
    expect(link.getAttribute("href")).toBe("/#/proposals/cmdb?id=prop-abc-123");
    expect(link.textContent).toMatch(/edge-router-bogota-01/);
  });

  it("does NOT render a proposal link when harness_result is denied", async () => {
    vi.mocked(chatWithAIAgent).mockResolvedValue({
      answer: "Rate-limited, retry later.",
      harness_result: {
        type: "propose_ci",
        denied: true,
        reason_code: "cooldown_active",
      },
    } satisfies AIChatResponse);
    render(<AIAgentConsole />);
    const input = screen.getByPlaceholderText(/Describe action/i);
    fireEvent.change(input, { target: { value: "add CI" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => {
      expect(screen.getByText("Rate-limited, retry later.")).toBeTruthy();
    });
    // No proposal-link testid present
    expect(screen.queryByTestId(/^proposal-link-/)).toBeNull();
  });

  it("does NOT render a proposal link when harness_result is an error", async () => {
    vi.mocked(chatWithAIAgent).mockResolvedValue({
      answer: "Could not create proposal: ci_id_collision.",
      harness_result: {
        type: "propose_ci",
        status: "error",
        reason: "ci_id_collision",
      },
    } satisfies AIChatResponse);
    render(<AIAgentConsole />);
    const input = screen.getByPlaceholderText(/Describe action/i);
    fireEvent.change(input, { target: { value: "add CI" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => {
      expect(screen.getByText(/ci_id_collision/)).toBeTruthy();
    });
    expect(screen.queryByTestId(/^proposal-link-/)).toBeNull();
  });

  it("does NOT render a proposal link when harness_result is null or absent", async () => {
    vi.mocked(chatWithAIAgent).mockResolvedValue({
      answer: "Just an answer, no harness result.",
    } satisfies AIChatResponse);
    render(<AIAgentConsole />);
    const input = screen.getByPlaceholderText(/Describe action/i);
    fireEvent.change(input, { target: { value: "hello" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => {
      expect(screen.getByText("Just an answer, no harness result.")).toBeTruthy();
    });
    expect(screen.queryByTestId(/^proposal-link-/)).toBeNull();
  });
});
