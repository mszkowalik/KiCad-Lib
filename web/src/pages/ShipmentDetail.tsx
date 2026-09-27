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
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  cancelShipment,
  checkShipmentCodes,
  deleteShipment,
  errorMessage,
  getShipment,
  isAbortError,
  packShipment,
  patchShipment,
  sendShipment,
  unpackShipment,
  type ShipmentCheck,
  type ShipmentDetail as Detail,
  type ShipmentDeviceRow,
} from "../api";
import DataTable, { type Column } from "../components/DataTable";
import { useDialog } from "../components/Dialog";
import Field, { FieldRow } from "../components/Field";
import { BackLink, ErrorBanner, Spinner, StatusPill } from "../components/Ui";
import { parseScanSheet } from "./Orders";

type ScanState = "pending" | "checking" | "done" | "error";
interface Scan {
  code: string;
  state: ScanState;
  check?: ShipmentCheck;
  error?: string;
}

const scanKey = (id: number) => `kicadlib:shipment-scan:${id}`;

function loadScans(id: number): Scan[] {
  try {
    const raw = window.localStorage.getItem(scanKey(id));
    const codes: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(codes) ? codes.filter((c) => typeof c === "string").map((code) => ({ code, state: "pending" })) : [];
  } catch {
    return [];
  }
}

function saveScans(id: number, scans: Scan[]) {
  try {
    if (scans.length) window.localStorage.setItem(scanKey(id), JSON.stringify(scans.map((s) => s.code)));
    else window.localStorage.removeItem(scanKey(id));
  } catch {
    /* private window or blocked storage: the list just does not survive a reload */
  }
}

export default function ShipmentDetail() {
  const { id: idParam } = useParams();
  const id = Number(idParam);
  const [sh, setSh] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    const ac = new AbortController();
    getShipment(id, ac.signal)
      .then((s) => {
        setSh(s);
        setError(null);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [id]);
  useEffect(reload, [reload]);

  return (
    <div className="main-solo">
      <div className="page">
        <BackLink to="/production/shipments">← Shipments</BackLink>
        <div className="toolbar">
          <h1>Shipment #{id}</h1>
          {sh ? <StatusPill status={sh.status} /> : null}
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
      </div>
    </div>
  );
}

function HeaderCard({ sh }: { sh: Detail }) {
  const open = sh.status === "open";
  const o = sh.order;
  return (
    <div className="card pad">
      <h2 className="card-title">
        <Link to={`/production/orders/${o.id}`}>{o.order_ref}</Link> · {o.customer}
      </h2>
      <div className="table-wrap">
        <table className="data order-table">
          <thead>
            <tr>
              <th>Line</th>
              <th className="num">Ordered</th>
              <th className="num">Shipped</th>
              <th className="num">Open</th>
              <th className="num">{open ? "In this box" : "On this shipment"}</th>
            </tr>
          </thead>
          <tbody>
            {o.lines.map((l) => {
              const here = sh.per_line[String(l.id)] ?? 0;
              const over = open && here > l.qty_open;
              return (
                <tr key={l.id}>
                  <td>{l.product || l.project}</td>
                  <td className="num">{l.qty_ordered.toLocaleString()}</td>
                  <td className="num">{l.qty_shipped.toLocaleString()}</td>
                  <td className="num">{l.qty_open.toLocaleString()}</td>
                  <td className={"num" + (over ? " warn-text" : "")}
                      title={over ? "More devices in the box than the line has open" : undefined}>
                    {here.toLocaleString()}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
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
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
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
                `Mark this shipment as sent on ${date}? ${sh.qty} device${sh.qty === 1 ? "" : "s"} are recorded as shipped to ${sh.order.customer}, and the box is closed.`,
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
                  navigate("/production/shipments");
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
                  `Cancel this shipment? ${sh.qty} packed device${sh.qty === 1 ? "" : "s"} go back to stock. The shipment stays in the list as cancelled.`,
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
        width: 40,
        className: "mono",
        get: (d) => d.serial || d.mac,
        render: (d) => <Link to={`/production/devices/${d.device_id}`}>{d.serial || d.mac}</Link>,
      },
      { key: "run", label: "Batch", width: 20, numeric: true, get: (d) => d.run_id ?? "" },
      { key: "state", label: "State now", width: 40, get: (d) => d.state },
    ],
    [],
  );
  return (
    <div className="card pad">
      <h2 className="card-title">Devices</h2>
      {sh.status === "cancelled" ? <p className="muted dim">Cancelled before it was sent. Its devices went back to stock.</p> : null}
      <DataTable rows={sh.devices} columns={columns} rowKey={(d) => d.device_id} empty="No device on this shipment." />
    </div>
  );
}

/** The packing station: scan field, SCANNED list, arrows, IN THIS SHIPMENT. */
function PackCard({ sh, onChange }: { sh: Detail; onChange: (s: Detail) => void }) {
  const [scans, setScans] = useState<Scan[]>(() => loadScans(sh.id));
  const [code, setCode] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [left, setLeft] = useState<Set<string>>(new Set());
  const [right, setRight] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const inflight = useRef(false);
  const input = useRef<HTMLInputElement>(null);

  // A line only needs naming when two lines of the order carry the same product.
  const ambiguous = useMemo(() => {
    const seen = new Set<number>();
    return sh.order.lines.some((l) => (seen.has(l.project_id) ? true : (seen.add(l.project_id), false)));
  }, [sh.order.lines]);
  const [lineId, setLineId] = useState<number | null>(null);

  useEffect(() => saveScans(sh.id, scans), [sh.id, scans]);

  // Check whatever is pending, in batches, one request at a time. Scans that
  // arrive while a request is out wait for the next round.
  useEffect(() => {
    if (inflight.current) return;
    const pending = scans.filter((s) => s.state === "pending").map((s) => s.code);
    if (!pending.length) return;
    inflight.current = true;
    const want = new Set(pending);
    setScans((ss) => ss.map((s) => (want.has(s.code) && s.state === "pending" ? { ...s, state: "checking" } : s)));
    checkShipmentCodes(sh.id, pending, lineId)
      .then((res) => {
        const by = new Map(res.map((r) => [r.code, r]));
        setScans((ss) =>
          ss.map((s) => (s.state === "checking" && by.has(s.code) ? { ...s, state: "done", check: by.get(s.code) } : s)),
        );
      })
      .catch((err) => {
        const msg = errorMessage(err);
        setScans((ss) => ss.map((s) => (s.state === "checking" && want.has(s.code) ? { ...s, state: "error", error: msg } : s)));
      })
      .finally(() => {
        inflight.current = false;
        // Wake the effect for anything scanned meanwhile.
        setScans((ss) => [...ss]);
      });
  }, [scans, sh.id, lineId]);

  /** One scan is taken as typed; only a PASTED list goes through
   *  `parseScanSheet`, which drops tokens with `:` or `-` (timestamps and MACs
   *  in a scanner's CSV export) — a scanned `PROTO-0045` must not vanish. */
  const add = (raw: string, list = false) => {
    const codes = list ? parseScanSheet(raw) : [raw.trim()].filter(Boolean);
    if (!codes.length) return;
    const have = new Set([...scans.map((s) => s.code), ...sh.devices.map((d) => d.serial)]);
    const dup = codes.filter((c) => have.has(c));
    setNotice(dup.length ? `${dup.length === 1 ? `${dup[0]} is` : `${dup.length} codes are`} already on a list — not added again.` : null);
    // The updater re-checks against the list as it is NOW: two scans can land
    // before this render's `scans` is replaced.
    setScans((ss) => {
      const now = new Set(ss.map((s) => s.code));
      const fresh = codes.filter((c) => !have.has(c) && !now.has(c));
      return fresh.length ? [...fresh.map((c) => ({ code: c, state: "pending" as ScanState })), ...ss] : ss;
    });
  };

  const recheckAll = () => setScans((ss) => ss.map((s) => ({ code: s.code, state: "pending" })));

  const ready = scans.filter((s) => s.check?.ok);
  const selectedReady = ready.filter((s) => left.has(s.code));

  const pack = async (rows: Scan[]) => {
    const ids = rows.map((s) => s.check!.device_id!).filter(Boolean);
    if (!ids.length) return;
    setBusy(true);
    setError(null);
    try {
      const r = await packShipment(sh.id, ids, lineId);
      const gone = new Set(rows.map((s) => s.code));
      setScans((ss) => ss.filter((s) => !gone.has(s.code)));
      setLeft(new Set());
      onChange(r);
    } catch (err) {
      setError(errorMessage(err));
      recheckAll();
    } finally {
      setBusy(false);
      input.current?.focus();
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
      setScans((ss) => [...back.map((c) => ({ code: c, state: "pending" as ScanState })), ...ss]);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
      input.current?.focus();
    }
  };

  const scanCols: Column<Scan>[] = [
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
            <span className="pill ok">ready</span>
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
                onClick={() => setScans((ss) => ss.filter((x) => x.code !== s.code))}>
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
      width: 34,
      className: "mono",
      get: (d) => d.serial || d.mac,
      render: (d) => <Link to={`/production/devices/${d.device_id}`}>{d.serial || d.mac}</Link>,
    },
    {
      key: "line",
      label: "Line",
      width: 30,
      get: (d) => {
        const l = sh.order.lines.find((x) => x.id === d.order_line_id);
        return l ? l.product || l.project : "";
      },
    },
    {
      key: "packed",
      label: "Packed",
      width: 30,
      className: "mono",
      get: (d) => d.packed_at ?? "",
      render: (d) => (d.packed_at ? new Date(d.packed_at).toLocaleString() : ""),
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
      <FieldRow>
        <Field label="Scan" hint={notice ?? "Enter adds the code. Pasting a list works too."}>
          <input
            ref={input}
            className="text mono"
            autoFocus
            value={code}
            placeholder="scan a serial…"
            onChange={(e) => setCode(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                add(code);
                setCode("");
              }
            }}
            onPaste={(e) => {
              const text = e.clipboardData.getData("text");
              if (/\s/.test(text.trim())) {
                e.preventDefault();
                add(text, true);
              }
            }}
          />
        </Field>
        {ambiguous ? (
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
        ) : null}
      </FieldRow>
      <div className="ship-pack">
        <div>
          <div className="toolbar">
            <h3 className="card-subtitle">Scanned</h3>
            <span className="toolbar-total">
              {counts.ready} ready{counts.refused ? ` · ${counts.refused} refused` : ""}
              {counts.checking ? ` · ${counts.checking} checking` : ""}
            </span>
            <button type="button" className="btn btn-sm" disabled={!counts.refused}
                    onClick={() => setScans((ss) => ss.filter((s) => !(s.state === "done" && !s.check?.ok)))}>
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
            <span className="toolbar-total">{sh.qty} device{sh.qty === 1 ? "" : "s"}</span>
          </div>
          <DataTable rows={sh.devices} columns={boxCols} rowKey={(d) => d.device_id} empty="The box is empty." />
        </div>
      </div>
    </div>
  );
}
