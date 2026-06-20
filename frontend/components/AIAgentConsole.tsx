
import React, { useState, useRef, useEffect } from 'react';
import { chatWithAIAgent } from '../services/geminiService';

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

const AIAgentConsole: React.FC = () => {
  const [messages, setMessages] = useState<Message[]>([
    { role: 'assistant', content: 'Agentic AI Online. Monitoring all Graph nodes for anomalies. How can I assist with your ITIL value streams today?' }
  ]);
  const [input, setInput] = useState('');
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

    const userMsg: Message = { role: 'user', content: input };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setLoading(true);

    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;
    const signal = AbortSignal.any([
      controller.signal,
      AbortSignal.timeout(60_000),
    ]);

    try {
      const response = await chatWithAIAgent(input, "Current Context: User viewing Incident Console. 2 Critical alerts on Redis Cache.", undefined, signal);
      setMessages(prev => [...prev, { role: 'assistant', content: response || 'Unable to process request.' }]);
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError" || error instanceof DOMException && error.name === "AbortError") {
        return;
      }
      console.error(error);
      setMessages(prev => [...prev, { role: 'assistant', content: 'Network disruption in AI reasoning layer.' }]);
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
          <span className="text-xs font-black uppercase tracking-widest text-white">NEX-GEN Reasoning Engine</span>
        </div>
        <div className="text-[10px] text-neutral-500 font-mono">MODEL: NexCO-Gen1</div>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4 custom-scrollbar">
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[85%] p-3 rounded-2xl text-sm leading-relaxed ${m.role === 'user'
                ? 'bg-brand-600 text-white rounded-tr-none'
                : 'bg-neutral-800/80 text-neutral-200 border border-white/5 rounded-tl-none'
              }`}>
              {m.content}
            </div>
          </div>
        ))}
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
        <div className="relative">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSend()}
            placeholder="Describe action (e.g., 'Fix redis latency', 'Mapp CI dependencies')"
            className="w-full bg-neutral-900 border border-white/10 rounded-xl py-3 pl-4 pr-12 text-sm text-white focus:outline-none focus:border-brand-500 transition-all"
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
