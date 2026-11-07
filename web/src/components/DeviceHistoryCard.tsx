/** Where a device has been: produced in a batch, shipped on an order, back
 *  for repair, replaced, disposed of. The log is append-only and the newest
 *  event is the state (decision 0003 §5). The actions here are what happens to
 *  a device after it leaves — it comes back, it gets repaired (to stock or to
 *  the bin), it is disposed of — and what a stock count finds (decision 0057):
 *  a unit on the shelf that is not there is MISSING, a missing unit can be
 *  FOUND, and a unit on the shelf that a delivery lists NEVER LEFT on it.
 *  Shipping it, missing or not, is done from the order.
 */
import { Link } from "react-router-dom";
import {
  disposeDevice,
  errorMessage,
  getDeviceHistory,
  listOrders,
  markDeviceFound,
  markDeviceMissing,
  repairDevice,
  returnDevice,
  unshipDevice,
  type DeviceEventRow,
  type DeviceHistory,
  type OrderRow,
} from "../api";
import DataTable from "./DataTable";
import FoldSection, { StatChip } from "./FoldSection";
import { useDialog } from "./Dialog";
import { ErrorBanner, Spinner, StatusPill } from "./Ui";
import { amount, localWhen } from "../format";
import { useLoad } from "./useLoad";

const STATE_LABEL: Record<string, string> = {
  "": "unrecorded",
  in_stock: "on the shelf",
  allocated: "reserved",
  shipped: "at the customer",
  returned: "back for repair",
  disposed: "disposed of",
  missing: "missing — not found at a count",
};

function describe(ev: DeviceEventRow): string {
  switch (ev.kind) {
    case "produced":
      return `passed programming in ${ev.production_run ?? `batch #${ev.production_run_id}`}`;
    case "allocated":
      return ev.shipment_id
        ? `packed into shipment #${ev.shipment_id} for ${ev.customer ?? "an order"}${ev.order_ref ? ` · ${ev.order_ref}` : ""}`
        : `reserved for ${ev.customer ?? "an order"}${ev.order_ref ? ` · ${ev.order_ref}` : ""}`;
    case "unallocated":
      return ev.shipment_id
        ? `taken out of shipment #${ev.shipment_id}${ev.note ? ` · ${ev.note}` : ""} — back in stock`
        : `released from ${ev.customer ?? "an order"}${ev.order_ref ? ` · ${ev.order_ref}` : ""} — back in stock`;
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
      return `taken off shipment #${ev.shipment_id ?? "?"} — it never left on it`;
    case "missing":
      return "not found at a stock count";
    case "found":
      return "found again — back on the shelf";
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

/** Events that left the device off the normal path: first in the folded header. */
const EVENT_PROBLEM = new Set(["returned", "disposed", "missing"]);

export default function DeviceHistoryCard({ deviceId, serial }: { deviceId: number; serial: string }) {
  const { data: hist, setData: setHist, error } = useLoad(
    (signal) => getDeviceHistory(deviceId, signal),
    [deviceId],
    { keep: true },
  );
  const dialog = useDialog();

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

  const onMissing = async () => {
    const note = await dialog.prompt(
      "It is recorded on the shelf and the count did not find it. Note:",
      { title: "Not found at a stock count", initial: "not found at the stock count" },
    );
    if (note == null) return;
    await run(() => markDeviceMissing(deviceId, { note: note.trim() }));
  };

  const onFound = async () => {
    const note = await dialog.prompt("Where was it?", { title: "Found it", initial: "found on the shelf" });
    if (note == null) return;
    await run(() => markDeviceFound(deviceId, { note: note.trim() }));
  };

  const onNeverLeft = async () => {
    // Ask the server which delivery it would come off before anything moves.
    let shipmentId: number | null;
    try {
      shipmentId = (await unshipDevice(deviceId, { dry_run: true })).shipment_id;
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "That did not work" });
      return;
    }
    const ok = await dialog.confirm(
      `Take ${serial} off shipment #${shipmentId}? It goes back on the shelf. `
        + "Every other device on that shipment stays shipped.",
      { title: "It never left", confirmLabel: "Take it off" },
    );
    if (!ok) return;
    await run(() => unshipDevice(deviceId, { shipment_id: shipmentId, dry_run: false }));
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
              batch <Link className="val-link" to={`/production/batches/${hist.production_run_id}`}>{hist.production_run}</Link>
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
          page, or record its return against the order it was delivered on.
        </p>
      ) : (
        <FoldSection
          bare
          title="History"
          count={hist.events.length}
          foldKey={`device:${deviceId}:events`}
          chips={[...new Set(hist.events.map((ev) => ev.kind))]
            .sort((a, b) => Number(EVENT_PROBLEM.has(b)) - Number(EVENT_PROBLEM.has(a)))
            .slice(0, 4)
            .map((kind) => (
              <StatChip key={kind} n={hist.events.filter((ev) => ev.kind === kind).length}
                tone={EVENT_PROBLEM.has(kind) ? "warn" : undefined}>
                {kind}
              </StatChip>
            ))}
        >
        <div className="table-wrap">
          <DataTable
            rows={hist.events}
            rowKey={(ev) => ev.id}
            columns={[
              { key: "at", label: "When", width: "132px", className: "muted", get: (ev) => ev.at ?? "",
                title: (ev) => ev.at ?? "", render: (ev) => localWhen(ev.at) },
              { key: "kind", label: "Event", width: 16, get: (ev) => ev.kind },
              { key: "what", label: "What", width: 48, get: (ev) => describe(ev),
                title: (ev) => `${describe(ev)}${ev.note ? ` — ${ev.note}` : ""}` },
              { key: "order", label: "Order", width: 18, get: (ev) => ev.order_ref || (ev.order_id ? `order #${ev.order_id}` : ""),
                render: (ev) => (ev.order_id ? (
                  <Link className="val-link" to={`/sales/orders/${ev.order_id}`}>
                    {ev.order_ref || `order #${ev.order_id}`}
                  </Link>
                ) : "—") },
              { key: "by", label: "By", width: 18, get: (ev) => ev.actor || "—" },
            ]}
          />
        </div>
        </FoldSection>
      )}
      {hist ? (
        <div className="btn-row">
          {state !== "returned" && state !== "disposed" && state !== "missing" ? (
            <button type="button" className="btn btn-sm" onClick={onReturn}>It came back…</button>
          ) : null}
          {state === "shipped" ? (
            <button type="button" className="btn btn-sm" onClick={onNeverLeft}>It never left…</button>
          ) : null}
          {state === "in_stock" ? (
            <button type="button" className="btn btn-sm" onClick={onMissing}>Not found at a count…</button>
          ) : null}
          {state === "missing" ? (
            <button type="button" className="btn btn-primary btn-sm" onClick={onFound}>Found it…</button>
          ) : null}
          {state === "returned" ? (
            <button type="button" className="btn btn-primary btn-sm" onClick={onRepair}>Repair outcome…</button>
          ) : null}
          {state === "returned" || state === "in_stock" || state === "missing" ? (
            <button type="button" className="btn btn-danger btn-sm" onClick={onDispose}>Dispose of it…</button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
