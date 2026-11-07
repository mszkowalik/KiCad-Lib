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
 *
 *  ONE UNIT, SEVERAL TOPICS. A bench reflash renames a device and the broker
 *  keeps the old name, so the card shows the main topic (online first, then the
 *  newest) and lists the others under "Other names" (decision 0056).
 */
import type { DevicePresence } from "../api";
import { since, localWhen } from "../format";
import DataTable from "./DataTable";
import FoldSection from "./FoldSection";
import { StatusPill } from "./Ui";

interface Props {
  presence: DevicePresence | null;
  /** The MAC the flasher recorded, to cross-check against the topic's. */
  mac: string;
}

/** "3 min ago" / "2 d ago" — how stale is this, at a glance. */
function ago(iso: string | null): string {
  const s = since(iso);
  return s ? `${s} ago` : "never";
}

export default function DevicePresenceCard({ presence, mac }: Props) {
  if (presence === null) {
    return (
      <div className="card pad">
        <h2 className="card-title">Broker</h2>
        <p className="muted">
          <StatusPill status="not seen" /> This device has never been heard on the MQTT broker.
        </p>
        <p className="muted dim">
          That is not a fault: a device that was never deployed has nothing to report, and the
          broker watcher may be switched off. It is not the same as being offline.
        </p>
      </div>
    );
  }

  const online = presence.online;
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
      <p className="muted">
        <StatusPill status={word} />{" "}
        {online === true
          ? presence.last_seen_at
            ? `talking to the broker, last heard ${ago(presence.last_seen_at)}.`
            : "the broker says it is connected."
          : online === false
            ? presence.last_seen_at
              ? `the broker last heard from it ${ago(presence.last_seen_at)}.`
              : "no live message from it is on record — the broker holds only its retained state."
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
            <td className="mono" title={presence.topic}>
              {presence.topic}{" "}
              {presence.current_name ? null : (
                <span className="pill warn">not the programmed name</span>
              )}
            </td>
          </tr>
          <tr>
            <td className="muted">Last heard</td>
            <td className="mono">{localWhen(presence.last_seen_at)}</td>
          </tr>
          <tr>
            <td className="muted">Last went online</td>
            <td className="mono">{localWhen(presence.last_online_at)}</td>
          </tr>
          {presence.last_offline_at ? (
            <tr>
              <td className="muted">Last went offline</td>
              <td className="mono">{localWhen(presence.last_offline_at)}</td>
            </tr>
          ) : null}
          <tr>
            <td className="muted">First heard</td>
            <td className="mono">{localWhen(presence.first_seen_at)}</td>
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

      {presence.other_topics.length > 0 ? (
        <FoldSection bare title="Other names" count={presence.other_topics.length} foldKey={`device:${mac}:other-topics`}>
          <p className="muted dim">
            The same unit under another topic. A bench reflash renames a device, and the broker
            keeps the old name with its last retained state.
          </p>
          <DataTable
            rows={presence.other_topics}
            rowKey={(t) => t.topic}
            columns={[
              { key: "topic", label: "Topic", width: 54, className: "mono", get: (t) => t.topic,
                render: (t) => (
                  <>
                    {t.topic}{" "}
                    {t.current_name ? <span className="pill neutral">programmed name</span> : null}
                  </>
                ) },
              { key: "broker", label: "Broker", width: 18,
                get: (t) => (t.online === true ? "online" : t.online === false ? "offline" : "unknown"),
                render: (t) => <StatusPill status={t.online === true ? "online" : t.online === false ? "offline" : "unknown"} /> },
              { key: "heard", label: "Last heard", width: 28, className: "mono", get: (t) => localWhen(t.last_seen_at) },
            ]}
          />
        </FoldSection>
      ) : null}

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
