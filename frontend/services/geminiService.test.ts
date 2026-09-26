import { beforeEach, describe, expect, it, vi } from "vitest";
import { chatWithAIAgent } from "./geminiService";
/* global DOMException */
import { api } from "./api";

vi.mock("./api", () => ({
  api: {
    post: vi.fn(),
  },
}));

describe("chatWithAIAgent", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts chat requests to the backend AI endpoint and returns the answer", async () => {
    vi.mocked(api.post).mockResolvedValueOnce({
      answer: "Check the active Redis incident first.",
      model: "local-model",
    });

    const response = await chatWithAIAgent("What should I check?", "Incident console context");

    expect(api.post).toHaveBeenCalledWith(
      "/ai/chat",
      {
        query: "What should I check?",
        context: "Incident console context",
      },
      { signal: undefined },
    );
    expect(response.answer).toBe("Check the active Redis incident first.");
    expect(response.model).toBe("local-model");
  });

  it("returns an empty string when the backend answer is empty", async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ answer: "", model: "local-model" });

    const response = await chatWithAIAgent("Hello", "");

    expect(response.answer).toBe("");
  });

  it("forwards signal to api.post config", async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ answer: "ok" });
    const controller = new AbortController();
    await chatWithAIAgent("hello", "ctx", undefined, controller.signal);
    expect(api.post).toHaveBeenCalledWith(
      "/ai/chat",
      { query: "hello", context: "ctx" },
      { signal: controller.signal },
    );
  });

  it("forwards explicit backend intent when provided", async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ answer: "ok" });

    await chatWithAIAgent("list events", "ctx", { type: "event_list", status: "OPEN", limit: 10 });

    expect(api.post).toHaveBeenCalledWith(
      "/ai/chat",
      {
        query: "list events",
        context: "ctx",
        intent: { type: "event_list", status: "OPEN", limit: 10 },
      },
      { signal: undefined },
    );
  });

  it("passes undefined signal when not provided", async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ answer: "ok" });
    await chatWithAIAgent("hello", "ctx");
    expect(api.post).toHaveBeenCalledWith(
      "/ai/chat",
      { query: "hello", context: "ctx" },
      { signal: undefined },
    );
  });

  // feat-489: chatWithAIAgent now returns AIChatResponse so the console can
  // surface harness_result.proposal_id as a per-message review link.
  it("forwards propose_ci intent with manifest and exposes harness_result (feat-489)", async () => {
    vi.mocked(api.post).mockResolvedValueOnce({
      answer: "Proposal submitted.",
      harness_result: {
        type: "propose_ci",
        status: "DRAFT",
        proposal_id: "prop-xyz",
        ci_id: "edge-router-01",
        version: 1,
      },
    });

    const response = await chatWithAIAgent("add edge router", "ctx", {
      type: "propose_ci",
      manifest: {
        schema_version: 1,
        ci: { id: "edge-router-01", type: "Router", name: "edge-router-01" },
      },
      source_refs: ["chat:msg-1"],
    });

    expect(api.post).toHaveBeenCalledWith(
      "/ai/chat",
      {
        query: "add edge router",
        context: "ctx",
        intent: {
          type: "propose_ci",
          manifest: {
            schema_version: 1,
            ci: { id: "edge-router-01", type: "Router", name: "edge-router-01" },
          },
          source_refs: ["chat:msg-1"],
        },
      },
      { signal: undefined },
    );
    expect(response.answer).toBe("Proposal submitted.");
    expect(response.harness_result?.type).toBe("propose_ci");
    expect(response.harness_result?.proposal_id).toBe("prop-xyz");
  });

  it("propagates AbortError when signal is aborted", async () => {
    vi.mocked(api.post).mockRejectedValue(new DOMException("Aborted", "AbortError"));
    const controller = new AbortController();
    controller.abort();
    await expect(chatWithAIAgent("hello", "ctx", undefined, controller.signal)).rejects.toThrow(
      "Aborted",
    );
  });
});
