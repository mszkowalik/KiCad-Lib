/** Where a device has been: produced in a batch, shipped on an order, back
 *  for repair, replaced, disposed of. The log is append-only and the newest
 *  event is the state (decision 0003 §5). The three actions here are the
 *  three things that happen to a device after it leaves: it comes back, it
 *  gets repaired (to stock or to the bin), or it is disposed of. Shipping it
 *  again is done from the order.
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  disposeDevice,
  errorMessage,
  getDeviceHistory,
  isAbortError,
  listOrders,
  repairDevice,
  returnDevice,
  type DeviceEventRow,
  type DeviceHistory,
  type OrderRow,
} from "../api";
import { useDialog } from "./Dialog";
import { ErrorBanner, Spinner, StatusPill } from "./Ui";
import { fmtWhen } from "./flasher/common";
import { amount } from "../format";

const STATE_LABEL: Record<string, string> = {
  "": "unrecorded",
  in_stock: "on the shelf",
  allocated: "reserved",
  shipped: "at the customer",
  returned: "back for repair",
  disposed: "disposed of",
};

function describe(ev: DeviceEventRow): string {
  switch (ev.kind) {
    case "produced":
      return `passed programming in ${ev.production_run ?? `batch #${ev.production_run_id}`}`;
    case "allocated":
      return `reserved for ${ev.customer ?? "an order"}${ev.order_ref ? ` · ${ev.order_ref}` : ""}`;
    case "shipped":
      return (
        `shipped to ${ev.customer ?? "an order"}${ev.order_ref ? ` · ${ev.order_ref}` : ""}` +
        (ev.replaces_device_id
          ? ev.replaces_serial
            ? ` as a replacement for ${ev.replaces_serial}`
            : " again after repair"
          : "") +
        (ev.auto ? " (picked oldest-first)" : "")
      );
    case "unshipped":
      return "taken off a shipment — a return corrected the oldest-first guess";
    case "returned":
      return `came back from ${ev.customer ?? "the customer"}${ev.reason ? ` · ${ev.reason}` : ""}`;
    case "repaired":
      return ev.cost_lines.length
        ? `repaired · ${ev.cost_lines.map((c) => `${c.kind} ${amount(c.amount * c.qty, c.currency)}`).join(", ")}`
        : "repaired";
    case "disposed":
      return `disposed of${ev.reason ? ` · ${ev.reason}` : ""}`;
    default:
      return ev.kind;
  }
}

export default function DeviceHistoryCard({ deviceId, serial }: { deviceId: number; serial: string }) {
  const [hist, setHist] = useState<DeviceHistory | null>(null);
  const [error, setError] = useState<string | null>(null);
  const dialog = useDialog();

  const reload = useCallback(() => {
    const ac = new AbortController();
    getDeviceHistory(deviceId, ac.signal)
      .then((h) => {
        setHist(h);
        setError(null);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [deviceId]);

  useEffect(() => reload(), [reload]);

  const run = async (work: () => Promise<DeviceHistory>) => {
    try {
      setHist(await work());
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "That did not work" });
    }
  };

  const onReturn = async () => {
    // Which order? The last shipment's, unless the device was never assigned.
    let lineId: number | null = null;
    const lastShip = [...(hist?.events ?? [])].reverse().find((e) => e.kind === "shipped");
    if (!lastShip || hist?.state !== "shipped") {
      let orders: OrderRow[] = [];
      try {
        orders = await listOrders();
      } catch (err) {
        await dialog.alert(errorMessage(err));
        return;
      }
      const options = orders.flatMap((o) =>
        o.lines.map((l) => ({
          value: String(l.id),
          label: `${o.customer}${o.order_ref ? ` · ${o.order_ref}` : ""} · ${l.product || l.project} (${o.order_date})`,
        })),
      );
      if (!options.length) {
        await dialog.alert("There is no order to return this device against.");
        return;
      }
      const v = await dialog.select("Which order did it come back from?", options, { title: "Return" });
      if (v == null) return;
      lineId = Number(v);
    }
    const reason = await dialog.prompt("Why did it come back?", { title: "Return", initial: "faulty" });
    if (reason == null) return;
    await run(() => returnDevice(deviceId, { order_line_id: lineId, reason: reason.trim() }));
  };

  const onRepair = async () => {
    const outcome = await dialog.select(
      "What happened to it?",
      [
        { value: "to_stock", label: "Repaired — back on the shelf" },
        { value: "dispose", label: "Unrepairable — disposed of" },
      ],
      { title: "Repair" },
    );
    if (outcome == null) return;
    const cost = await dialog.prompt("Material cost, net (blank = none):", { title: "Repair cost", initial: "0" });
    if (cost == null) return;
    const n = Number(cost.trim() || 0);
    await run(() =>
      repairDevice(deviceId, {
        outcome: outcome as "to_stock" | "dispose",
        cost_lines: n > 0 ? [{ kind: "material", amount: n, currency: "PLN" }] : [],
      }),
    );
  };

  const onDispose = async () => {
    const reason = await dialog.prompt("Reason:", { title: "Dispose of the device", initial: "scrap" });
    if (reason == null) return;
    await run(() => disposeDevice(deviceId, { reason: reason.trim() }));
  };

  const state = hist?.state ?? "";
  return (
    <div className="card pad">
      <div className="toolbar">
        <h2 className="card-title">Where it is</h2>
        {hist ? <StatusPill status={STATE_LABEL[state] ?? state} /> : null}
        <span className="toolbar-total">
          {hist?.production_run ? (
            <>
              batch <Link className="val-link" to={`/runs/${hist.production_run_id}`}>{hist.production_run}</Link>
            </>
          ) : hist ? (
            "batch not recorded"
          ) : null}
        </span>
      </div>
      {error ? <ErrorBanner message={error} /> : null}
      {!hist ? (
        <Spinner />
      ) : hist.events.length === 0 ? (
        <p className="muted">
          No history yet: {serial} predates device records. Link it to its batch from the batch
          page, or record its return against an order and it will name one unserialized unit.
        </p>
      ) : (
        <div className="table-wrap">
          <table className="data data-fixed device-history-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Event</th>
                <th>What</th>
                <th>Order</th>
                <th>By</th>
              </tr>
            </thead>
            <tbody>
              {hist.events.map((ev) => (
                <tr key={ev.id}>
                  <td className="muted" title={ev.at ?? ""}>{fmtWhen(ev.at)}</td>
                  <td>{ev.kind}</td>
                  <td title={`${describe(ev)}${ev.note ? ` — ${ev.note}` : ""}`}>{describe(ev)}</td>
                  <td>
                    {ev.order_id ? (
                      <Link className="val-link" to={`/production/orders/${ev.order_id}`}>
                        {ev.order_ref || `order #${ev.order_id}`}
                      </Link>
                    ) : "—"}
                  </td>
                  <td>{ev.actor || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {hist ? (
        <div className="btn-row">
          {state !== "returned" && state !== "disposed" ? (
            <button type="button" className="btn btn-sm" onClick={onReturn}>It came back…</button>
          ) : null}
          {state === "returned" ? (
            <button type="button" className="btn btn-primary btn-sm" onClick={onRepair}>Repair outcome…</button>
          ) : null}
          {state === "returned" || state === "in_stock" ? (
            <button type="button" className="btn btn-danger btn-sm" onClick={onDispose}>Dispose of it…</button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
