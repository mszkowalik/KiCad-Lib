import { useContext, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import {
  errorMessage,
  getJaravisStatus,
  isAbortError,
  jaravisChat,
  type ChatMessage,
  type ChatProposalRef,
  type ChatTraceItem,
  type JaravisStatus,
} from "../api";
import { ProposalsBadge } from "../App";
import { ErrorBanner, Spinner } from "../components/Ui";

interface ThreadMsg {
  role: "user" | "assistant";
  content: string;
  trace?: ChatTraceItem[];
  proposals?: ChatProposalRef[];
}

function TraceDetails({ trace }: { trace: ChatTraceItem[] }) {
  if (trace.length === 0) return null;
  return (
    <details className="trace">
      <summary>
        Tools used <span className="mono">({trace.length})</span>
      </summary>
      <ul>
        {trace.map((t, i) => (
          <li key={i}>
            <span className="mono trace-tool">{t.tool}</span>
            <pre>{JSON.stringify(t.input, null, 1)}</pre>
          </li>
        ))}
      </ul>
    </details>
  );
}

export default function Jaravis() {
  const [status, setStatus] = useState<JaravisStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [thread, setThread] = useState<ThreadMsg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [chatError, setChatError] = useState<string | null>(null);
  const { refresh: refreshBadge } = useContext(ProposalsBadge);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    getJaravisStatus(ctrl.signal)
      .then((s) => setStatus(s))
      .catch((err) => {
        if (!isAbortError(err)) setStatusError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, []);

  // elapsed-seconds ticker while a request is in flight
  useEffect(() => {
    if (!busy) return;
    setElapsed(0);
    const t = window.setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => window.clearInterval(t);
  }, [busy]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [thread, busy]);

  const canSend = status?.available === true && !busy && input.trim() !== "";

  const send = async () => {
    if (!canSend) return;
    const text = input.trim();
    const nextThread: ThreadMsg[] = [...thread, { role: "user", content: text }];
    setThread(nextThread);
    setInput("");
    setChatError(null);
    setBusy(true);
    try {
      const messages: ChatMessage[] = nextThread.map((m) => ({
        role: m.role,
        content: m.content,
      }));
      const res = await jaravisChat(messages);
      setThread((prev) => [
        ...prev,
        { role: "assistant", content: res.reply, trace: res.trace, proposals: res.proposals },
      ]);
      if (res.proposals.length > 0) refreshBadge();
    } catch (err) {
      setChatError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  };

  return (
    <div className="main-solo chat-solo">
      <div className="page chat-page">
        <div className="chat-head">
          <h1>Jaravis</h1>
          {status ? <span className="muted mono chat-model">{status.model}</span> : null}
        </div>

        {statusError ? <ErrorBanner message={`Status failed to load: ${statusError}`} /> : null}
        {status !== null && !status.available ? (
          <div className="banner-warn" role="alert">
            {status.hint ?? "Jaravis is not available."}
          </div>
        ) : null}

        <div className="chat-thread" aria-live="polite">
          {thread.length === 0 && status?.available ? (
            <p className="muted chat-empty">
              Ask the librarian — look things up, check consistency, or propose new parts and
              edits. Changes land as drafts in <Link to="/proposals">Proposals</Link>.
            </p>
          ) : null}
          {thread.map((m, i) => (
            <div key={i} className={`msg ${m.role}`}>
              <div className="msg-meta mono">{m.role === "user" ? "you" : "jaravis"}</div>
              <div className="msg-body">{m.content}</div>
              {m.role === "assistant" && m.trace ? <TraceDetails trace={m.trace} /> : null}
              {m.role === "assistant" && m.proposals && m.proposals.length > 0 ? (
                <div className="proposal-note">
                  Created {m.proposals.length} proposal{m.proposals.length === 1 ? "" : "s"} (
                  <span className="mono">
                    {m.proposals.map((p) => p.component).join(", ")}
                  </span>
                  ) — <Link to="/proposals">review in Proposals</Link>
                </div>
              ) : null}
            </div>
          ))}
          {busy ? (
            <div className="msg assistant">
              <div className="msg-meta mono">jaravis</div>
              <div className="msg-body working">
                <Spinner />
                <span>
                  Jaravis is working… <span className="mono">{elapsed}s</span>
                </span>
              </div>
            </div>
          ) : null}
          {chatError ? <ErrorBanner message={chatError} /> : null}
          <div ref={bottomRef} />
        </div>

        <div className="chat-input">
          <textarea
            className="text chat-textarea"
            rows={2}
            placeholder={
              status?.available ? "Message Jaravis… (Enter to send, Shift+Enter for newline)" : "Jaravis is unavailable"
            }
            value={input}
            disabled={status?.available !== true || busy}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            aria-label="Message Jaravis"
          />
          <button type="button" className="btn btn-accent" disabled={!canSend} onClick={() => void send()}>
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
