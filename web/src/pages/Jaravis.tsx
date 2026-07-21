import { useContext, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import {
  ApiError,
  attachJaravisRun,
  cancelJaravisRun,
  createJaravisSession,
  deleteJaravisSession,
  errorMessage,
  getJaravisSession,
  getJaravisStatus,
  isAbortError,
  jaravisSessionChatStream,
  listJaravisSessions,
  renameJaravisSession,
  type ChatProposalRef,
  type ChatStreamEvent,
  type ChatTraceItem,
  type JaravisSessionSummary,
  type JaravisStatus,
  type StoredChatMessage,
} from "../api";
import { ProposalsBadge } from "../App";
import { useDialog } from "../components/Dialog";
import { ErrorBanner, Spinner } from "../components/Ui";

/** Remembers which conversation was open, so a reload returns to it. */
const ACTIVE_KEY = "jaravis.activeSession";

interface ThreadMsg {
  role: "user" | "assistant";
  content: string;
  trace?: ChatTraceItem[];
  proposals?: ChatProposalRef[];
}

function toThreadMsg(m: StoredChatMessage): ThreadMsg {
  return { role: m.role, content: m.content, trace: m.trace, proposals: m.proposals };
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

/** One-line summary of a tool input for the live feed. */
function inputSummary(input: unknown): string {
  if (input == null) return "";
  const s = JSON.stringify(input);
  return s.length > 90 ? `${s.slice(0, 90)}…` : s;
}

export default function Jaravis() {
  const [status, setStatus] = useState<JaravisStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [sessions, setSessions] = useState<JaravisSessionSummary[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [thread, setThread] = useState<ThreadMsg[]>([]);
  const [loadingSession, setLoadingSession] = useState(false);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false); // a turn is streaming (sent or reattached)
  const [attaching, setAttaching] = useState(false); // probing/attaching to an existing run
  const [elapsed, setElapsed] = useState(0);
  const [chatError, setChatError] = useState<string | null>(null);
  const [progress, setProgress] = useState<ChatTraceItem[]>([]);
  const [note, setNote] = useState<string | null>(null);
  const { refresh: refreshBadge } = useContext(ProposalsBadge);
  const dialog = useDialog();
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const sessionLoadRef = useRef<AbortController | null>(null);
  const progressRef = useRef<ChatTraceItem[]>([]);
  // Mirrors activeId for async callbacks that must ignore results from a
  // session the user has since switched away from.
  const activeIdRef = useRef<number | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    getJaravisStatus(ctrl.signal)
      .then((s) => setStatus(s))
      .catch((err) => {
        if (!isAbortError(err)) setStatusError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, []);

  // Load the session list on mount and reopen the last-active conversation
  // (or the most recent one). Empty list = the "start a new chat" empty state.
  useEffect(() => {
    let cancelled = false;
    listJaravisSessions()
      .then((list) => {
        if (cancelled) return;
        setSessions(list);
        const saved = Number(localStorage.getItem(ACTIVE_KEY));
        const initial = list.find((s) => s.id === saved) ?? list[0];
        if (initial) void openSession(initial.id);
      })
      .catch((err) => {
        if (!cancelled) setChatError(errorMessage(err));
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
  }, [thread, busy, loadingSession]);

  const refreshSessions = async () => {
    try {
      setSessions(await listJaravisSessions());
    } catch {
      /* sidebar only — never surface a refresh failure */
    }
  };

  /** Progress-event handling shared by a fresh send and a reattach. Returns
   *  true when the event was consumed here; the caller handles "done". */
  const applyProgressEvent = (ev: ChatStreamEvent, sessionId: number): boolean => {
    if (ev.type === "tool" && ev.tool) {
      progressRef.current = [...progressRef.current, { tool: ev.tool, input: ev.input }];
      setProgress(progressRef.current);
      return true;
    }
    if (ev.type === "note") {
      setNote(ev.text ?? null);
      return true;
    }
    if (ev.type === "session") {
      if (ev.title) {
        const title = ev.title;
        setSessions((prev) => prev.map((s) => (s.id === sessionId ? { ...s, title } : s)));
      }
      return true;
    }
    if (ev.type === "error") {
      setChatError(ev.error ?? "Jaravis failed");
      return true;
    }
    return false; // "done"
  };

  /** After a reload, re-attach to a run still executing for this session (or
   *  reconcile a turn that just finished). Only called when the loaded thread
   *  ends on a user message — the signature of an unfinished turn. */
  const reattach = async (id: number) => {
    setAttaching(true);
    setChatError(null);
    progressRef.current = [];
    setProgress([]);
    setNote("Reattaching to a run in progress…");
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      await attachJaravisRun(
        id,
        (ev) => {
          setBusy(true); // events arriving ⇒ a run is live
          if (applyProgressEvent(ev, id)) return;
          if (ev.type === "done" && (ev.proposals?.length ?? 0) > 0) refreshBadge();
        },
        ctrl.signal,
      );
      // The run (if any) persisted the reply; the stored messages are now
      // authoritative. Reload them rather than appending, to avoid duplicates.
      if (id === activeIdRef.current) {
        const d = await getJaravisSession(id);
        if (id === activeIdRef.current) setThread(d.messages.map(toThreadMsg));
        void refreshSessions();
      }
    } catch (err) {
      if (!isAbortError(err) && id === activeIdRef.current) setChatError(errorMessage(err));
    } finally {
      if (abortRef.current === ctrl) abortRef.current = null;
      setAttaching(false);
      setBusy(false);
      setProgress([]);
      setNote(null);
    }
  };

  const openSession = async (id: number) => {
    if (busy || attaching || id === activeId) return;
    setActiveId(id);
    activeIdRef.current = id;
    localStorage.setItem(ACTIVE_KEY, String(id));
    setChatError(null);
    setLoadingSession(true);
    sessionLoadRef.current?.abort();
    const ctrl = new AbortController();
    sessionLoadRef.current = ctrl;
    try {
      const detail = await getJaravisSession(id, ctrl.signal);
      const msgs = detail.messages.map(toThreadMsg);
      setThread(msgs);
      const last = msgs[msgs.length - 1];
      if (last && last.role === "user") void reattach(id); // unfinished turn
    } catch (err) {
      if (!isAbortError(err)) setChatError(errorMessage(err));
    } finally {
      if (sessionLoadRef.current === ctrl) setLoadingSession(false);
    }
  };

  const newSession = async () => {
    if (busy || attaching) return;
    try {
      const s = await createJaravisSession();
      setSessions((prev) => [s, ...prev]);
      setActiveId(s.id);
      activeIdRef.current = s.id;
      localStorage.setItem(ACTIVE_KEY, String(s.id));
      setThread([]);
      setChatError(null);
    } catch (err) {
      void dialog.alert(errorMessage(err), { title: "Could not create chat" });
    }
  };

  const renameSession = async (s: JaravisSessionSummary) => {
    const next = await dialog.prompt("Rename conversation:", { title: "Rename", initial: s.title });
    if (next == null || next.trim() === "") return;
    try {
      const updated = await renameJaravisSession(s.id, next.trim());
      setSessions((prev) => prev.map((x) => (x.id === s.id ? { ...x, title: updated.title } : x)));
    } catch (err) {
      void dialog.alert(errorMessage(err), { title: "Rename failed" });
    }
  };

  const removeSession = async (s: JaravisSessionSummary) => {
    const ok = await dialog.confirm(`Delete "${s.title}"? The whole conversation is removed.`, {
      title: "Delete chat",
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (!ok) return;
    try {
      await deleteJaravisSession(s.id);
      setSessions((prev) => prev.filter((x) => x.id !== s.id));
      if (activeId === s.id) {
        setActiveId(null);
        activeIdRef.current = null;
        setThread([]);
        localStorage.removeItem(ACTIVE_KEY);
      }
    } catch (err) {
      void dialog.alert(errorMessage(err), { title: "Delete failed" });
    }
  };

  /** Stop the current run server-side (it keeps going otherwise) and detach. */
  const stop = async () => {
    const id = activeIdRef.current;
    abortRef.current?.abort();
    if (id != null) {
      try {
        await cancelJaravisRun(id);
      } catch {
        /* best-effort */
      }
    }
  };

  const canSend =
    status?.available === true && !busy && !attaching && input.trim() !== "";

  const send = async () => {
    if (canSend !== true) return;
    const text = input.trim();

    // Create a conversation lazily on the first message, so idle empty
    // sessions never pile up in the sidebar.
    let sessionId = activeId;
    if (sessionId == null) {
      try {
        const s = await createJaravisSession();
        sessionId = s.id;
        setSessions((prev) => [s, ...prev]);
        setActiveId(s.id);
        activeIdRef.current = s.id;
        localStorage.setItem(ACTIVE_KEY, String(s.id));
      } catch (err) {
        setChatError(errorMessage(err));
        return;
      }
    }

    setThread((prev) => [...prev, { role: "user", content: text }]);
    setInput("");
    setChatError(null);
    setBusy(true);
    setProgress([]);
    setNote(null);
    progressRef.current = [];
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      await jaravisSessionChatStream(
        sessionId,
        text,
        (ev) => {
          if (applyProgressEvent(ev, sessionId)) return;
          if (ev.type === "done") {
            setThread((prev) => [
              ...prev,
              {
                role: "assistant",
                content: ev.reply ?? "",
                trace: ev.trace ?? [],
                proposals: ev.proposals ?? [],
              },
            ]);
            if ((ev.proposals?.length ?? 0) > 0) refreshBadge();
          }
        },
        ctrl.signal,
      );
    } catch (err) {
      if (isAbortError(err)) {
        setThread((prev) => [
          ...prev,
          {
            role: "assistant",
            content:
              "(Stopped by you. The run was cancelled server-side; any drafts already created are in Proposals.)",
            trace: progressRef.current,
          },
        ]);
      } else if (err instanceof ApiError && err.status === 409) {
        // A turn is already running for this session (e.g. started in another
        // tab). Drop the optimistic bubble and attach to the existing run.
        setThread((prev) => prev.slice(0, -1));
        void reattach(sessionId);
      } else {
        setChatError(errorMessage(err));
      }
    } finally {
      setBusy(false);
      setProgress([]);
      setNote(null);
      abortRef.current = null;
      void refreshSessions();
    }
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  };

  const running = busy || attaching;
  const lastMsg = thread[thread.length - 1];
  const danglingTurn = !running && !loadingSession && lastMsg?.role === "user";

  return (
    <div className="main-solo chat-solo">
      <aside className="chat-sessions">
        <button
          type="button"
          className="btn btn-sm btn-accent chat-new"
          disabled={running}
          onClick={() => void newSession()}
        >
          + New chat
        </button>
        <div className="session-list">
          {sessions.map((s) => (
            <div key={s.id} className={`session-item ${s.id === activeId ? "active" : ""}`}>
              <button
                type="button"
                className="session-open"
                title={s.title}
                disabled={running && s.id !== activeId}
                onClick={() => void openSession(s.id)}
              >
                <span className="session-title">{s.title}</span>
                <span className="session-sub mono">
                  {s.message_count} msg{s.message_count === 1 ? "" : "s"}
                </span>
              </button>
              <div className="session-actions">
                <button
                  type="button"
                  className="icon-btn"
                  title="Rename"
                  onClick={() => void renameSession(s)}
                >
                  ✎
                </button>
                <button
                  type="button"
                  className="icon-btn"
                  title="Delete"
                  onClick={() => void removeSession(s)}
                >
                  ✕
                </button>
              </div>
            </div>
          ))}
          {sessions.length === 0 ? <p className="muted dim session-empty">No conversations yet.</p> : null}
        </div>
      </aside>

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
          {loadingSession ? (
            <div className="session-loading">
              <Spinner label="Loading conversation…" />
            </div>
          ) : null}
          {!loadingSession && thread.length === 0 && status?.available ? (
            <p className="muted chat-empty">
              Ask the librarian — look things up, check consistency, or propose new parts and
              edits. Changes land as drafts in <Link to="/proposals">Proposals</Link>. Your
              conversations are saved and keep running even if you close the page; start a fresh
              one any time with <strong>New chat</strong>.
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
          {danglingTurn ? (
            <p className="muted dim chat-empty">
              This turn didn’t finish — it may have been stopped, or the server restarted while it
              was running. Send another message to continue.
            </p>
          ) : null}
          {busy ? (
            <div className="msg assistant">
              <div className="msg-meta mono">jaravis</div>
              <div className="msg-body working">
                <Spinner />
                <span>
                  Jaravis is working… <span className="mono">{elapsed}s</span>
                  {progress.length > 0 ? (
                    <span className="mono"> · {progress.length} tool call{progress.length === 1 ? "" : "s"}</span>
                  ) : null}
                </span>
                <button type="button" className="btn btn-sm btn-danger" onClick={() => void stop()}>
                  Stop
                </button>
              </div>
              {note ? <div className="live-note">{note}</div> : null}
              {progress.length > 0 ? (
                <ul className="live-feed mono">
                  {progress.slice(-8).map((t, i) => (
                    <li key={progress.length - 8 + i}>
                      <span className="trace-tool">{t.tool}</span> {inputSummary(t.input)}
                    </li>
                  ))}
                </ul>
              ) : null}
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
            disabled={status?.available !== true || running}
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
