/** What the fleet MQTT broker says about one device.
 *
 *  A DIFFERENT AXIS from the check grid beside it, and the card says so. The
 *  checks are history the bench proved and they cannot change; this is a live
 *  cache that is allowed to be stale, wrong or missing. Keeping the two apart
 *  is the whole point — a device that is "offline" is a device the broker has
 *  not heard from, which is not a claim that anything is broken.
 *
 *  THREE STATES, never two. `online: true` and `online: false` are the broker
 *  speaking; `presence === null` is the platform admitting it does not know.
 *  Collapsing "unknown" into "offline" would report every never-deployed shelf
 *  unit as a failure.
 */
import type { DevicePresence } from "../api";
import { fmtWhen } from "./flasher/common";

interface Props {
  presence: DevicePresence | null;
  /** The MAC the flasher recorded, to cross-check against the topic's. */
  mac: string;
}

/** "3 min ago" / "2 days ago" — how stale is this, at a glance. */
function ago(iso: string | null): string {
  if (!iso) return "never";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "never";
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 90) return `${secs}s ago`;
  const mins = Math.round(secs / 60);
  if (mins < 90) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

export default function DevicePresenceCard({ presence, mac }: Props) {
  if (presence === null) {
    return (
      <div className="card pad">
        <h2 className="card-title">Broker</h2>
        <p className="card-subtitle">
          <span className="pill">not seen</span> This device has never been heard on the MQTT
          broker.
        </p>
        <p className="muted dim">
          That is not a fault: a device that was never deployed has nothing to report, and the
          broker watcher may be switched off. It is not the same as being offline.
        </p>
      </div>
    );
  }

  const online = presence.online;
  const pill = online === true ? "ok" : online === false ? "err" : "";
  const word = online === true ? "online" : online === false ? "offline" : "unknown";

  // The broker's best MAC: the device's own report beats the topic, because a
  // topic is a configured string a restored backup can carry onto different
  // hardware. The platform NEVER overwrites a programmed MAC with either — a
  // disagreement is shown here and queued for an admin instead.
  const brokerMac = presence.reported_mac || presence.mac_from_topic;
  const brokerMacSource = presence.reported_mac
    ? `the device reported it (${presence.reported_mac_field || "status"})`
    : "encoded in its topic";
  const macMismatch =
    brokerMac !== "" && mac !== "" && brokerMac.toLowerCase() !== mac.toLowerCase();

  return (
    <div className="card pad">
      <h2 className="card-title">Broker</h2>
      <p className="card-subtitle">
        <span className={`pill ${pill}`}>{word}</span>{" "}
        {online === true
          ? `talking to the broker, last heard ${ago(presence.last_seen_at)}.`
          : online === false
            ? `the broker last heard from it ${ago(presence.last_seen_at)}.`
            : "the broker has a status for it that could not be read."}
      </p>
      <p className="muted dim">
        Live from MQTT, not from a programming run — it may be stale by up to the watcher&apos;s
        write interval.
      </p>

      <table className="data data-fixed identity-table">
        <tbody>
          <tr>
            <td className="muted">Topic</td>
            <td className="mono" title={presence.topic}>{presence.topic}</td>
          </tr>
          <tr>
            <td className="muted">Last heard</td>
            <td className="mono">{fmtWhen(presence.last_seen_at)}</td>
          </tr>
          <tr>
            <td className="muted">Last went online</td>
            <td className="mono">{fmtWhen(presence.last_online_at)}</td>
          </tr>
          {presence.last_offline_at ? (
            <tr>
              <td className="muted">Last went offline</td>
              <td className="mono">{fmtWhen(presence.last_offline_at)}</td>
            </tr>
          ) : null}
          <tr>
            <td className="muted">First heard</td>
            <td className="mono">{fmtWhen(presence.first_seen_at)}</td>
          </tr>
          {presence.temperature_c !== null ? (
            <tr>
              <td className="muted">ESP32 temperature</td>
              <td className="mono">
                {presence.temperature_c.toFixed(1)} °C{" "}
                <span className="muted dim">{ago(presence.temperature_at)}</span>
              </td>
            </tr>
          ) : null}
          {presence.wifi_ping_ms !== null ? (
            <tr>
              <td className="muted">WiFi ping</td>
              <td className="mono">{presence.wifi_ping_ms} ms</td>
            </tr>
          ) : null}
          {presence.inverter ? (
            <tr>
              <td className="muted">Inverter</td>
              <td className="mono">{presence.inverter}</td>
            </tr>
          ) : null}
          {presence.inverter_sn ? (
            <tr>
              <td className="muted">Inverter serial</td>
              <td className="mono" title={presence.inverter_sn}>{presence.inverter_sn}</td>
            </tr>
          ) : null}
          {presence.dongle_version ? (
            <tr>
              <td className="muted">Dongle firmware</td>
              <td className="mono">{presence.dongle_version}</td>
            </tr>
          ) : null}
          {brokerMac ? (
            <tr>
              <td className="muted">MAC per broker</td>
              <td className="mono" title={brokerMacSource}>
                {brokerMac}{" "}
                {macMismatch ? (
                  <span className="pill warn">differs from programmed</span>
                ) : null}
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>

      {macMismatch ? (
        <p className="muted dim">
          The MAC recorded during programming is <span className="mono">{mac}</span>, and the
          broker says <span className="mono">{brokerMac}</span> ({brokerMacSource}). The platform
          has changed nothing: a disagreement usually means a swapped board or a configuration
          restored onto different hardware, and it needs a person to decide.
        </p>
      ) : null}
    </div>
  );
}
