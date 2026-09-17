/** Pick the USB socket a station owns, by watching the agent's port list live.
 *
 *  WHY IT IS A WATCHER AND NOT A LIST. Every V2 dongle is the same CH340, and a
 *  `/dev/cu.*` name says nothing an operator recognises — so choosing the right
 *  row out of four identical ones is guesswork. Chrome's own port picker solved
 *  it by being open while you plug the device in: the row that APPEARS is the
 *  one in your hand. This does the same against the agent's list (user request
 *  2026-09-17), which is the only reason a static `dialog.select` was not
 *  enough.
 *
 *  So: it opens with no ports at all and says to plug one in, it polls while it
 *  is open, and anything that arrives after it opened is marked NEW and sorted
 *  to the top. Nothing is auto-assigned — appearing is a strong hint, not a
 *  decision, and two cables can arrive at once.
 */
import { useEffect, useRef, useState } from "react";
import { errorMessage } from "../../api";
import { listSerialPorts, type AgentPort } from "../../flasher/benchAgent";
import { ErrorBanner } from "../Ui";
import { useModal } from "../modal";

/** Often enough that plugging a cable in feels immediate, cheap enough to hold:
 *  one HTTP call and one `lsof` on the bench machine. */
const POLL_MS = 700;

export interface SocketPickerProps {
  /** Station being assigned, for the title. */
  stationName: string;
  /** Sockets other stations already own, so this one cannot steal them blind. */
  takenBy: Record<string, string>;
  onPick: (node: string) => void;
  onCancel: () => void;
}

export default function SocketPicker({ stationName, takenBy, onPick, onCancel }: SocketPickerProps) {
  const [ports, setPorts] = useState<AgentPort[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** What was already plugged in when this opened. Everything else is NEW. */
  const baseline = useRef<Set<string> | null>(null);
  const modal = useModal(onCancel, { active: true });

  useEffect(() => {
    let alive = true;
    const look = async () => {
      try {
        const found = await listSerialPorts();
        if (!alive) return;
        // The FIRST answer is the baseline, so a port that was already there
        // never flashes up as new — the whole point is to spot an arrival.
        if (baseline.current === null) baseline.current = new Set(found.map((p) => p.device));
        setPorts(found);
        setError(null);
      } catch (e) {
        if (alive) setError(errorMessage(e));
      }
    };
    void look();
    const t = window.setInterval(() => void look(), POLL_MS);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, []);

  const isNew = (device: string) => baseline.current !== null && !baseline.current.has(device);
  // Arrivals first, then by name: the row you just created is the one you want.
  const rows = [...(ports ?? [])].sort(
    (a, b) => Number(isNew(b.device)) - Number(isNew(a.device)) || a.device.localeCompare(b.device),
  );

  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card modal-card-mid" {...modal.cardProps}>
        <h2 className="card-title">Assign a socket to {stationName}</h2>
        <p className="card-subtitle">
          The list is live. <strong>Plug the device in now</strong> — the socket that appears is
          the one it is in, and it will jump to the top marked NEW. The station keeps that socket
          until it is freed, so the same cable always programs the same station.
        </p>
        {error ? <ErrorBanner message={error} /> : null}
        {ports === null ? (
          <p className="muted">Asking the bench agent…</p>
        ) : rows.length === 0 ? (
          <p className="muted">
            No USB serial ports on this machine yet. Plug one in and it will appear here.
          </p>
        ) : (
          <div className="socket-list">
            {rows.map((p) => {
              const owner = takenBy[p.device];
              return (
                <button
                  key={p.device}
                  type="button"
                  className={`socket-row${isNew(p.device) ? " is-new" : ""}`}
                  onClick={() => onPick(p.device)}
                >
                  <span className="mono socket-node">{p.device}</span>
                  {isNew(p.device) ? <span className="pill ok">new</span> : null}
                  {owner ? <span className="pill warn">{owner}</span> : null}
                  {p.held_by ? <span className="pill neutral">open in {p.held_by}</span> : null}
                </button>
              );
            })}
          </div>
        )}
        <div className="btn-row modal-actions">
          <button type="button" className="btn" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
