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
import { useEffect, useState } from "react";
import {
  errorMessage,
  getMqttStatus,
  getMacMismatches,
  getMqttUnlinked,
  linkMqttDevices,
  saveMqttConfig,
} from "../api";
import DataTable from "./DataTable";
import { useDialog } from "./Dialog";
import { CheckField } from "./Field";
import FoldSection, { StatChip } from "./FoldSection";
import NumberInput from "./NumberInput";
import { ErrorBanner, Spinner, StatusPill } from "./Ui";
import { localWhen } from "../format";
import { useLoad } from "./useLoad";

export default function MqttCard() {
  const dialog = useDialog();
  /** a relink changes who is unlinked: an open list reads it again */
  const [listTick, setListTick] = useState(0);
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

  const { data: status, error, setError, reload: load } = useLoad(
    (signal) =>
      getMqttStatus(signal).then((s) => {
        setEnabled(s.configured.enabled);
        setHost(s.configured.host);
        setPort(s.configured.port);
        setTls(s.configured.tls);
        setUsername(s.configured.username);
        setFlushS(s.configured.flush_s);
        return s;
      }),
    [],
  );

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

  const relink = async () => {
    setBusy(true);
    try {
      const r = await linkMqttDevices();
      setNote(
        `Linked ${r.linked} presence row(s); filled ${r.macs_filled} missing MAC(s). ` +
          "An existing MAC is never overwritten.",
      );
      setListTick((t) => t + 1);
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
        {m ? <StatusPill status={m.connected ? "connected" : m.enabled ? "disconnected" : "off"} /> : null}
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
                  {status.unlinked.toLocaleString()}
                </td>
              </tr>
              <tr>
                <td className="muted">MAC disagreements</td>
                <td className="mono">
                  {status.mac_mismatches.toLocaleString()}
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
                    <td className="mono">{localWhen(m.last_message_at)}</td>
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

          {status.mac_mismatches > 0 ? (
            <FoldSection bare title="MAC disagreements" count={status.mac_mismatches} foldKey="admin:mqtt:mismatches"
              chips={<StatChip n={status.mac_mismatches} tone="err">to check</StatChip>}>
              <MacMismatches tick={listTick} onError={setError} />
            </FoldSection>
          ) : null}

          {status.unlinked > 0 ? (
            <FoldSection bare title="Not in the platform" count={status.unlinked} foldKey="admin:mqtt:unlinked"
              chips={<StatChip n={status.unlinked} tone="warn">not linked</StatChip>}>
              <UnlinkedTopics total={status.unlinked} tick={listTick} onError={setError} />
            </FoldSection>
          ) : null}

          <h3>Connection</h3>
          {/* The `kv settings-table` pattern of Admin → Configuration: this card
              invents no form layout of its own. */}
          <table className="kv settings-table">
            <tbody>
              <tr>
                <td>
                  <div>Watch the broker</div>
                  <div className="muted">Subscribe and keep device presence current.</div>
                </td>
                <td>
                  <CheckField checked={enabled} onChange={setEnabled}>enabled</CheckField>
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
                  <NumberInput className="text mono" value={port} min={1} max={65535} onChange={setPort} />
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
                  <CheckField checked={tls} onChange={setTls}>use TLS</CheckField>
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
                  <NumberInput className="text mono" value={flushS} min={5} onChange={setFlushS} />
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
              {localWhen(status.configured.updated_at)}. The watcher reads its credential once at
              startup, so a change needs an API restart.
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}

/** The children of a fold render only while it is open, so these two lists are
 *  read then, and a closed one costs no request. */
function MacMismatches({ tick, onError }: { tick: number; onError: (message: string) => void }) {
  const { data: mismatches, error } = useLoad(
    (signal) => getMacMismatches(signal).then((r) => r.items),
    [tick],
    { keep: true },
  );
  useEffect(() => {
    if (error) onError(error);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [error]);
  if (!mismatches) return <Spinner label="Reading the disagreements…" />;
  return (
    <>
      <p className="muted dim">
        The programmed MAC disagrees with what the broker says. Nothing is changed
        automatically — a disagreement usually means a swapped board or a configuration
        restored onto different hardware, and picking a side would destroy the evidence.
      </p>
      <div className="table-wrap">
        <DataTable
          rows={mismatches}
          rowKey={(r) => r.device_id}
          columns={[
            { key: "device", label: "Device", width: 10, className: "mono", get: (r) => `#${r.device_id}` },
            { key: "topic", label: "Topic", width: 30, className: "mono", get: (r) => r.topic },
            { key: "programmed", label: "Programmed", width: 16, className: "mono", get: (r) => r.programmed_mac },
            { key: "broker", label: "Broker says", width: 16, className: "mono", get: (r) => r.broker_mac },
            { key: "evidence", label: "Evidence", width: 28, className: "muted",
              get: (r) => (r.source === "device_report"
                ? `the device reported it (${r.reported_mac_field})`
                : "encoded in its topic") },
          ]}
        />
      </div>
    </>
  );
}

function UnlinkedTopics({ total, tick, onError }: { total: number; tick: number; onError: (message: string) => void }) {
  const { data: unlinked, error } = useLoad(
    (signal) => getMqttUnlinked(signal).then((r) => r.items),
    [tick],
    { keep: true },
  );
  useEffect(() => {
    if (error) onError(error);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [error]);
  if (!unlinked) return <Spinner label="Reading the topics…" />;
  return (
    <div className="table-wrap">
      {unlinked.length < total ? <p className="muted dim">The server sends the first {unlinked.length} of {total} topics.</p> : null}
      <DataTable
        rows={unlinked}
        rowKey={(r) => r.topic}
        columns={[
          { key: "topic", label: "Topic", width: 30, className: "mono", get: (r) => r.topic },
          { key: "broker", label: "Broker", width: 10, get: (r) => (r.online ? "online" : "offline"),
            render: (r) => <StatusPill status={r.online ? "online" : "offline"} /> },
          { key: "inverter", label: "Inverter", width: 12, className: "mono", get: (r) => r.inverter || "—" },
          { key: "fw", label: "Firmware", width: 10, className: "mono", get: (r) => r.dongle_version || "—" },
          { key: "heard", label: "Last heard", width: 14, className: "muted", get: (r) => localWhen(r.last_seen_at) },
          // A row with candidates is still unlinked because its rules name different units.
          { key: "candidates", label: "Link rules that matched", width: 24, className: "mono",
            get: (r) => (r.candidates.length ? r.candidates.map((c) => `#${c.device_id} (${c.rule})`).join(", ") : "—") },
        ]}
      />
    </div>
  );
}
