import { useCallback, useEffect, useState } from "react";
import {
  checkJlcSession,
  clearJlcSession,
  errorMessage,
  getJlcSession,
  isAbortError,
  putJlcSession,
  type JlcSessionState,
} from "../../api";
import AutoTextarea from "../AutoTextarea";
import Field from "../Field";
import { ErrorBanner } from "../Ui";

/** An account page: logged out, the site sends the tab to its login page. A page
 *  of ours cannot read the cookies it sets, so a person copies them back. */
const JLC_LOGIN_URL = "https://jlcpcb.com/user-center/orders/";

/**
 * The JLCPCB browser session — the one thing only a human can supply.
 *
 * These endpoints have existed since the JLC work began and had no client
 * function at all, which is why "Sync from JLCPCB" could only ever fail into a
 * bare error banner: the fix was to paste cookies, and there was nowhere to
 * paste them.
 *
 * Presence and liveness are shown as SEPARATE facts. Stored cookies are not
 * working cookies — JLC answers 460 once the session dies, and it dies on its
 * own schedule — so "configured" is never rendered as "ok" on its own.
 */
export default function JlcSessionStrip({ onChange }: { onChange?: () => void }) {
  const [state, setState] = useState<JlcSessionState | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [paste, setPaste] = useState(false);
  const [cookies, setCookies] = useState("");
  const [live, setLive] = useState<"unknown" | "ok" | "dead">("unknown");
  const [detail, setDetail] = useState("");

  const load = useCallback((signal?: AbortSignal) => {
    getJlcSession(signal)
      .then((s) => {
        setState(s);
        setError("");
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
  }, []);

  useEffect(() => {
    const ac = new AbortController();
    load(ac.signal);
    return () => ac.abort();
  }, [load]);

  async function check() {
    setBusy("check");
    setDetail("");
    try {
      const r = await checkJlcSession();
      setLive(r.ok ? "ok" : "dead");
      setDetail(r.ok ? "" : r.error || "JLC rejected the session");
      load();
    } catch (err) {
      setLive("dead");
      setDetail(errorMessage(err));
    } finally {
      setBusy("");
    }
  }

  async function save() {
    setBusy("save");
    try {
      await putJlcSession(cookies, `pasted ${new Date().toISOString().slice(0, 10)}`);
      setCookies("");
      setPaste(false);
      setLive("unknown");
      load();
      onChange?.();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  }

  async function forget() {
    setBusy("forget");
    try {
      await clearJlcSession();
      setLive("unknown");
      load();
      onChange?.();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  }

  const configured = !!state?.configured;
  // The server's own verdict is used when the user has not pressed Check this
  // visit: the keep-alive is already probing every 20 minutes, so "configured"
  // alone understates what is known.
  const known = live !== "unknown" ? live : state?.died_at ? "dead" : state?.alive ? "ok" : "unknown";
  const tone = known === "ok" ? "ok" : known === "dead" ? "err" : configured ? "warn" : "neutral";
  const word =
    known === "ok" ? "verified" : known === "dead" ? "dead" : configured ? "configured" : "absent";

  return (
    /* `meta-card` alone has no appearance — it only sets `flex-shrink` — so this
       strip drew no box at all and its facts ran into the card below it. Every
       other call site in the app is `card pad meta-card`; this one and the JLC
       order rows were the two that were not (user report 2026-09-22). The
       FACTS and the ACTIONS are also two rows now: one `btn-row` put four dim
       measurements and three buttons on one line, so the buttons landed
       wherever the text happened to end. */
    <div className="card pad meta-card">
      <ErrorBanner message={error} />
      <div className="toolbar">
        <strong>JLCPCB session</strong>
        <span className={`pill ${tone}`}>{word}</span>
        {state?.last_ok_at && (
          <span className="muted dim">
            last worked {new Date(state.last_ok_at).toLocaleString()}
          </span>
        )}
        {state?.label && <span className="muted dim">· {state.label}</span>}
        {state?.age_hours != null && (
          <span
            className="muted dim"
            title={
              "How long this session has held. The 30-minute figure people quote is the " +
              "secretkey and XSRF-TOKEN, both of which the client renews by itself."
            }
          >
            · {state.age_hours}h old
          </span>
        )}
        {!!state?.keepalive_count && (
          <span
            className="muted dim"
            title="Successful keep-alive touches. A touch every 20 minutes cannot expire from idleness."
          >
            · {state.keepalive_count} keep-alive{state.keepalive_count === 1 ? "" : "s"}
          </span>
        )}
      </div>
      <div className="btn-row">
        <button className="btn btn-sm" disabled={!configured || busy === "check"} onClick={check}>
          {busy === "check" ? "checking…" : "Check"}
        </button>
        <a
          className="btn btn-sm"
          href={JLC_LOGIN_URL}
          target="_blank"
          rel="noopener noreferrer"
          onClick={() => setPaste(true)}
        >
          Log in at JLCPCB
        </a>
        <button className="btn btn-sm" onClick={() => setPaste((v) => !v)}>
          {configured ? "Re-paste cookies" : "Paste cookies"}
        </button>
        {configured && (
          <button
            className="btn btn-sm btn-danger"
            disabled={busy === "forget"}
            onClick={forget}
            title="Delete the stored cookies. Nothing else is affected."
          >
            Forget
          </button>
        )}
      </div>

      {known === "dead" && (
        <div className="banner-warn">
          The stored session no longer works
          {detail || state?.last_error ? ` — ${detail || state?.last_error}` : ""}
          {state?.died_at && state?.updated_at
            ? `. It held for ${(
                (new Date(state.died_at).getTime() - new Date(state.updated_at).getTime()) /
                3_600_000
              ).toFixed(1)}h`
            : ""}
          . Henry cannot log in to JLC by itself. Press Log in at JLCPCB to start a new session.
        </div>
      )}

      {paste && (
        <div className="edit-card">
          <ol className="muted">
            <li>Log in at JLCPCB in the other tab.</li>
            <li>In that tab, open DevTools (⌥⌘I), then Network, and reload the page.</li>
            <li>
              Right-click the first request (<code>orders/</code>), then Copy → Copy as cURL.
            </li>
            <li>Paste it here.</li>
          </ol>
          <p className="muted dim">
            Henry also reads a <code>Cookie:</code> header, or the value of{" "}
            <code>JLCPCB_SESSION_ID</code> from Application → Cookies. It takes only the cookies
            and tests them against JLCPCB. If JLCPCB refuses them, the stored session stays. They
            are stored encrypted, and no endpoint returns them.
          </p>
          <Field label="What you copied">
            <AutoTextarea
              className="text mono"
              rows={3}
              maxRows={8}
              placeholder="curl 'https://jlcpcb.com/user-center/orders/' …"
              value={cookies}
              onChange={(e) => setCookies(e.target.value)}
            />
          </Field>
          <div className="btn-row">
            <button
              className="btn btn-primary btn-sm"
              disabled={!cookies.trim() || busy === "save"}
              onClick={save}
            >
              {busy === "save" ? "testing…" : "Test and store"}
            </button>
            <button className="btn btn-sm" onClick={() => setPaste(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
