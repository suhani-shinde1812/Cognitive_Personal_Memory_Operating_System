// 📁 LOCATION: frontend/src/app/chat/page.tsx
"use client";
import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import ReactMarkdown from "react-markdown";
import { sendChat, MemorySource } from "@/services/api";
import { smartTitle } from "@/utils/helpers";
import {
  Send, Brain, User, Cpu, Target, Loader2, Trash2,
  FlaskConical, ChevronDown, ChevronUp, FileText, Image,
  File, MapPin, Zap, Clock, ExternalLink,
} from "lucide-react";
import toast from "react-hot-toast";

interface Message {
  role:          "user" | "assistant";
  content:       string;
  memories_used?: any[];
  goal_context?:  string[];
  sources?:       MemorySource[];
  fast_answer?:   boolean;
  confidence?:    number;
}

const STARTERS = [
  "What programming language do I prefer for backend development?",
  "What documents do I have for Germany Masters?",
  "Show all my certificates and courses",
  "Summarize my career documents",
];

// Helper: derive icon from file type
function FileIcon({ fileType, className = "" }: { fileType: string; className?: string }) {
  const t = (fileType || "").toLowerCase();
  if (t === "pdf")  return <FileText size={13} className={`text-red-400 ${className}`} />;
  if (["jpg","jpeg","png","webp","bmp","gif"].includes(t))
                    return <Image size={13} className={`text-amber-400 ${className}`} />;
  if (["docx","doc"].includes(t))
                    return <FileText size={13} className={`text-blue-400 ${className}`} />;
  if (t === "txt")  return <FileText size={13} className={`text-gray-400 ${className}`} />;
  return <File size={13} className={`text-gray-400 ${className}`} />;
}

// Source card shown below each AI answer
function MemorySourceCard({ source, index }: { source: MemorySource; index: number }) {
  const [expanded, setExpanded] = useState(false);

  const displayPath = source.file_path || source.source || "Unknown location";
  const shortPath = displayPath.length > 55
    ? "…" + displayPath.slice(-52)
    : displayPath;

  return (
    <motion.div
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: index * 0.07 }}
      className="bg-[#0e0e1c]/80 border border-[#252540] rounded-xl p-3 space-y-2 hover:border-brand-500/40 transition-all"
    >
      {/* Header row */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <div className="w-6 h-6 rounded-md bg-brand-600/20 border border-brand-500/30 flex items-center justify-center shrink-0">
            <FileIcon fileType={source.file_type} />
          </div>
          <div className="min-w-0">
            <p className="text-xs font-bold text-white leading-tight truncate">
              {source.title || source.source || "Memory"}
            </p>
            <p className="text-[10px] text-gray-400 font-mono truncate mt-0.5" title={displayPath}>
              📍 {shortPath}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <span className="text-[10px] font-mono bg-emerald-950/40 text-emerald-400 border border-emerald-800/30 px-1.5 py-0.5 rounded font-bold">
            {(source.relevance_score * (source.relevance_score <= 1 ? 100 : 1)).toFixed(0)}%
          </span>
          {source.abstract && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="text-gray-500 hover:text-brand-400 transition-colors"
            >
              {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            </button>
          )}
        </div>
      </div>

      {/* Abstract (expandable) */}
      <AnimatePresence>
        {expanded && source.abstract && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <p className="text-[11px] text-gray-300 leading-relaxed border-t border-[#252540] pt-2">
              {source.abstract}
            </p>
          </motion.div>
        )}
      </AnimatePresence>

      {/* File type badge */}
      {source.file_type && (
        <div className="flex items-center gap-2">
          <span className="text-[10px] uppercase font-bold px-1.5 py-0.5 rounded bg-surface border border-surface-border text-gray-400">
            {source.file_type}
          </span>
          {source.timestamp && (
            <span className="text-[10px] text-gray-500 flex items-center gap-1">
              <Clock size={10} />
              {new Date(source.timestamp).toLocaleDateString()}
            </span>
          )}
        </div>
      )}
    </motion.div>
  );
}

export default function ChatPage() {
  const [messages,     setMessages]     = useState<Message[]>([]);
  const [input,        setInput]        = useState("");
  const [sessionId,    setSessionId]    = useState<string | undefined>();
  const [loading,      setLoading]      = useState(false);
  const [researchMode, setResearchMode] = useState(true);
  const [expandedMem,  setExpandedMem]  = useState<number | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = async (text = input) => {
    const q = text.trim();
    if (!q || loading) return;
    setInput("");
    setMessages(prev => [...prev, { role: "user", content: q }]);
    setLoading(true);

    try {
      const res = await sendChat(q, sessionId);
      setSessionId(res.session_id);
      setMessages(prev => [...prev, {
        role:          "assistant",
        content:       res.answer,
        memories_used: res.memories_used,
        goal_context:  res.goal_context,
        sources:       res.sources || [],
        fast_answer:   res.fast_answer,
        confidence:    res.confidence,
      }]);
    }
    catch (err: any) {
      console.error(err);
      const message =
        err?.response?.data?.answer ||
        err?.response?.data?.detail ||
        err?.message ||
        "Unknown error";

      toast.error(message);

      setMessages(prev => [
        ...prev,
        { role: "assistant", content: message },
      ]);
    }
    finally {
      setLoading(false);
    }
  };

  const clearChat = () => {
    setMessages([]);
    setSessionId(undefined);
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-surface-border">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-brand-600 flex items-center justify-center">
            <Brain size={16} className="text-white" />
          </div>
          <div>
            <h1 className="text-sm font-semibold text-white">CogniSphere AI Chat</h1>
            <p className="text-xs text-gray-500">Retrieval-Augmented Generation over ACMA Memory Graph</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* Research Mode Toggle */}
          <button
            onClick={() => setResearchMode(!researchMode)}
            className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border transition-all ${
              researchMode
                ? "bg-brand-600/20 border-brand-500/50 text-brand-300 font-medium"
                : "border-surface-border text-gray-400 hover:text-white"
            }`}
          >
            <FlaskConical size={13} />
            <span>Research Mode</span>
            <span className={`w-2 h-2 rounded-full ${researchMode ? "bg-brand-400 animate-pulse" : "bg-gray-600"}`} />
          </button>

          {messages.length > 0 && (
            <button onClick={clearChat} className="btn-ghost text-xs">
              <Trash2 size={13} /> Clear
            </button>
          )}
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center pt-16 gap-6">
            <div className="w-16 h-16 rounded-2xl bg-brand-600/20 border border-brand-600/30 flex items-center justify-center">
              <Brain size={28} className="text-brand-400" />
            </div>
            <div className="text-center">
              <h2 className="text-lg font-semibold text-white mb-1">Ask CogniSphere</h2>
              <p className="text-sm text-gray-400 max-w-sm">
                Ask questions about your files & memories. The AI retrieves matching documents,
                shows their file path and a summary of each source.
              </p>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2 w-full max-w-lg">
              {STARTERS.map(s => (
                <button key={s} onClick={() => send(s)}
                  className="card p-3 text-left text-sm text-gray-300 hover:text-white hover:border-brand-600/50 transition-all">
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        <AnimatePresence>
          {messages.map((msg, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              className={`flex gap-3 ${msg.role === "user" ? "flex-row-reverse" : ""}`}
            >
              {/* Avatar */}
              <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${
                msg.role === "user" ? "bg-surface-hover" : "bg-brand-600"
              }`}>
                {msg.role === "user" ? <User size={14} className="text-gray-300" /> : <Brain size={14} className="text-white" />}
              </div>

              <div className={`flex-1 max-w-2xl ${msg.role === "user" ? "items-end flex flex-col" : ""}`}>
                {/* Answer bubble */}
                <div className={`rounded-xl px-4 py-3 text-sm leading-relaxed ${
                  msg.role === "user"
                    ? "bg-brand-600 text-white"
                    : "bg-surface-card border border-surface-border text-gray-200"
                }`}>
                  {msg.role === "assistant"
                    ? <ReactMarkdown>{msg.content}</ReactMarkdown>
                    : msg.content
                  }
                </div>

                {/* Fast / confidence badge */}
                {msg.role === "assistant" && msg.confidence !== undefined && (
                  <div className="flex items-center gap-2 mt-1.5 px-1">
                    {msg.fast_answer && (
                      <span className="flex items-center gap-1 text-[10px] font-bold text-emerald-400 bg-emerald-950/30 border border-emerald-800/30 px-2 py-0.5 rounded-full">
                        <Zap size={9} /> Instant Answer
                      </span>
                    )}
                    <span className="text-[10px] text-gray-500 font-mono">
                      Confidence: {msg.confidence?.toFixed(1)}%
                    </span>
                  </div>
                )}

                {/* ── Memory Sources with File Address & Abstract ── */}
                {msg.role === "assistant" && msg.sources && msg.sources.length > 0 && (
                  <div className="mt-3 space-y-2 w-full">
                    <div className="flex items-center gap-2 px-1">
                      <MapPin size={11} className="text-brand-400" />
                      <p className="text-xs font-bold uppercase tracking-wider text-brand-400">
                        Memory Sources & File Addresses
                      </p>
                      <span className="text-[10px] text-gray-500">({msg.sources.length})</span>
                    </div>
                    {msg.sources.map((src, si) => (
                      <MemorySourceCard key={src.memory_id ?? si} source={src} index={si} />
                    ))}
                  </div>
                )}

                {/* Research Mode ACMA breakdown */}
                {researchMode && msg.memories_used && msg.memories_used.length > 0 && (
                  <div className="mt-3 space-y-2 w-full">
                    <div className="flex items-center justify-between border-b border-surface-border pb-1">
                      <p className="text-xs font-bold uppercase tracking-wider text-purple-400 flex items-center gap-1.5">
                        <Cpu size={12} /> ACMA Re-ranking Details
                      </p>
                      <span className="text-[10px] font-mono text-gray-400">Research Mode</span>
                    </div>

                    {msg.memories_used.map((m: any, mIdx: number) => {
                      const isExpanded = expandedMem === m.id;
                      const actScore = (m.activation_score ?? 0).toFixed(2);
                      const comps = m.components;

                      return (
                        <div key={m.id || mIdx} className="card p-3 border-surface-border bg-surface-card/60 text-xs space-y-2">
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <span className="font-mono text-gray-400 font-bold">#{mIdx + 1}</span>
                              <span className="text-white font-semibold">{smartTitle("", m.title)}</span>
                            </div>
                            <div className="flex items-center gap-2">
                              <span className="font-mono text-emerald-400 font-bold bg-emerald-950/40 px-2 py-0.5 rounded border border-emerald-800/40">
                                Score: {actScore}
                              </span>
                              <button
                                onClick={() => setExpandedMem(isExpanded ? null : m.id)}
                                className="text-gray-400 hover:text-white p-1"
                              >
                                {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                              </button>
                            </div>
                          </div>

                          {m.activation_reason && (
                            <p className="text-[11px] text-gray-400 font-mono">
                              Reason: {m.activation_reason}
                            </p>
                          )}

                          {/* ACMA Score Breakdown */}
                          <div className={`mt-2 pt-2 border-t border-surface-border space-y-1 ${!isExpanded && "hidden"}`}>
                            <p className="font-mono font-bold text-[10px] text-brand-300 uppercase tracking-wider">
                              ACMA 6-Factor Activation Equation:
                            </p>
                            <div className="grid grid-cols-2 md:grid-cols-3 gap-2 font-mono text-[11px] bg-surface-hover p-2.5 rounded border border-surface-border">
                              <div><span className="text-gray-400">Semantic:</span> <span className="text-white font-bold">{comps?.semantic ?? "—"}</span></div>
                              <div><span className="text-gray-400">Goal:</span> <span className="text-white font-bold">{comps?.goal ?? "—"}</span></div>
                              <div><span className="text-gray-400">Relationship:</span> <span className="text-white font-bold">{comps?.relationship ?? "—"}</span></div>
                              <div><span className="text-gray-400">Importance:</span> <span className="text-white font-bold">{comps?.importance ?? "—"}</span></div>
                              <div><span className="text-gray-400">Temporal:</span> <span className="text-white font-bold">{comps?.temporal ?? "—"}</span></div>
                              <div><span className="text-gray-400">Access:</span> <span className="text-white font-bold">{comps?.access ?? "—"}</span></div>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* Goal context */}
                {msg.goal_context && msg.goal_context.length > 0 && (
                  <div className="flex items-center gap-2 mt-2 flex-wrap">
                    <Target size={11} className="text-yellow-500" />
                    {msg.goal_context.map(g => (
                      <span key={g} className="badge badge-yellow">{g}</span>
                    ))}
                  </div>
                )}
              </div>
            </motion.div>
          ))}
        </AnimatePresence>

        {loading && (
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-brand-600 flex items-center justify-center">
              <Brain size={14} className="text-white" />
            </div>
            <div className="card px-4 py-3 flex items-center gap-2 text-sm text-gray-400">
              <Loader2 size={14} className="animate-spin text-brand-400" />
              Searching memories with ACMA Engine…
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-6 py-4 border-t border-surface-border">
        <div className="flex gap-3">
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === "Enter" && !e.shiftKey && send()}
            placeholder="Ask about your memories, files, or documents..."
            className="input"
          />
          <button onClick={() => send()} disabled={!input.trim() || loading} className="btn-primary px-4">
            <Send size={16} />
          </button>
        </div>
      </div>
    </div>
  );
}