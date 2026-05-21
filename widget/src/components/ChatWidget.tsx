import { useCallback, useEffect, useRef, useState } from "react";
import {
  askChat,
  ChatTimeoutError,
  probeApi,
  type ChatResponse,
  type WidgetConfig,
} from "../api";

type Message = {
  role: "user" | "assistant";
  content: string;
  meta?: string;
  isError?: boolean;
};

type Props = {
  config: WidgetConfig;
  sessionId: string;
  parentOrigin: string;
};

type ApiStatus = "checking" | "online" | "offline";

const COLLAPSED_SIZE = { width: 72, height: 72 };
// Wider panel — the previous 400px felt cramped on assistant paragraphs.
const EXPANDED_SIZE = { width: 460, height: 660 };
const REQUEST_TIMEOUT_MS = 20_000;
const SLOW_REQUEST_MESSAGE =
  "The language model is responding slowly. Please try again.";

export default function ChatWidget({ config, sessionId, parentOrigin }: Props) {
  const theme = config.theme || {};
  const primary = theme.primary_color || "#6366f1";
  const bubble = theme.bubble_color || primary;
  const title = theme.title || config.name || "Maintainer's Copilot";

  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [messages, setMessages] = useState<Message[]>(() =>
    config.greeting
      ? [{ role: "assistant", content: config.greeting }]
      : []
  );
  const [sources, setSources] = useState<string[]>([]);
  const [apiStatus, setApiStatus] = useState<ApiStatus>("checking");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  // One source of truth for "is a request currently in flight". We track
  // both a state (for re-renders) and a ref (so async handlers can see the
  // latest value without going stale through closures).
  const inFlightRef = useRef<AbortController | null>(null);
  // Mount flag — prevents setState after unmount from setting a stale
  // "Thinking…" indicator.
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      inFlightRef.current?.abort("unmount");
      inFlightRef.current = null;
    };
  }, []);

  // Auto-scroll to the bottom whenever a new message arrives OR the typing
  // indicator toggles. requestAnimationFrame avoids fighting layout.
  useEffect(() => {
    const id = window.requestAnimationFrame(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    });
    return () => window.cancelAnimationFrame(id);
  }, [messages.length, loading]);

  // ----- API readiness probe -----------------------------------------------
  // Runs every 15s while the panel is open. Pure UX signal — does NOT block
  // the user from typing.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;

    async function poll() {
      const ok = await probeApi(config.api_url);
      if (!cancelled && mountedRef.current) {
        setApiStatus(ok ? "online" : "offline");
      }
    }
    void poll();
    const handle = window.setInterval(poll, 15_000);
    return () => {
      cancelled = true;
      window.clearInterval(handle);
    };
  }, [open, config.api_url]);

  // ----- postMessage resize handshake with the parent loader ----------------

  const postSize = useCallback(
    (size: { width: number; height: number }) => {
      try {
        window.parent.postMessage(
          { type: "copilot:resize", width: size.width, height: size.height },
          parentOrigin
        );
      } catch {
        // Silently swallow — non-fatal; the iframe just stays at default size.
      }
    },
    [parentOrigin]
  );

  useEffect(() => {
    postSize(open ? EXPANDED_SIZE : COLLAPSED_SIZE);
  }, [open, postSize]);

  // Re-broadcast on viewport resize so the parent can clamp accordingly.
  useEffect(() => {
    function onResize() {
      postSize(open ? EXPANDED_SIZE : COLLAPSED_SIZE);
    }
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [open, postSize]);

  // ----- chat ---------------------------------------------------------------

  const containerRef = useRef<HTMLDivElement>(null);

  async function send() {
    const query = input.trim();
    // Guard against re-entrancy AND against firing while a previous request
    // is still in flight. The ref check is the authoritative one.
    if (!query || loading || inFlightRef.current) return;

    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: query }]);
    setLoading(true);

    const controller = new AbortController();
    inFlightRef.current = controller;

    let appended = false;
    const appendAssistant = (msg: Message) => {
      if (appended || !mountedRef.current) return;
      appended = true;
      setMessages((prev) => [...prev, msg]);
    };

    try {
      const data: ChatResponse = await askChat(
        config.api_url,
        query,
        sessionId,
        { signal: controller.signal, timeoutMs: REQUEST_TIMEOUT_MS }
      );

      // Component may have unmounted while we awaited — don't touch state.
      if (!mountedRef.current) return;
      if (data.sources?.length) setSources(data.sources);
      const meta = data.tool_trace?.length
        ? `tools: ${data.tool_trace.map((t) => t.name).join(", ")}`
        : undefined;
      appendAssistant({ role: "assistant", content: data.reply, meta });
    } catch (err) {
      if (!mountedRef.current) return;
      if (err instanceof ChatTimeoutError) {
        appendAssistant({
          role: "assistant",
          content: SLOW_REQUEST_MESSAGE,
          isError: true,
        });
      } else if (err instanceof DOMException && err.name === "AbortError") {
        // Cancellation due to unmount / explicit abort — silently swallow.
        return;
      } else {
        const msg = err instanceof Error ? err.message : String(err);
        appendAssistant({
          role: "assistant",
          content: `Couldn't reach the API: ${msg}`,
          isError: true,
        });
      }
    } finally {
      // Always clear the loading state — both the success and the error
      // branches above must release the "Thinking…" indicator.
      if (inFlightRef.current === controller) {
        inFlightRef.current = null;
      }
      if (mountedRef.current) {
        setLoading(false);
        // Belt-and-suspenders: if neither branch managed to append anything
        // (e.g. some exotic exception path), surface a generic error so the
        // UI never silently swallows a turn.
        if (!appended) {
          setMessages((prev) => [
            ...prev,
            {
              role: "assistant",
              content: SLOW_REQUEST_MESSAGE,
              isError: true,
            },
          ]);
        }
      }
    }
  }

  return (
    <div className="copilot-widget" ref={containerRef}>
      {open && (
        <div
          className="copilot-panel"
          style={{ "--accent": primary } as React.CSSProperties}
        >
          <header className="copilot-header">
            <div className="copilot-header-meta">
              <span className="copilot-header-avatar" aria-hidden="true">
                ✦
              </span>
              <div>
                <div className="copilot-header-title">{title}</div>
                <div
                  className={`copilot-header-sub copilot-status-${apiStatus}`}
                >
                  <span className="copilot-status-dot" />
                  {apiStatus === "online" && "Connected · grounded RAG"}
                  {apiStatus === "checking" && "Connecting…"}
                  {apiStatus === "offline" && "API offline"}
                </div>
              </div>
            </div>
            <button
              type="button"
              className="copilot-header-close"
              onClick={() => setOpen(false)}
              aria-label="Close chat"
            >
              ×
            </button>
          </header>

          <div className="copilot-messages">
            {messages.map((msg, i) => (
              <div
                key={i}
                className={`copilot-msg copilot-msg-${msg.role}${
                  msg.isError ? " copilot-msg-error" : ""
                }`}
              >
                {msg.role === "assistant" && (
                  <span
                    className="copilot-msg-avatar"
                    aria-hidden="true"
                    data-error={msg.isError ? "true" : undefined}
                  >
                    {msg.isError ? "!" : "✦"}
                  </span>
                )}
                <div className="copilot-msg-bubble">
                  <p>{msg.content}</p>
                  {msg.meta && <small>{msg.meta}</small>}
                </div>
              </div>
            ))}
            {loading && (
              <div className="copilot-msg copilot-msg-assistant copilot-msg-typing">
                <span className="copilot-msg-avatar" aria-hidden="true">
                  ✦
                </span>
                <div className="copilot-msg-bubble">
                  <span className="copilot-typing-dot" />
                  <span className="copilot-typing-dot" />
                  <span className="copilot-typing-dot" />
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {sources.length > 0 && (
            <details className="copilot-sources">
              <summary>
                Sources <span className="copilot-source-count">{sources.length}</span>
              </summary>
              <ul>
                {sources.map((src) => (
                  <li key={src}>
                    <code>{src}</code>
                  </li>
                ))}
              </ul>
            </details>
          )}

          <form
            className="copilot-input"
            onSubmit={(e) => {
              e.preventDefault();
              send();
            }}
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              placeholder="Ask anything about the docs…"
              disabled={loading}
              aria-label="Message"
            />
            <button
              type="submit"
              className="copilot-send"
              disabled={loading || !input.trim()}
              aria-label="Send"
            >
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M5 12h14" />
                <path d="M13 5l7 7-7 7" />
              </svg>
            </button>
          </form>
          <div className="copilot-footer">
            Powered by <strong>Maintainer's Copilot</strong>
          </div>
        </div>
      )}
      <button
        type="button"
        className={`copilot-bubble ${open ? "is-open" : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-label={open ? "Close chat" : "Open chat"}
        style={{ background: bubble }}
      >
        {open ? (
          <svg
            width="22"
            height="22"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.4"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M18 6L6 18" />
            <path d="M6 6l12 12" />
          </svg>
        ) : (
          <svg
            width="22"
            height="22"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
          </svg>
        )}
      </button>
    </div>
  );
}
