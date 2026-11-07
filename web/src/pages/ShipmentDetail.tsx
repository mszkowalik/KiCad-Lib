/** One shipment — and, while it is OPEN, the packing station (decision 0053).
 *
 *  Two lists side by side. SCANNED holds every code the scanner typed, in this
 *  browser only; each one is checked against the box in the background, because
 *  a scanner reads faster than the server answers. IN THIS SHIPMENT is what the
 *  server holds: devices with an `allocated` event naming this box. The arrows
 *  move rows between them — → packs, ← takes out — and "Mark as sent" writes
 *  the `shipped` events.
 *
 *  The scan field takes a code and an Enter. A Zebra scanner in keyboard mode
 *  sends CR LF after the code, which arrives as Enter and then a second, empty
 *  Enter; an empty field is ignored, so the pair adds one row.
 *
 *  The scanned list is kept in `localStorage` per shipment, so a reload does not
 *  lose a half-scanned carton. Its check results are NOT kept — they are
 *  re-asked on load, because stock may have moved meanwhile.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  cancelShipment,
  checkShipmentCodes,
  deleteShipment,
  errorMessage,
  getShipment,
  markShipmentReplacement,
  packShipment,
  patchShipment,
  sendShipment,
  unpackShipment,
  type ShipmentCheck,
  type ShipmentDetail as Detail,
  type ShipmentDeviceRow,
  shipmentMosquittoPath,
} from "../api";
import DataTable, { type Column } from "../components/DataTable";
import { useDialog } from "../components/Dialog";
import Field, { FieldRow } from "../components/Field";
import FoldSection, { StatChip } from "../components/FoldSection";
import { ScanBox, useScanList, type Scan, type ScanBoxHandle } from "../components/ScanList";
import { BackLink, ErrorBanner, Spinner, StatusPill } from "../components/Ui";
import { localWhen, today, plural } from "../format";
import { useLoad } from "../components/useLoad";
import PageShell from "../components/PageShell";

export default function ShipmentDetail() {
  const { id: idParam } = useParams();
  const id = Number(idParam);
  const { data: sh, setData: setSh, error } = useLoad((signal) => getShipment(id, signal), [id], { keep: true });

  return (
    <PageShell>
      <BackLink to="/sales/shipments">← Shipments</BackLink>
      <div className="toolbar">
        <h1>Shipment #{id}</h1>
        {sh ? <StatusPill status={sh.status} /> : null}
        {sh ? (
          <a
            className="btn btn-sm"
            href={shipmentMosquittoPath(sh.id)}
            download
            title="Plaintext user:password file for the units in this shipment, each with its current MQTT account only — the file the client installs on their broker. Hash it with mosquitto_passwd -U before you deploy it."
          >
            MQTT accounts
          </a>
        ) : null}
      </div>
      {error ? <ErrorBanner message={error} /> : null}
      {!sh ? (
        error ? null : <Spinner label="Loading shipment…" />
      ) : (
        <>
          <HeaderCard sh={sh} />
          {sh.status === "open" ? (
            <>
              <PackCard sh={sh} onChange={setSh} />
              <SendCard sh={sh} onChange={setSh} />
            </>
          ) : (
            <ContentCard sh={sh} />
          )}
        </>
      )}
    </PageShell>
  );
}

function HeaderCard({ sh }: { sh: Detail }) {
  const open = sh.status === "open";
  const o = sh.order;
  const hereOf = (l: Detail["order"]["lines"][number]) => sh.per_line[String(l.id)] ?? 0;
  const over = (l: Detail["order"]["lines"][number]) => open && hereOf(l) > l.qty_open;
  const columns: Column<Detail["order"]["lines"][number]>[] = [
    { key: "line", label: "Line", width: 40, get: (l) => l.product || l.project },
    { key: "ordered", label: "Ordered", width: 15, numeric: true, get: (l) => l.qty_ordered, render: (l) => <>{l.qty_ordered.toLocaleString()}</> },
    { key: "shipped", label: "Shipped", width: 15, numeric: true, get: (l) => l.qty_shipped, render: (l) => <>{l.qty_shipped.toLocaleString()}</> },
    { key: "open", label: "Open", width: 15, numeric: true, get: (l) => l.qty_open, render: (l) => <>{l.qty_open.toLocaleString()}</> },
    {
      key: "here",
      label: open ? "In this box" : "On this shipment",
      width: 15,
      numeric: true,
      get: hereOf,
      title: (l) => (over(l) ? "More devices in the box than the line has open" : undefined),
      render: (l) => <span className={over(l) ? "warn-text" : undefined}>{hereOf(l).toLocaleString()}</span>,
    },
  ];
  return (
    <div className="card pad">
      <h2 className="card-title">
        <Link to={`/sales/orders/${o.id}`}>{o.order_ref}</Link> · {o.customer}
      </h2>
      <DataTable rows={o.lines} rowKey={(l) => l.id} columns={columns} empty="This order has no lines." />
      {open ? null : (
        <dl className="kv">
          <dt>Sent on</dt>
          <dd className="mono">{sh.shipped_at || "—"}</dd>
          <dt>Delivery note</dt>
          <dd>{sh.delivery_note || "—"}</dd>
          <dt>Tracking</dt>
          <dd>{sh.tracking || "—"}</dd>
          {sh.notes ? (
            <>
              <dt>Notes</dt>
              <dd>{sh.notes}</dd>
            </>
          ) : null}
        </dl>
      )}
    </div>
  );
}

/** The last step: the paperwork, and closing the box. */
function SendCard({ sh, onChange }: { sh: Detail; onChange: (s: Detail) => void }) {
  const dialog = useDialog();
  const navigate = useNavigate();
  const [note, setNote] = useState(sh.delivery_note);
  const [tracking, setTracking] = useState(sh.tracking);
  const [notes, setNotes] = useState(sh.notes);
  const [date, setDate] = useState(today);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setNote(sh.delivery_note);
    setTracking(sh.tracking);
    setNotes(sh.notes);
  }, [sh.delivery_note, sh.tracking, sh.notes]);
  const dirty = note !== sh.delivery_note || tracking !== sh.tracking || notes !== sh.notes;

  const run = async (w: () => Promise<Detail | void>) => {
    setBusy(true);
    setError(null);
    try {
      const r = await w();
      if (r) onChange(r);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card pad">
      <h2 className="card-title">Send</h2>
      {error ? <ErrorBanner message={error} /> : null}
      <FieldRow>
        <Field label="Delivery note">
          <input className="text" value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        <Field label="Tracking">
          <input className="text" value={tracking} onChange={(e) => setTracking(e.target.value)} />
        </Field>
        <Field label="Sent on">
          <input className="text mono" value={date} onChange={(e) => setDate(e.target.value)} />
        </Field>
        <Field label="Notes" wide>
          <input className="text" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
      </FieldRow>
      <div className="btn-row">
        <button type="button" className="btn btn-sm" disabled={busy || !dirty}
                onClick={() => run(() => patchShipment(sh.id, { delivery_note: note, tracking, notes }))}>
          Save
        </button>
        <button
          type="button"
          className="btn btn-primary"
          disabled={busy || sh.qty === 0}
          title={sh.qty === 0 ? "Pack at least one device first" : undefined}
          onClick={async () => {
            if (
              await dialog.confirm(
                `Mark this shipment as sent on ${date}? ${plural(sh.qty, "device")} are recorded as shipped to ${sh.order.customer}, and the box is closed.`,
                { confirmLabel: "Mark as sent" },
              )
            ) {
              await run(() => sendShipment(sh.id, { shipped_at: date.trim(), delivery_note: note, tracking }));
            }
          }}
        >
          Mark as sent
        </button>
        {sh.deletable ? (
          <button
            type="button"
            className="btn btn-danger"
            disabled={busy}
            onClick={async () => {
              if (await dialog.confirm("Delete this empty shipment?", { tone: "danger" })) {
                await run(async () => {
                  await deleteShipment(sh.id);
                  navigate("/sales/shipments");
                });
              }
            }}
          >
            Delete
          </button>
        ) : (
          <button
            type="button"
            className="btn btn-danger"
            disabled={busy}
            onClick={async () => {
              if (
                await dialog.confirm(
                  `Cancel this shipment? ${plural(sh.qty, "packed device")} go back to stock. The shipment stays in the list as cancelled.`,
                  { tone: "danger", confirmLabel: "Cancel shipment" },
                )
              ) {
                await run(() => cancelShipment(sh.id));
              }
            }}
          >
            Cancel shipment
          </button>
        )}
      </div>
    </div>
  );
}

/** A sent or cancelled shipment: what it carries, read-only. */
function ContentCard({ sh }: { sh: Detail }) {
  const columns: Column<ShipmentDeviceRow>[] = useMemo(
    () => [
      {
        key: "serial",
        label: "Serial",
        // The widths sum to 100 with the broker column and without it.
        width: sh.broker ? 28 : 40,
        className: "mono",
        get: (d) => d.serial || d.mac,
        render: (d) => <Link to={`/production/devices/${d.device_id}`}>{d.serial || d.mac}</Link>,
      },
      { key: "run", label: "Batch", width: sh.broker ? 12 : 20, numeric: true, get: (d) => d.run_id ?? "" },
      { key: "state", label: "State now", width: sh.broker ? 20 : 40,
        get: (d) => (d.replaces_serial ? `${d.state}, replaces ${d.replaces_serial}` : d.state) },
      ...(sh.broker
        ? [{
            key: "broker",
            label: "Fleet broker since shipping",
            width: 40,
            get: (d: ShipmentDeviceRow) => d.broker?.heard_at ?? "",
            title: (d: ShipmentDeviceRow) =>
              d.broker ? `topic ${d.broker.topic}, counted after ${localWhen(d.broker.since)}` : "",
            render: (d: ShipmentDeviceRow) =>
              !d.broker?.heard_at
                ? <span className="muted">not heard</span>
                : d.broker.online
                  ? `online${d.broker.online_since ? ` since ${localWhen(d.broker.online_since)}` : ""}`
                  : `last heard ${localWhen(d.broker.heard_at)}`,
          } as Column<ShipmentDeviceRow>]
        : []),
    ],
    [sh.broker],
  );
  const returned = sh.devices.filter((d) => d.state === "returned").length;
  const disposed = sh.devices.filter((d) => d.state === "disposed").length;
  return (
    <FoldSection
      title="Devices"
      count={sh.devices.length}
      foldKey={`shipment:${sh.id}:devices`}
      chips={
        <>
          {sh.broker ? <StatChip n={sh.broker.heard} tone="ok">heard on the broker</StatChip> : null}
          {sh.broker && sh.broker.of > sh.broker.heard ? <StatChip n={sh.broker.of - sh.broker.heard} tone="warn">not heard</StatChip> : null}
          {returned ? <StatChip n={returned} tone="warn">returned</StatChip> : null}
          {disposed ? <StatChip n={disposed} tone="err">disposed</StatChip> : null}
        </>
      }
    >
      {sh.status === "cancelled" ? <p className="muted dim">Cancelled before it was sent. Its devices went back to stock.</p> : null}
      {sh.broker ? (
        <p className="muted">
          {sh.broker.heard} of {sh.broker.of} units heard on the fleet broker since they shipped. A unit leaves
          the bench with only its own account, so a unit heard here proves the client installed that account.
          {sh.broker.watching ? "" : " The broker monitor is not connected now, so this can be behind."}
        </p>
      ) : null}
      <DataTable rows={sh.devices} columns={columns} rowKey={(d) => d.device_id} empty="No device on this shipment." />
    </FoldSection>
  );
}

/** The packing station: scan field, SCANNED list, arrows, IN THIS SHIPMENT. */
type PackScan = Scan<ShipmentCheck>;

function PackCard({ sh, onChange }: { sh: Detail; onChange: (s: Detail) => void }) {
  const dialog = useDialog();
  const [error, setError] = useState<string | null>(null);
  const [left, setLeft] = useState<Set<string>>(new Set());
  const [right, setRight] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const box = useRef<ScanBoxHandle>(null);

  // A line only needs naming when two lines of the order carry the same product.
  const ambiguous = useMemo(() => {
    const seen = new Set<number>();
    return sh.order.lines.some((l) => (seen.has(l.project_id) ? true : (seen.add(l.project_id), false)));
  }, [sh.order.lines]);
  const [lineId, setLineId] = useState<number | null>(null);
  const list = useScanList<ShipmentCheck>({
    storageKey: `kicadlib:shipment-scan:${sh.id}`,
    check: (codes) => checkShipmentCodes(sh.id, codes, lineId),
    codeOf: (c) => c.code,
    isOk: (c) => c.ok,
    describe: (c) => (c.ok
      ? { tone: "ok", text: `${c.code} is ready for this box.` }
      : { tone: "err", text: `${c.code}: ${c.reason}. The next scan works.` }),
    taken: (c) => sh.devices.some((d) => d.serial === c),
  });
  const { scans } = list;

  const recheckAll = list.recheck;

  const ready = scans.filter((s) => s.check?.ok);
  const selectedReady = ready.filter((s) => left.has(s.code));

  const pack = async (rows: PackScan[]) => {
    const ids = rows.map((s) => s.check!.device_id!).filter(Boolean);
    if (!ids.length) return;
    setBusy(true);
    setError(null);
    try {
      const r = await packShipment(sh.id, ids, lineId);
      const gone = new Set(rows.map((s) => s.code));
      list.removeWhere((s) => gone.has(s.code));
      setLeft(new Set());
      onChange(r);
    } catch (err) {
      setError(errorMessage(err));
      recheckAll();
    } finally {
      setBusy(false);
      box.current?.focus();
    }
  };

  const unpack = async () => {
    const ids = [...right];
    if (!ids.length) return;
    setBusy(true);
    setError(null);
    try {
      const back = sh.devices.filter((d) => right.has(d.device_id)).map((d) => d.serial).filter(Boolean);
      const r = await unpackShipment(sh.id, ids);
      setRight(new Set());
      onChange(r);
      list.add(back, "scanned");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
      box.current?.focus();
    }
  };

  /** A scanner works in this prompt too: it types the code and Enter, and that is
   *  the answer. The scan box itself still never meets a dialog. */
  const askReplacement = async (d: ShipmentDeviceRow) => {
    const code = await dialog.prompt(
      `${d.serial || d.mac} replaces which device? Scan or type the serial of a device delivered on this order.`,
      { title: "Warranty replacement", confirmLabel: "Save" },
    );
    if (code?.trim()) await setReplacement(d, code.trim());
  };

  const setReplacement = async (d: ShipmentDeviceRow, code: string) => {
    setBusy(true);
    setError(null);
    try {
      onChange(await markShipmentReplacement(sh.id, d.device_id, code));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
      box.current?.focus();
    }
  };

  const scanCols: Column<PackScan>[] = [
    {
      key: "sel",
      label: (
        <input
          type="checkbox"
          checked={ready.length > 0 && selectedReady.length === ready.length}
          disabled={!ready.length}
          onChange={() => setLeft(selectedReady.length === ready.length ? new Set() : new Set(ready.map((s) => s.code)))}
          aria-label="Select every device that is ready"
        />
      ),
      width: 6,
      className: "ctr",
      interactive: false,
      get: () => "",
      render: (s) => (
        <input
          type="checkbox"
          checked={left.has(s.code)}
          disabled={!s.check?.ok}
          onChange={() =>
            setLeft((cur) => {
              const n = new Set(cur);
              if (n.has(s.code)) n.delete(s.code);
              else n.add(s.code);
              return n;
            })
          }
          aria-label={`Select ${s.code}`}
        />
      ),
    },
    { key: "code", label: "Scanned", width: 27, className: "mono", get: (s) => s.code },
    { key: "product", label: "Product", width: 23, get: (s) => s.check?.project ?? "" },
    {
      key: "result",
      label: "Check",
      width: 36,
      get: (s) => (s.state === "done" ? (s.check!.ok ? "ready" : s.check!.reason) : s.state),
      title: (s) => (s.state === "done" ? s.check!.reason || "ready to pack" : s.error),
      render: (s) =>
        s.state === "done" ? (
          s.check!.ok ? (
            <StatusPill status="ready" />
          ) : (
            <span className="err-text">{s.check!.reason}</span>
          )
        ) : s.state === "error" ? (
          <span className="err-text">{s.error}</span>
        ) : (
          <span className="muted">checking…</span>
        ),
    },
    {
      key: "x",
      label: "",
      width: 8,
      className: "ctr",
      interactive: false,
      get: () => "",
      render: (s) => (
        <button type="button" className="btn btn-sm" title="Remove from the scanned list"
                onClick={() => list.remove(s.code)}>
          ×
        </button>
      ),
    },
  ];

  const boxCols: Column<ShipmentDeviceRow>[] = [
    {
      key: "sel",
      label: (
        <input
          type="checkbox"
          checked={sh.devices.length > 0 && right.size === sh.devices.length}
          disabled={!sh.devices.length}
          onChange={() => setRight(right.size === sh.devices.length ? new Set() : new Set(sh.devices.map((d) => d.device_id)))}
          aria-label="Select every device in the shipment"
        />
      ),
      width: 6,
      className: "ctr",
      interactive: false,
      get: () => "",
      render: (d) => (
        <input
          type="checkbox"
          checked={right.has(d.device_id)}
          onChange={() =>
            setRight((cur) => {
              const n = new Set(cur);
              if (n.has(d.device_id)) n.delete(d.device_id);
              else n.add(d.device_id);
              return n;
            })
          }
          aria-label={`Select ${d.serial}`}
        />
      ),
    },
    {
      key: "serial",
      label: "Serial",
      width: "126px",
      className: "mono",
      get: (d) => d.serial || d.mac,
      title: (d) => (d.packed_at ? `Packed ${localWhen(d.packed_at)}` : undefined),
      render: (d) => <Link to={`/production/devices/${d.device_id}`}>{d.serial || d.mac}</Link>,
    },
    {
      key: "line",
      label: "Line",
      width: 36,
      get: (d) => {
        const l = sh.order.lines.find((x) => x.id === d.order_line_id);
        return l ? l.product || l.project : "";
      },
    },
    {
      // A warranty replacement does not count against the ordered quantity (decision 0003).
      key: "replaces",
      label: "Replaces",
      width: 56,
      interactive: false,
      get: (d) => d.replaces_serial ?? "",
      title: (d) => (d.replaces_serial ? `Goes out as the replacement of ${d.replaces_serial}` : undefined),
      render: (d) => (d.replaces_serial ? (
        <>
          <span className="mono">{d.replaces_serial}</span>{" "}
          <button type="button" className="linklike" disabled={busy} onClick={() => void setReplacement(d, "")}>clear</button>
        </>
      ) : (
        <button type="button" className="btn btn-sm" disabled={busy} onClick={() => void askReplacement(d)}>Replacement…</button>
      )),
    },
  ];

  const counts = {
    ready: ready.length,
    refused: scans.filter((s) => s.state === "done" && !s.check?.ok).length,
    checking: scans.filter((s) => s.state === "pending" || s.state === "checking").length,
  };

  return (
    <div className="card pad">
      <h2 className="card-title">Pack</h2>
      <p className="muted dim">
        Click the scan field and scan. Each code is added to <b>Scanned</b> and checked in the background.
        Select the ready ones and press → to put them in the shipment; ← takes devices back out to stock.
      </p>
      {error ? <ErrorBanner message={error} /> : null}
      <ScanBox ref={box} label="Scan" placeholder="scan a serial…" onScan={list.scan} onPaste={list.paste}
        notice={list.notice} hint="Enter adds the code. Pasting a list works too." />
      {ambiguous ? (
        <FieldRow>
          <Field label="Pack onto line" hint="Two lines of this order carry the same product.">
            <select className="text" value={lineId ?? ""} onChange={(e) => {
              setLineId(e.target.value ? Number(e.target.value) : null);
              recheckAll();
            }}>
              <option value="">—</option>
              {sh.order.lines.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.product || l.project} · {l.qty_open} open
                </option>
              ))}
            </select>
          </Field>
        </FieldRow>
      ) : null}
      <div className="ship-pack">
        <div>
          <div className="toolbar">
            <h3 className="card-subtitle">Scanned</h3>
            <span className="toolbar-total">
              {counts.ready} ready{counts.refused ? ` · ${counts.refused} refused` : ""}
              {counts.checking ? ` · ${counts.checking} checking` : ""}
            </span>
            <button type="button" className="btn btn-sm" disabled={!counts.refused}
                    onClick={() => list.removeWhere((s) => s.state === "done" && !s.check?.ok)}>
              Clear refused
            </button>
            <button type="button" className="btn btn-sm" disabled={!scans.length} onClick={recheckAll}>
              Re-check
            </button>
          </div>
          <DataTable rows={scans} columns={scanCols} rowKey={(s) => s.code} empty="Nothing scanned yet." />
        </div>
        <div className="ship-pack-arrows">
          <button type="button" className="btn btn-primary" disabled={busy || !selectedReady.length}
                  title="Put the selected devices in the shipment" onClick={() => pack(selectedReady)}>
            →
          </button>
          <button type="button" className="btn btn-sm" disabled={busy || !ready.length}
                  title="Put every ready device in the shipment" onClick={() => pack(ready)}>
            all →
          </button>
          <button type="button" className="btn" disabled={busy || !right.size}
                  title="Take the selected devices out of the shipment, back to stock" onClick={unpack}>
            ←
          </button>
        </div>
        <div>
          <div className="toolbar">
            <h3 className="card-subtitle">In this shipment</h3>
            <span className="toolbar-total">{plural(sh.qty, "device")}</span>
          </div>
          <DataTable rows={sh.devices} columns={boxCols} rowKey={(d) => d.device_id} empty="The box is empty." />
        </div>
      </div>
    </div>
  );
}
