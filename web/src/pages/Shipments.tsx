/** Production → Shipments: every delivery, and the boxes still being packed.
 *
 *  Decision record 0053. A shipment can be OPENED for one order before anything
 *  leaves; devices are scanned into it on `ShipmentDetail` and it is sent when
 *  the box is closed. The one-step Ship card on the order page stays for a
 *  delivery whose serials are all to hand.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  errorMessage,
  isAbortError,
  listOrders,
  listShipments,
  openShipment,
  type OrderRow,
  type ShipmentListRow,
} from "../api";
import DataTable, { type Column } from "../components/DataTable";
import Field, { FieldRow } from "../components/Field";
import { ErrorBanner, Spinner, StatusPill } from "../components/Ui";

export default function Shipments() {
  const [rows, setRows] = useState<ShipmentListRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const navigate = useNavigate();

  const reload = useCallback(() => {
    const ac = new AbortController();
    listShipments(undefined, ac.signal)
      .then((r) => {
        setRows(r);
        setError(null);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, []);
  useEffect(reload, [reload]);

  const columns: Column<ShipmentListRow>[] = useMemo(
    () => [
      { key: "id", label: "#", width: 6, numeric: true, get: (s) => s.id },
      {
        key: "status",
        label: "Status",
        width: 10,
        get: (s) => s.status,
        render: (s) => <StatusPill status={s.status} />,
      },
      { key: "order", label: "Order", width: 17, className: "mono", get: (s) => s.order_ref },
      { key: "customer", label: "Customer", width: 15, get: (s) => s.customer },
      { key: "products", label: "Products", width: 16, get: (s) => s.products.join(", ") },
      { key: "qty", label: "Devices", width: 8, numeric: true, get: (s) => s.qty },
      { key: "created", label: "Recorded", width: 10, className: "mono", get: (s) => (s.created_at ?? "").slice(0, 10) },
      { key: "shipped", label: "Sent", width: 10, className: "mono", get: (s) => s.shipped_at || "" },
      { key: "tracking", label: "Tracking", width: 8, get: (s) => s.tracking },
    ],
    [],
  );

  return (
    <div className="main-solo">
      <div className="page">
        <div className="toolbar">
          <h1>Shipments</h1>
          <span className="toolbar-total">
            {rows ? `${rows.filter((r) => r.status === "open").length} open · ${rows.length} in all` : ""}
          </span>
          <button type="button" className="btn btn-primary btn-sm" onClick={() => setCreating((v) => !v)}>
            {creating ? "Close" : "New shipment"}
          </button>
        </div>
        {error ? <ErrorBanner message={error} /> : null}
        {creating ? <NewShipmentCard onCreated={(id) => navigate(`/production/shipments/${id}`)} /> : null}
        <div className="card pad">
          <h2 className="card-title">Shipments</h2>
          <p className="muted dim">
            An open shipment is a box being packed: its devices are reserved and nothing has left.
            Click a row to scan devices into it or to send it.
          </p>
          {rows === null ? (
            <Spinner label="Loading shipments…" />
          ) : (
            <DataTable
              rows={rows}
              columns={columns}
              rowKey={(s) => s.id}
              group={(s) => (s.status === "open" ? 0 : 1)}
              defaultSort={{ key: "id", dir: "desc" }}
              onRowClick={(s) => navigate(`/production/shipments/${s.id}`)}
              persistKey="shipments"
              empty="No shipments yet."
            />
          )}
        </div>
      </div>
    </div>
  );
}

/** Open a box for one order. The order is chosen here and never changes. */
function NewShipmentCard({ onCreated }: { onCreated: (id: number) => void }) {
  const [orders, setOrders] = useState<OrderRow[] | null>(null);
  const [orderId, setOrderId] = useState("");
  const [note, setNote] = useState("");
  const [tracking, setTracking] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    listOrders(ac.signal)
      .then((os) => setOrders(os.filter((o) => !o.cancelled && o.status !== "fulfilled")))
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, []);

  const create = async () => {
    if (!orderId) {
      setError("Choose the order this box goes out on.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const sh = await openShipment({ order_id: Number(orderId), delivery_note: note.trim(), tracking: tracking.trim() });
      onCreated(sh.id);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <div className="card pad edit-card">
      <h2 className="card-title">New shipment</h2>
      {error ? <ErrorBanner message={error} /> : null}
      {orders === null ? (
        <Spinner label="Loading orders…" />
      ) : (
        <FieldRow>
          <Field label="Order" hint="Open and partly shipped orders only.">
            <select className="text" value={orderId} onChange={(e) => setOrderId(e.target.value)}>
              <option value="">—</option>
              {orders.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.order_ref} · {o.customer} · {o.lines.map((l) => `${l.qty_open} × ${l.project}`).join(", ")} open
                </option>
              ))}
            </select>
          </Field>
          <Field label="Delivery note">
            <input className="text" value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
          <Field label="Tracking">
            <input className="text" value={tracking} onChange={(e) => setTracking(e.target.value)} />
          </Field>
        </FieldRow>
      )}
      <div className="btn-row">
        <button type="button" className="btn btn-primary" disabled={busy || !orders} onClick={create}>
          {busy ? "Opening…" : "Open shipment"}
        </button>
      </div>
    </div>
  );
}
