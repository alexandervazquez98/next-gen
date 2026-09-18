/* global DOMException */
import type React from "react";
import { useState, useRef, useEffect } from "react";
import { ApiError } from "../services/api";
import { chatWithAIAgent } from "../services/geminiService";
import { ProposalBadge } from "./cmdb/proposals/ProposalBadge";
import { useAuth } from "../context/AuthContext";

interface Message {
  role: "user" | "assistant";
  content: string;
  // feat-489: backend-supplied harness_result for this assistant turn.
  // For propose_ci submissions, this carries {type, status, proposal_id,
  // ci_id, version} so the console can render a per-message review link.
  harnessResult?: Record<string, unknown> | null;
}

function extractProposalLink(
  harnessResult: Record<string, unknown> | null | undefined,
): { proposalId: string; ciId: string | null } | null {
  if (!harnessResult || typeof harnessResult !== "object") return null;
  if (harnessResult.type !== "propose_ci") return null;
  if (harnessResult.denied === true) return null;
  if (harnessResult.status === "error") return null;
  const proposalId =
    typeof harnessResult.proposal_id === "string" ? harnessResult.proposal_id : null;
  if (!proposalId) return null;
  const ciId = typeof harnessResult.ci_id === "string" ? harnessResult.ci_id : null;
  return { proposalId, ciId };
}

function useSafeHasPermission(perm: string): boolean {
  // Defensive: when the console is rendered without an AuthProvider (e.g. legacy
  // unit tests), bail out as if the user has no permission. This keeps the badge
  // hidden instead of crashing the chat console.
  try {
    return useAuth().hasPermission(perm);
  } catch {
    return false;
  }
}

const AIAgentConsole: React.FC = () => {
  const canReviewProposals = useSafeHasPermission("CI_APPROVE_PROPOSAL");
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content:
        "Agentic AI Online. Monitoring all Graph nodes for anomalies. How can I assist with your ITIL value streams today?",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort();
    };
  }, []);

  const handleSend = async () => {
    if (!input.trim() || loading) return;

    const userMsg: Message = { role: "user", content: input };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;
    const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(60_000)]);

    try {
      const context =
        "Current Context: User is interacting with NEX-GEN AI chat. Use backend harness results as the source of truth for live event or diagnostic data.";
      const response = await chatWithAIAgent(input, context, undefined, signal);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: response.answer || "Unable to process request.",
          harnessResult: response.harness_result ?? null,
        },
      ]);
    } catch (error) {
      if (
        (error instanceof Error && error.name === "AbortError") ||
        (error instanceof DOMException && error.name === "AbortError")
      ) {
        return;
      }
      // eslint-disable-next-line no-console
      console.error(error);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content:
            error instanceof ApiError ? error.message : "Network disruption in AI reasoning layer.",
        },
      ]);
    } finally {
      abortControllerRef.current = null;
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full glass border-none rounded-none overflow-hidden">
      <div className="p-4 border-b border-white/5 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-3 h-3 bg-accent-cyan rounded-full animate-ping"></div>
          <span className="text-sm font-black uppercase tracking-widest text-white">
            NEX-GEN Reasoning Engine
          </span>
        </div>
        <div className="text-[10px] text-neutral-500 font-mono">MODEL: NexCO-Gen1</div>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4 custom-scrollbar">
        {messages.map((m, i) => {
          const proposalLink =
            m.role === "assistant" ? extractProposalLink(m.harnessResult) : null;
          return (
            <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <div className="flex flex-col gap-2 max-w-[85%]">
                <div
                  className={`p-3 rounded-2xl text-base leading-relaxed whitespace-pre-wrap break-words ${
                    m.role === "user"
                      ? "bg-brand-600 text-white rounded-tr-none"
                      : "bg-neutral-800/80 text-neutral-200 border border-white/5 rounded-tl-none"
                  }`}
                >
                  {m.content}
                </div>
                {proposalLink && (
                  <a
                    data-testid={`proposal-link-${proposalLink.proposalId}`}
                    href={`/#/proposals/cmdb?id=${proposalLink.proposalId}`}
                    className="self-start inline-flex items-center gap-2 text-xs px-3 py-1.5 rounded-lg bg-emerald-500/10 text-emerald-300 border border-emerald-500/30 hover:bg-emerald-500/20 transition-colors"
                  >
                    <span className="material-symbols-outlined text-sm">rule</span>
                    Review CI proposal
                    {proposalLink.ciId && (
                      <span className="font-mono text-emerald-200/80">({proposalLink.ciId})</span>
                    )}
                    <span className="text-emerald-400/60">→</span>
                  </a>
                )}
              </div>
            </div>
          );
        })}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-neutral-800/80 p-3 rounded-2xl rounded-tl-none border border-white/5 flex gap-1">
              <div className="w-1.5 h-1.5 bg-accent-cyan rounded-full animate-bounce"></div>
              <div className="w-1.5 h-1.5 bg-accent-cyan rounded-full animate-bounce delay-100"></div>
              <div className="w-1.5 h-1.5 bg-accent-cyan rounded-full animate-bounce delay-200"></div>
            </div>
          </div>
        )}
      </div>

      <div className="p-4 bg-black/40 border-t border-white/5">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-[10px] font-black uppercase tracking-widest text-neutral-500">
            MODEL: NexCO-Gen1
          </span>
          <ProposalBadge canReview={canReviewProposals} />
        </div>
        <div className="relative">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSend()}
            placeholder="Describe action (e.g., 'Fix redis latency', 'Mapp CI dependencies')"
            className="w-full bg-neutral-900 border border-white/10 rounded-xl py-3 pl-4 pr-12 text-base text-white focus:outline-none focus:border-brand-500 transition-all"
          />
          <button
            onClick={handleSend}
            disabled={loading}
            className="absolute right-2 top-1.5 p-1.5 text-brand-400 hover:text-white transition-colors"
          >
            <span className="material-symbols-outlined text-xl">send</span>
          </button>
        </div>
      </div>
    </div>
  );
};

export default AIAgentConsole;
