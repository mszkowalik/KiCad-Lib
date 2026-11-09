/** Batch → Devices on a crafted batch: one list of everything the batch made.
 *
 *  It joins the twins (done, still needs, price) and the device records (broker,
 *  where it is, condition), so a device programmed with no unit behind it, a gap,
 *  is on the list too. A tick adds the device to the scan group, which Floor runs
 *  steps on. This is the main list of the tab, so it does not fold: its chips sit
 *  above the filter row, and a click on one narrows the list.
 */
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  getProjectDevices,
  type CraftDevice,
  type ProjectDeviceRow,
  type RunInfo,
} from "../../api";
import { pln, localWhen } from "../../format";
import DataTable, { type Column } from "../DataTable";
import { NarrowChip } from "../FoldSection";
import { ErrorBanner, Spinner, StatusPill } from "../Ui";
import { stepLabelOf, type CraftModal } from "./craftDialogs";
import type { ScanGroupState } from "./ScanGroup";
import type { Craft } from "./useCraft";
import { useLoad } from "../useLoad";

interface Row {
  id: number;
  code: string;
  twin: CraftDevice | null;
  rec: ProjectDeviceRow | null;
}

type Narrow = "" | "active" | "finished" | "gap" | "online" | "offline" | "unknown";

const presenceOf = (r: Row) => (!r.rec?.presence || r.rec.presence.online === null
  ? "unknown" : r.rec.presence.online ? "online" : "offline");

export default function RunDevices({ run, craft, group, onModal }: {
  run: RunInfo;
  craft: Craft;
  group: ScanGroupState;
  onModal: (m: CraftModal) => void;
}) {
  const { view } = craft;
  const { data: page, error } = useLoad(
    (signal) => getProjectDevices(run.project_id, { runId: run.id, limit: 2000 }, signal),
    [run.id, run.project_id, view],
    { keep: true },
  );
  const recs = page?.items ?? null;
  const truncated = page?.truncated ?? false;
  const [narrow, setNarrow] = useState<Narrow>("");
  const [shown, setShown] = useState<Row[]>([]);

  const rows: Row[] = useMemo(() => {
    const twins = new Map((view?.devices ?? []).map((d) => [d.device_id, d]));
    const out = (recs ?? []).map((rec): Row => ({
      id: rec.id, code: rec.serial || rec.mac, rec, twin: twins.get(rec.id) ?? null,
    }));
    const seen = new Set(out.map((r) => r.id));
    // A twin named here from a device another batch produced.
    for (const d of view?.devices ?? []) {
      if (!seen.has(d.device_id)) out.push({ id: d.device_id, code: d.serial || d.mac || "", twin: d, rec: null });
    }
    return out;
  }, [recs, view]);

  const count = (test: (r: Row) => boolean) => rows.filter(test).length;
  const listed = narrow === "" ? rows : rows.filter((r) => {
    if (narrow === "active" || narrow === "finished") return r.twin?.status === narrow;
    if (narrow === "gap") return !r.twin;
    return presenceOf(r) === narrow;
  });
  const label = stepLabelOf(view);

  const allShownTicked = shown.length > 0 && shown.every((r) => !r.twin || group.has(r.id));
  const columns: Column<Row>[] = [
    // Sortable, so the ticked devices can come to the top: a scan ticks a row
    // that may sit 700 rows down. The header box ticks, or unticks, every device
    // the filters leave shown. A gap has no unit to run a step on.
    { key: "sel", width: 3, interactive: false, sortable: true, className: "ctr",
      label: (
        <input type="checkbox" checked={allShownTicked} disabled={!shown.length}
          onChange={() => { for (const r of shown) if (r.twin) group.toggle(r.id, r.code, !allShownTicked); }}
          aria-label={allShownTicked ? "Untick every device shown" : "Tick every device shown"}
          title={allShownTicked ? "Untick every device shown" : "Tick every device shown"} />
      ),
      get: (r) => (group.has(r.id) ? 1 : 0), sortValue: (r) => (group.has(r.id) ? 0 : 1),
      render: (r) => (r.twin
        ? <input type="checkbox" checked={group.has(r.id)} onChange={(e) => group.toggle(r.id, r.code, e.target.checked)} />
        : null) },
    { key: "dev", label: "Device", width: "126px", className: "mono", get: (r) => r.code,
      render: (r) => <Link to={`/production/devices/${r.id}`} onClick={(e) => e.stopPropagation()}>{r.code}</Link> },
    { key: "status", label: "Work", width: 10, get: (r) => r.twin?.status ?? "gap",
      render: (r) => (r.twin ? <StatusPill status={r.twin.status} /> : <span className="pill warn">gap</span>) },
    { key: "done", label: "Done", width: 12, get: (r) => (r.twin?.done ?? []).map(label).join(", ") },
    // The finish date, so the units finished on one day are one filter away.
    { key: "finished", label: "Finished", width: 9, className: "mono", get: (r) => r.twin?.finished_at ?? "" },
    { key: "missing", label: "Still needs", width: 14, get: (r) => (r.twin?.missing ?? []).join("; "),
      render: (r) => (!r.twin ? <span className="muted">a unit: merge it</span>
        : r.twin.status === "finished" ? <span className="muted">—</span>
        : r.twin.missing.join("; ") || "ready to finish") },
    { key: "broker", label: "Broker", width: 10, get: (r) => presenceOf(r),
      render: (r) => { const p = presenceOf(r);
        return p === "unknown" ? <span className="muted">never seen</span> : <StatusPill status={p} />; } },
    { key: "state", label: "Where", width: 11, get: (r) => r.rec?.state ?? "",
      render: (r) => (r.rec?.state ? <StatusPill status={r.rec.state} /> : <span className="muted">—</span>) },
    { key: "condition", label: "Condition", width: 8, get: (r) => r.rec?.condition ?? "" },
    { key: "price", label: "Price", width: 12, numeric: true, get: (r) => r.twin?.price_usd ?? 0,
      render: (r) => (r.twin ? pln(r.twin.price_usd, view?.pln_per_usd) : "—") },
  ];

  if (error) return <ErrorBanner message={error} />;
  if (!view || !recs) return <Spinner />;

  const ids = group.deviceIds;
  return (
    <div className="card pad">
      <div className="fold-bar">
        <div className="fold-toggle">
          <h2 className="card-title">Devices</h2>
          <span className="fold-count">{rows.length.toLocaleString()}</span>
          <NarrowChip n={count((r) => r.twin?.status === "active")} value="active" current={narrow} onNarrow={setNarrow}>active</NarrowChip>
          <NarrowChip n={count((r) => r.twin?.status === "finished")} tone="ok" value="finished" current={narrow} onNarrow={setNarrow}>finished</NarrowChip>
          {count((r) => !r.twin) ? <NarrowChip n={count((r) => !r.twin)} tone="warn" value="gap" current={narrow} onNarrow={setNarrow}>gaps</NarrowChip> : null}
          <NarrowChip n={count((r) => presenceOf(r) === "online")} tone="acc" value="online" current={narrow} onNarrow={setNarrow}>online</NarrowChip>
          <NarrowChip n={count((r) => presenceOf(r) === "offline")} value="offline" current={narrow} onNarrow={setNarrow}>offline</NarrowChip>
          <NarrowChip n={count((r) => presenceOf(r) === "unknown")} value="unknown" current={narrow} onNarrow={setNarrow}>never seen</NarrowChip>
        </div>
      </div>
      {truncated ? <div className="banner-warn">The list holds the newest devices only.</div> : null}
      <div className="toolbar">
        <span className="muted">{ids.length} in the group
          {ids.length ? ` (${group.chosen === "scanned" ? "all scanned" : "some picked from the list"})` : ""}</span>
        <button type="button" className="btn btn-sm" disabled={!ids.length}
          onClick={() => onModal({ kind: "step", target: { kind: "devices", ids, chosen: group.chosen } })}>Run a step…</button>
        <button type="button" className="btn btn-sm btn-primary" disabled={!ids.length}
          onClick={() => onModal({ kind: "finish" })}>Mark finished…</button>
        <button type="button" className="btn btn-sm" disabled={!ids.length}
          onClick={() => onModal({ kind: "scrap", target: { kind: "devices", ids, chosen: group.chosen } })}>Scrap…</button>
        <button type="button" className="btn btn-sm" disabled={!ids.length}
          title="Finished units back into work: a new label, a new enclosure, a return"
          onClick={() => onModal({ kind: "reopen" })}>Reopen…</button>
        <button type="button" className="btn btn-sm" disabled={ids.length !== 1}
          title="The bench named this device from the wrong pile"
          onClick={() => onModal({ kind: "swap" })}>Swap twin…</button>
        <button type="button" className="btn btn-sm" disabled={ids.length !== 1}
          title="A bench run was filed against another device: move it, with its steps, to this one"
          onClick={() => onModal({ kind: "relink" })}>Relink run…</button>
        {ids.length ? <button type="button" className="btn btn-sm" onClick={() => group.clear()}>Clear</button> : null}
      </div>
      <DataTable rows={listed} columns={columns} rowKey={(r) => r.id}
        persistKey={`run:${run.id}:devices`} defaultSort={{ key: "sel", dir: "asc" }} onVisibleChange={setShown}
        expand={(r) => {
          const p = r.rec?.presence;
          return (
            <dl className="kv">
              <dt>Last seen</dt><dd>{localWhen(p?.last_seen_at ?? null) || "never"}</dd>
              <dt>Inverter</dt><dd>{p?.inverter || "—"}{p?.inverter_sn ? ` · ${p.inverter_sn}` : ""}</dd>
              <dt>Firmware</dt><dd>{p?.dongle_version || "—"}</dd>
              <dt>Temperature</dt><dd>{p?.temperature_c != null ? `${p.temperature_c.toFixed(1)} °C` : "—"}</dd>
              <dt>Programming runs</dt><dd>{Object.entries(r.rec?.attempts ?? {}).map(([k, n]) => `${n} ${k}`).join(", ") || "—"}</dd>
            </dl>
          );
        }}
        empty="No device yet: the programming bench names units as it programs them." />
    </div>
  );
}
