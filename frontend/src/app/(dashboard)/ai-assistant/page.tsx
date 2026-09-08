"use client";

import { useState, useRef, useEffect } from "react";
import axios from "axios";
import { Bot, Send, Loader2, User, Sparkles, RotateCcw } from "lucide-react";
import { cn } from "@/utils/cn";
import apiClient from "@/services/api-client";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  toolsUsed?: string[];
}

const SUGGESTED_PROMPTS = [
  "Summarize attendance trends for last month",
  "Which employees are on probation this quarter?",
  "Show me payroll cost breakdown by department",
  "List employees whose contracts expire soon",
  "How many leave days are remaining per team?",
  "Which devices have health issues?",
];

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  return (
    <div className={cn("flex items-start gap-3", isUser && "flex-row-reverse")}>
      <div className={cn(
        "flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold",
        isUser
          ? "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]"
          : "bg-[hsl(var(--secondary))] text-[hsl(var(--foreground-subtle))]",
      )}>
        {isUser ? <User size={13} /> : <Bot size={13} />}
      </div>
      <div className={cn(
        "max-w-[75%] rounded-2xl px-4 py-3 text-sm leading-relaxed",
        isUser
          ? "rounded-tr-sm bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]"
          : "rounded-tl-sm border border-[hsl(var(--border))] bg-[hsl(var(--background))]",
      )}>
        <p className="whitespace-pre-wrap">{message.content}</p>
        {message.toolsUsed && message.toolsUsed.length > 0 && (
          <p className="mt-1.5 flex flex-wrap gap-1 text-[10px] text-[hsl(var(--foreground-muted))]">
            <Sparkles size={10} className="mt-0.5 shrink-0" />
            Checked live data: {message.toolsUsed.map((t) => t.replace("get_", "").replace(/_/g, " ")).join(", ")}
          </p>
        )}
        <p className={cn(
          "mt-1.5 text-[10px]",
          isUser ? "text-white/50" : "text-[hsl(var(--foreground-muted))]",
        )}>
          {message.timestamp.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" })}
        </p>
      </div>
    </div>
  );
}

export default function AIAssistantPage() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "welcome",
      role: "assistant",
      content: "Hi! I'm your EWMP AI Assistant. I can help you analyze workforce data, generate reports, and answer questions about your employees, attendance, payroll, and devices.\n\nWhat would you like to know?",
      timestamp: new Date(0),
    },
  ]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Fixes the placeholder welcome message's timestamp (epoch 0, so its
  // relative "time ago" doesn't briefly show as 1970 during SSR/hydration)
  // exactly ONCE on mount. This must NOT depend on `messages`:
  // Array.prototype.map() always returns a brand-new array reference even
  // when every element inside is unchanged, so the previous version of
  // this effect — which had `messages` in its own dependency array while
  // also calling setMessages(...map(...)) unconditionally — replaced
  // `messages` with a new-but-content-identical array on every run, which
  // the effect then saw as "messages changed" and ran again: an infinite
  // render loop (100% CPU, unresponsive tab).
  useEffect(() => {
    setMessages((prev) =>
      prev[0]?.id === "welcome" && prev[0].timestamp.getTime() === 0
        ? [{ ...prev[0], timestamp: new Date() }, ...prev.slice(1)]
        : prev,
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-scrolls to the newest message. Depends on messages.length (a
  // primitive) rather than the `messages` array itself, so it only
  // re-fires when a message is actually added or removed — not on every
  // render that happens to touch `messages`'s reference for an unrelated
  // reason (e.g. the mount effect above, or a future edit to message
  // content in place).
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  async function sendMessage(text?: string) {
    const content = (text ?? input).trim();
    if (!content || isLoading) return;

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setIsLoading(true);

    try {
      const { data } = await apiClient.post<{ response: string; tools_used?: string[] }>("/ai/chat", {
        message: content,
        history: messages.slice(-10).map((m) => ({ role: m.role, content: m.content })),
      });

      const aiMsg: Message = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: data.response,
        timestamp: new Date(),
        toolsUsed: data.tools_used,
      };
      setMessages((prev) => [...prev, aiMsg]);
    } catch (error: unknown) {
      const detail = axios.isAxiosError(error)
        ? (error.response?.data as { detail?: string } | undefined)?.detail
        : undefined;
      const errMsg: Message = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: detail ?? "I'm having trouble connecting right now. Please check your AI provider configuration in Settings.",
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errMsg]);
    } finally {
      setIsLoading(false);
    }
  }

  function clearChat() {
    setMessages([{
      id: "welcome",
      role: "assistant",
      content: "Chat cleared. How can I help you?",
      timestamp: new Date(),
    }]);
  }

  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col gap-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-violet-500 to-purple-600">
            <Sparkles size={15} className="text-white" />
          </div>
          <div>
            <h1 className="font-heading text-base font-semibold">AI Assistant</h1>
            <p className="text-xs text-[hsl(var(--foreground-muted))]">Powered by Claude · Contextual HR intelligence</p>
          </div>
        </div>
        <button
          onClick={clearChat}
          className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs text-[hsl(var(--foreground-muted))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))] transition-colors"
        >
          <RotateCcw size={12} /> Clear chat
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background-subtle))] p-5">
        <div className="space-y-5">
          {messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))}

          {isLoading && (
            <div className="flex items-start gap-3">
              <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[hsl(var(--secondary))]">
                <Bot size={13} className="text-[hsl(var(--foreground-subtle))]" />
              </div>
              <div className="rounded-2xl rounded-tl-sm border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-4 py-3">
                <div className="flex items-center gap-1.5">
                  {[0, 1, 2].map((i) => (
                    <div
                      key={i}
                      className="h-1.5 w-1.5 rounded-full bg-[hsl(var(--foreground-muted))] animate-bounce"
                      style={{ animationDelay: `${i * 150}ms` }}
                    />
                  ))}
                </div>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* Suggested prompts */}
      {messages.length <= 1 && (
        <div className="flex flex-wrap gap-2">
          {SUGGESTED_PROMPTS.map((prompt) => (
            <button
              key={prompt}
              onClick={() => void sendMessage(prompt)}
              className="rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-3 py-1.5 text-xs text-[hsl(var(--foreground-subtle))] hover:border-[hsl(var(--border-strong))] hover:text-[hsl(var(--foreground))] transition-colors"
            >
              {prompt}
            </button>
          ))}
        </div>
      )}

      {/* Input */}
      <div className="flex items-end gap-2">
        <div className="flex-1 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-4 py-3 focus-within:ring-2 focus-within:ring-[hsl(var(--ring))] focus-within:ring-offset-1">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void sendMessage();
              }
            }}
            placeholder="Ask anything about your workforce…"
            rows={1}
            className="w-full resize-none bg-transparent text-sm outline-none placeholder:text-[hsl(var(--foreground-muted))]"
          />
        </div>
        <button
          onClick={() => void sendMessage()}
          disabled={!input.trim() || isLoading}
          className={cn(
            "flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] transition-all",
            "hover:bg-[hsl(var(--primary-hover))] disabled:cursor-not-allowed disabled:opacity-40",
          )}
        >
          {isLoading ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
        </button>
      </div>
    </div>
  );
}