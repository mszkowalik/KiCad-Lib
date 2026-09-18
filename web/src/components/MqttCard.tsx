/** The fleet MQTT broker: credential, watcher health, and the devices it found
 *  that the platform does not know about.
 *
 *  ADMIN ONLY, and the card is rendered only for an admin — the API answers
 *  403 either way, so showing it to anyone else would only display controls
 *  that can only fail.
 *
 *  THE PASSWORD IS WRITE-ONLY. The API never returns it, so the field starts
 *  empty and an empty field means "leave the stored one alone". That is why
 *  clearing a credential needs its own button: a blank input cannot mean both
 *  "unchanged" and "delete".
 */
import { useCallback, useEffect, useState } from "react";
import {
  errorMessage,
  getMqttStatus,
  getMacMismatches,
  getMqttUnlinked,
  isAbortError,
  linkMqttDevices,
  saveMqttConfig,
  type MacMismatchRow,
  type MqttStatusPayload,
  type MqttUnlinkedRow,
} from "../api";
import { useDialog } from "./Dialog";
import { ErrorBanner, Spinner } from "./Ui";
import { fmtWhen } from "./flasher/common";

export default function MqttCard() {
  const dialog = useDialog();
  const [status, setStatus] = useState<MqttStatusPayload | null>(null);
  const [unlinked, setUnlinked] = useState<MqttUnlinkedRow[] | null>(null);
  const [mismatches, setMismatches] = useState<MacMismatchRow[] | null>(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  // Form state, seeded from the server once loaded.
  const [enabled, setEnabled] = useState(false);
  const [host, setHost] = useState("");
  const [port, setPort] = useState(8883);
  const [tls, setTls] = useState(true);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [flushS, setFlushS] = useState(15);

  const load = useCallback((signal?: AbortSignal) => {
    getMqttStatus(signal)
      .then((s) => {
        setStatus(s);
        setEnabled(s.configured.enabled);
        setHost(s.configured.host);
        setPort(s.configured.port);
        setTls(s.configured.tls);
        setUsername(s.configured.username);
        setFlushS(s.configured.flush_s);
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

  const save = async () => {
    setBusy(true);
    try {
      const r = await saveMqttConfig({
        enabled,
        host,
        port,
        tls,
        username,
        flush_s: flushS,
        // Omitted entirely when blank — see the file comment.
        ...(password ? { password } : {}),
      });
      setPassword("");
      setNote(
        r.restart_required
          ? "Saved. The watcher reads its credential once at startup, so restart the API to apply this."
          : "Saved.",
      );
      load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const clearPassword = async () => {
    const ok = await dialog.confirm(
      "Remove the stored broker password? The watcher cannot connect without it.",
    );
    if (!ok) return;
    setBusy(true);
    try {
      await saveMqttConfig({ password: "" });
      setNote("Broker password removed.");
      load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const showUnlinked = async () => {
    try {
      const r = await getMqttUnlinked();
      setUnlinked(r.items);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const showMismatches = async () => {
    try {
      setMismatches((await getMacMismatches()).items);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const relink = async () => {
    setBusy(true);
    try {
      const r = await linkMqttDevices();
      setNote(
        `Linked ${r.linked} presence row(s); filled ${r.macs_filled} missing MAC(s). ` +
          "An existing MAC is never overwritten.",
      );
      setUnlinked(null);
      load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const m = status?.monitor;

  return (
    <div className="card pad">
      <div className="toolbar">
        <h2 className="card-title">Fleet MQTT broker</h2>
        {m ? (
          <span className={`pill ${m.connected ? "ok" : m.enabled ? "err" : ""}`}>
            {m.connected ? "connected" : m.enabled ? "disconnected" : "off"}
          </span>
        ) : null}
        <span className="toolbar-total">{m?.host ?? ""}</span>
      </div>

      <p className="muted">
        A read-only watcher that keeps each device&apos;s online state, last-seen time, ESP32
        temperature and inverter configuration current. It subscribes to four leaf topics and
        never publishes, so it sends no commands to any device. The credential is stored
        encrypted and is never shown again.
      </p>

      {error ? <ErrorBanner message={error} /> : null}
      {note ? <p className="muted dim">{note}</p> : null}

      {status === null ? (
        <Spinner label="Loading broker status…" />
      ) : (
        <>
          <table className="data data-fixed identity-table">
            <tbody>
              <tr>
                <td className="muted">Devices on the broker</td>
                <td className="mono">{status.topics.toLocaleString()}</td>
              </tr>
              <tr>
                <td className="muted">Online now</td>
                <td className="mono">
                  {status.online.toLocaleString()} online · {status.offline.toLocaleString()} offline
                </td>
              </tr>
              <tr>
                <td className="muted">Not in the platform</td>
                <td className="mono">
                  {status.unlinked.toLocaleString()}{" "}
                  {status.unlinked > 0 ? (
                    <button type="button" className="btn btn-sm" onClick={showUnlinked}>
                      show
                    </button>
                  ) : null}
                </td>
              </tr>
              <tr>
                <td className="muted">MAC disagreements</td>
                <td className="mono">
                  {status.mac_mismatches.toLocaleString()}{" "}
                  {status.mac_mismatches > 0 ? (
                    <button type="button" className="btn btn-sm" onClick={showMismatches}>
                      show
                    </button>
                  ) : null}
                </td>
              </tr>
              {m ? (
                <>
                  <tr>
                    <td className="muted">Messages / rows written</td>
                    <td className="mono">
                      {m.messages.toLocaleString()} / {m.flushed.toLocaleString()}
                    </td>
                  </tr>
                  <tr>
                    <td className="muted">Last message</td>
                    <td className="mono">{fmtWhen(m.last_message_at)}</td>
                  </tr>
                  <tr>
                    <td className="muted">Watching</td>
                    <td className="mono">{m.subscriptions.join(", ") || "—"}</td>
                  </tr>
                  {m.errors > 0 || m.last_error ? (
                    <tr>
                      <td className="muted">Errors</td>
                      <td className="mono">
                        {m.errors} {m.last_error ? `— ${m.last_error}` : ""}
                      </td>
                    </tr>
                  ) : null}
                </>
              ) : null}
            </tbody>
          </table>

          {mismatches && mismatches.length > 0 ? (
            <>
              <p className="muted dim">
                The programmed MAC disagrees with what the broker says. Nothing is changed
                automatically — a disagreement usually means a swapped board or a configuration
                restored onto different hardware, and picking a side would destroy the evidence.
              </p>
              <div className="table-wrap">
                <table className="data data-fixed">
                  <thead>
                    <tr>
                      <th>Device</th>
                      <th>Topic</th>
                      <th>Programmed</th>
                      <th>Broker says</th>
                      <th>Evidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {mismatches.map((r) => (
                      <tr key={r.device_id}>
                        <td className="mono">#{r.device_id}</td>
                        <td className="mono">{r.topic}</td>
                        <td className="mono">{r.programmed_mac}</td>
                        <td className="mono">{r.broker_mac}</td>
                        <td className="muted">
                          {r.source === "device_report"
                            ? `the device reported it (${r.reported_mac_field})`
                            : "encoded in its topic"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : null}

          {unlinked ? (
            <div className="table-wrap">
              <table className="data data-fixed">
                <thead>
                  <tr>
                    <th>Topic</th>
                    <th>Broker</th>
                    <th>Inverter</th>
                    <th>Firmware</th>
                    <th>Last heard</th>
                  </tr>
                </thead>
                <tbody>
                  {unlinked.map((r) => (
                    <tr key={r.topic}>
                      <td className="mono">{r.topic}</td>
                      <td>
                        <span className={`pill ${r.online ? "ok" : "err"}`}>
                          {r.online ? "online" : "offline"}
                        </span>
                      </td>
                      <td className="mono">{r.inverter || "—"}</td>
                      <td className="mono">{r.dongle_version || "—"}</td>
                      <td className="muted">{fmtWhen(r.last_seen_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}

          <h3>Connection</h3>
          {/* The `kv settings-table` pattern the Setup page uses — this card
              invents no form layout of its own. */}
          <table className="kv settings-table">
            <tbody>
              <tr>
                <td>
                  <div>Watch the broker</div>
                  <div className="muted">Subscribe and keep device presence current.</div>
                </td>
                <td>
                  <label className="muted">
                    <input
                      type="checkbox"
                      checked={enabled}
                      onChange={(e) => setEnabled(e.target.checked)}
                    />{" "}
                    enabled
                  </label>
                </td>
              </tr>
              <tr>
                <td><div>Host</div></td>
                <td>
                  <input
                    className="text mono"
                    value={host}
                    placeholder="broker.example.com"
                    onChange={(e) => setHost(e.target.value)}
                  />
                </td>
              </tr>
              <tr>
                <td><div>Port</div></td>
                <td>
                  <input
                    className="text mono"
                    type="number"
                    value={port}
                    onChange={(e) => setPort(Number(e.target.value))}
                  />
                </td>
              </tr>
              <tr>
                <td>
                  <div>TLS</div>
                  <div className="muted">
                    The certificate is NOT verified: the devices pin a fingerprint rather than
                    validating a chain, so the broker certificate is routinely left expired.
                  </div>
                </td>
                <td>
                  <label className="muted">
                    <input
                      type="checkbox"
                      checked={tls}
                      onChange={(e) => setTls(e.target.checked)}
                    />{" "}
                    use TLS
                  </label>
                </td>
              </tr>
              <tr>
                <td>
                  <div>Username</div>
                  <div className="muted">A fleet credential that can read every device topic.</div>
                </td>
                <td>
                  <input
                    className="text mono"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                  />
                </td>
              </tr>
              <tr>
                <td>
                  <div>
                    Password{" "}
                    {status.configured.password_set ? (
                      <span className="pill neutral">stored</span>
                    ) : null}
                  </div>
                  <div className="muted">
                    Never shown again. Leave blank to keep the stored one.
                  </div>
                </td>
                <td>
                  <input
                    className="text mono"
                    type="password"
                    value={password}
                    placeholder={status.configured.password_set ? "unchanged" : "not set"}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                </td>
              </tr>
              <tr>
                <td>
                  <div>Write interval (seconds)</div>
                  <div className="muted">
                    How often buffered messages reach Postgres, and so how stale the online
                    column may be. Minimum 5.
                  </div>
                </td>
                <td>
                  <input
                    className="text mono"
                    type="number"
                    value={flushS}
                    onChange={(e) => setFlushS(Number(e.target.value))}
                  />
                </td>
              </tr>
            </tbody>
          </table>

          <div className="btn-row">
            <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={save}>
              Save
            </button>
            <button type="button" className="btn btn-sm" disabled={busy} onClick={relink}>
              Re-link devices
            </button>
            {status.configured.password_set ? (
              <button type="button" className="btn btn-sm" disabled={busy} onClick={clearPassword}>
                Remove password
              </button>
            ) : null}
          </div>
          {status.configured.updated_at ? (
            <p className="muted dim">
              Last changed by {status.configured.updated_by || "—"} on{" "}
              {fmtWhen(status.configured.updated_at)}. The watcher reads its credential once at
              startup, so a change needs an API restart.
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}
