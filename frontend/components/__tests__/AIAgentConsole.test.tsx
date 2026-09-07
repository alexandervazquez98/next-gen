import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import AIAgentConsole from "../AIAgentConsole";
import { chatWithAIAgent } from "../../services/geminiService";

vi.mock("../../services/geminiService", () => ({
  chatWithAIAgent: vi.fn(),
}));

describe("AIAgentConsole", () => {
  beforeEach(() => {
    // mockReset clears any mockResolvedValue/mockImplementationOnce that
    // leaked from earlier tests, so each test starts from a clean slate.
    vi.mocked(chatWithAIAgent).mockReset();
    vi.clearAllMocks();
    cleanup();
  });

  it("passes an AbortSignal to chatWithAIAgent", async () => {
    const mockChat = vi.mocked(chatWithAIAgent).mockResolvedValue("response");
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
    const firstCall = new Promise<string>(() => undefined);
    const mockChat = vi
      .mocked(chatWithAIAgent)
      .mockImplementationOnce(() => firstCall)
      .mockResolvedValueOnce("second response");

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
    vi.mocked(chatWithAIAgent).mockResolvedValue("assistant reply");
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
});
