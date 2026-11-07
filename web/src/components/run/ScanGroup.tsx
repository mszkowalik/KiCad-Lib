/** The scan group (decision 0103): the devices a person chose with the scanner,
 *  and the steps to run on them.
 *
 *  The board says how many units can go, and it cannot say which. After
 *  programming each unit is a named device, and the case this exists for is real:
 *  some devices are in cartons with leaflets and the others are not, because the
 *  cartons ran out. So the person scans the packed ones, ticks Pack into carton
 *  and Instruction leaflet, and runs both on that group only.
 *
 *  The group is shared with the Devices tab: a tick in its list adds a device
 *  here, recorded as `list`, and a scan as `scanned`. A scan is an observation and
 *  a tick is a person's statement, so the write is `scanned` only when every
 *  device was.
 *
 *  The group STAYS after a run, so the next step can go on the same devices.
 *  The preview sits in the card and not in a dialog, so a scan cannot land on a
 *  dialog button. A new scan closes it, because the group has changed.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  checkCraftCodes,
  craftSteps,
  errorMessage,
  type CodeCheck,
  type CraftView,
  type RunInfo,
  type StepsPlan,
} from "../../api";
import { pln, today, plural } from "../../format";
import AutoTextarea from "../AutoTextarea";
import DataTable from "../DataTable";
import { useDialog } from "../Dialog";
import Field, { CheckField, FieldGrid } from "../Field";
import FoldSection, { StatChip } from "../FoldSection";
import NumberInput from "../NumberInput";
import { ScanBox, useScanList, type Scan, type ScanBoxHandle } from "../ScanList";
import { ErrorBanner, StatusPill } from "../Ui";
import { STATABLE, stepLabelOf } from "./craftDialogs";

export function useScanGroup(runId: number, view: CraftView | null) {
  const labelOf = stepLabelOf(view);
  const list = useScanList<CodeCheck>({
    storageKey: `henry:batch-scan:${runId}`,
    check: (codes) => checkCraftCodes(runId, codes),
    codeOf: (c) => c.code,
    isOk: (c) => c.ok,
    describe: (c) => (c.ok
      ? { tone: "ok", text: `${c.code} added. It can take ${c.can.map(labelOf).join(", ") || "no step now"}.` }
      : { tone: "err", text: `${c.code} ${c.why}. The next scan works.` }),
  });
  const [ticks, setTicks] = useState<string[]>([]);
  const box = useRef<ScanBoxHandle>(null);
  const focus = () => box.current?.focus();

  /** The usable entries, one per device: a serial and a MAC are one device. */
  const ready = useMemo(() => {
    const seen = new Set<number>();
    return list.scans.filter((s) => {
      const id = s.check?.ok ? s.check.device_id : null;
      if (!id || seen.has(id)) return false;
      seen.add(id);
      return true;
    });
  }, [list.scans]);
  const deviceIds = ready.map((s) => s.check!.device_id!);
  const chosen: "scanned" | "list" = ready.every((s) => s.how === "scanned") ? "scanned" : "list";

  const has = (deviceId: number) => deviceIds.includes(deviceId);
  /** A tick in the Devices list. */
  const toggle = (deviceId: number, code: string, on: boolean) => {
    if (on) list.add([code], "list");
    else list.removeWhere((s) => s.code === code || s.check?.device_id === deviceId);
  };
  const countFor = (key: string) => ready.filter((s) => s.check!.can.includes(key)).length;
  const tick = (key: string, on: boolean) =>
    setTicks((t) => (on ? [...new Set([...t, key])] : t.filter((k) => k !== key)));

  return { ...list, ticks, setTicks, tick, box, focus, ready, deviceIds, chosen, has, toggle, countFor };
}

export type ScanGroupState = ReturnType<typeof useScanGroup>;

export default function ScanGroup({ run, view, group, onChanged }: {
  run: RunInfo;
  view: CraftView;
  group: ScanGroupState;
  onChanged: () => void;
}) {
  const dialog = useDialog();
  const [plan, setPlan] = useState<StepsPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [madeAt, setMadeAt] = useState(today());
  const [note, setNote] = useState("");
  const [stated, setStated] = useState("");
  const [lots, setLots] = useState<Record<string, number>>({});
  const [showBench, setShowBench] = useState(false);
  const { scans, ready, ticks, deviceIds, chosen } = group;
  const refused = scans.filter((s) => s.check && !s.check.ok).length;

  // The group or the steps changed: what the preview said no longer holds.
  useEffect(() => { setPlan(null); }, [deviceIds.join(","), ticks.join(",")]);

  const label = stepLabelOf(view);
  const route = view.board;
  const nOf = (k: string) => route.findIndex((s) => s.key === k) + 1;
  // The steps a person runs here. A bench step may be STATED, with the reason,
  // when no bench recorded it (decision 0074), so it stays one click further.
  const runHere = route.filter((s) => s.kind === "step" || s.kind === "finish" || (showBench && STATABLE.includes(s.kind)));
  const needsOf = (k: string) => view.graph.steps.find((s) => s.key === k)?.needs ?? [];
  /** On this device now, or after the ticked steps before it have run. */
  const canAfter = (c: CodeCheck, key: string): "now" | "after" | null => {
    if (c.can.includes(key)) return "now";
    if (c.done.includes(key) || key === "finish") return null;
    const earlier = ticks.filter((t) => c.can.includes(t) && nOf(t) < nOf(key));
    return earlier.length && needsOf(key).every((n) => c.done.includes(n) || earlier.includes(n)) ? "after" : null;
  };
  // A step shows when it is ticked, when a device of the group can take it, or,
  // with an empty group, when devices wait there: a step on unnamed units is a
  // stack's, and it belongs to its field.
  const offered = runHere.filter((s) => ticks.includes(s.key)
    || (ready.length ? ready.some((r) => canAfter(r.check!, s.key)) : s.waiting_named > 0));
  const statedTicked = ticks.some((k) => STATABLE.includes(route.find((s) => s.key === k)?.kind ?? ""));
  const preparedInputs = view.graph.steps
    .filter((s) => ticks.includes(s.key))
    .flatMap((s) => s.inputs ?? [])
    .filter((i) => view.parts[String(i.component_id)]?.internal);
  const goingCount = ready.filter((s) => ticks.some((k) => canAfter(s.check!, k))).length;

  const body = (dry: boolean) => ({
    step_keys: ticks, device_ids: deviceIds, chosen, made_at: madeAt, note, stated,
    lots: Object.keys(lots).length ? lots : null, dry_run: dry,
  });
  const preview = async () => {
    setBusy(true); setError(null);
    try { setPlan(await craftSteps(run.id, body(true))); }
    catch (err) { setError(errorMessage(err)); }
    finally { setBusy(false); }
  };
  const apply = async () => {
    setBusy(true); setError(null);
    try {
      const done = await craftSteps(run.id, body(false));
      const said = done.steps.filter((p) => p.units).map((p) => `${p.label} on ${p.units}`).join(", ");
      group.setNotice({ tone: "ok", text: `Done: ${said}. The group stays, so you can tick the next step.` });
      group.setTicks([]);
      setNote(""); setStated(""); setLots({});
      setPlan(null);
      onChanged();
      group.recheck();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
      group.focus();
    }
  };

  const addAllWaiting = async () => {
    const steps = view.graph.steps.filter((s) => ticks.includes(s.key));
    const groupMembers = (ref: string) => view.graph.steps.filter((s) => s.group === ref).map((s) => s.key);
    const waiting = view.devices.filter((d) => d.status === "active" && steps.some((s) => (s.kind === "finish"
      ? !d.missing.length
      : !d.done.includes(s.key) && (s.needs ?? []).every((n) => d.done.includes(n)
        || groupMembers(n).some((m) => d.done.includes(m))))));
    const codes = waiting.map((d) => d.serial || d.mac || "").filter((c) => c && !scans.some((s) => s.code === c));
    if (!codes.length) {
      group.setNotice({ tone: "warn", text: "No more devices wait at the ticked steps." });
      group.focus();
      return;
    }
    const ok = await dialog.confirm(
      `Add the ${codes.length} device(s) that wait at ${steps.map((s) => s.label || s.key).join(" and ")}? `
        + "They are recorded as picked from a list, because nobody scanned them.",
      { title: "Add all waiting", confirmLabel: `Add ${codes.length}` },
    );
    if (ok) group.add(codes, "list");
    group.focus();
  };

  return (
    <div className="card pad">
      <div className="fold-bar">
        <div className="fold-toggle">
          <h2 className="card-title">Scan group</h2>
          <StatChip n={ready.length}>in the group</StatChip>
          {refused ? <StatChip n={refused} tone="err">refused</StatChip> : null}
          {scans.some((s) => s.state === "pending" || s.state === "checking")
            ? <span className="muted dim">checking…</span> : null}
        </div>
        <button type="button" className="btn btn-sm" disabled={!ticks.length} onClick={() => void addAllWaiting()}
          title="Add every device that waits at the ticked steps">Add all waiting…</button>
        {refused ? (
          <button type="button" className="btn btn-sm"
            onClick={() => { group.removeWhere((s) => !!s.check && !s.check.ok); group.focus(); }}>Clear refused</button>
        ) : null}
        <button type="button" className="btn btn-sm" disabled={!scans.length}
          onClick={() => { group.clear(); group.focus(); }}>Clear group</button>
      </div>

      <ScanBox ref={group.box} label="Scan a label or MAC" onScan={group.scan} onPaste={group.paste}
        notice={group.notice} hint="A code and Enter adds one device. Pasting a list works too." />

      <div className="scan-steps">
        {offered.map((s) => {
          const now = ready.filter((r) => canAfter(r.check!, s.key) === "now").length;
          const after = ready.filter((r) => canAfter(r.check!, s.key) === "after").length;
          const draws = (view.graph.steps.find((x) => x.key === s.key)?.inputs ?? [])
            .map((i) => `${i.qty} × ${s.inputs.find((b) => b.key === (i.component_id ? `c${i.component_id}` : `m${i.mpn}`))?.name ?? i.mpn}`)
            .join(" + ");
          return (
            <CheckField key={s.key} checked={ticks.includes(s.key)}
              onChange={(v) => { group.tick(s.key, v); group.focus(); }}>
              <b>{nOf(s.key)} · {s.label}</b>{" "}
              <span className="muted">
                {now + after} of {ready.length} can take it{after ? ", after the steps before it" : ""}
                {draws ? ` · ${draws}` : ""}
                {STATABLE.includes(s.kind) ? " · state it" : ""}
              </span>
            </CheckField>
          );
        })}
        {!offered.length ? (
          <p className="muted dim">Scan a device: the steps it can take show here.</p>
        ) : null}
        <button type="button" className="btn-link muted dim" onClick={() => setShowBench(!showBench)}>
          {showBench ? "Hide the bench steps" : "A bench did not record a step: state it…"}
        </button>
      </div>

      {statedTicked ? (
        <Field label="Why no bench recorded it" hint="required: the step is saved as your statement">
          <AutoTextarea className="text" value={stated} onChange={(e) => setStated(e.target.value)} />
        </Field>
      ) : null}
      {preparedInputs.map((i) => (
        <Field key={i.component_id} label={`Lot of ${view.parts[String(i.component_id)]?.name}`}
          hint="one lot per step, so the units stay one pile">
          <NumberInput className="text" value={lots[String(i.component_id)] ?? null} min={1}
            placeholder="oldest lot that holds enough"
            onChange={(v) => setLots({ ...lots, [String(i.component_id)]: v as number })} />
        </Field>
      ))}

      {error ? <ErrorBanner message={error} /> : null}

      {plan ? (
        <div className="scan-preview">
          {plan.steps.map((p) => (
            <div key={p.step}>
              <b>{p.units}</b> device(s) take {p.label}
              {p.draws.length ? <>: {p.draws.map((d) => `${d.qty} × ${d.name}`).join(", ")}, {pln(p.value_usd, view.pln_per_usd)}</> : null}.
              {p.shortages.length ? (
                <div className="banner-error">Not in stock: {p.shortages.map((x) => `${x.label} (${x.short} short)`).join(", ")}</div>
              ) : null}
              {p.problems.length ? (
                <div className="banner-error">{p.problems.map((x) => `${x.name}: ${x.problem}`).join("; ")}</div>
              ) : null}
              {p.refused.length ? (
                <div className="muted dim">Skipped: {p.refused.map((r) => `${r.unit} (${r.why.join(", ")})`).join("; ")}</div>
              ) : null}
            </div>
          ))}
          <FieldGrid>
            <Field label="Done on">
              <input className="text" type="date" value={madeAt} onChange={(e) => setMadeAt(e.target.value)} />
            </Field>
            <Field label="Note" wide>
              <AutoTextarea className="text" value={note} onChange={(e) => setNote(e.target.value)} />
            </Field>
          </FieldGrid>
          <div className="btn-row">
            <button type="button" className="btn btn-primary" disabled={busy
              || !plan.steps.some((p) => p.units) || plan.steps.some((p) => p.shortages.length || p.problems.length)}
              onClick={() => void apply()}>{busy ? "Working…" : "Apply"}</button>
            <button type="button" className="btn" onClick={() => { setPlan(null); group.focus(); }}>Back</button>
          </div>
        </div>
      ) : (
        <div className="btn-row">
          <button type="button" className="btn btn-primary" disabled={busy || !ticks.length || !goingCount
            || (statedTicked && !stated.trim())} onClick={() => void preview()}>
            {busy ? "Working…" : `Run ${ticks.length || "no"} step${ticks.length === 1 ? "" : "s"} on ${plural(goingCount, "device")}…`}
          </button>
        </div>
      )}

      {scans.length ? (
        <FoldSection bare title="In the group" count={scans.length} foldKey={`run:${run.id}:scan`}
          chips={<>
            <StatChip n={ready.filter((r) => r.how === "scanned").length} tone="ok">scanned</StatChip>
            {ready.some((r) => r.how === "list") ? <StatChip n={ready.filter((r) => r.how === "list").length}>ticked</StatChip> : null}
            {refused ? <StatChip n={refused} tone="err">refused</StatChip> : null}
          </>}>
          <DataTable<Scan<CodeCheck>>
            rows={scans}
            rowKey={(s) => s.code}
            columns={[
              { key: "code", label: "Code", width: 22, className: "mono", get: (s) => s.code,
                render: (s) => (s.check?.device_id
                  ? <Link to={`/production/devices/${s.check.device_id}`}>{s.code}</Link> : s.code) },
              { key: "how", label: "Scan", width: 12, get: (s) => (s.check && !s.check.ok ? "refused" : s.state === "done" ? s.how : s.state),
                render: (s) => (s.state === "error" ? <span className="pill err">error</span>
                  : !s.check ? <span className="pill neutral">{s.state}</span>
                  : s.check.ok ? <span className={`pill ${s.how === "scanned" ? "ok" : "neutral"}`}>{s.how === "scanned" ? "scanned" : "ticked"}</span>
                  : <span className="pill err">refused</span>) },
              { key: "state", label: "State", width: 32,
                get: (s) => s.error ?? (s.check ? (s.check.ok ? `has ${s.check.done.map(label).join(", ")}` : s.check.why) : ""),
                render: (s) => (s.check && s.check.ok && s.check.status && s.check.status !== "active"
                  ? <StatusPill status={s.check.status} />
                  : s.error ?? (s.check ? (s.check.ok ? (s.check.done.length ? `last: ${label(s.check.done[s.check.done.length - 1])}` : "—") : s.check.why) : "")) },
              { key: "can", label: "Can take", width: 28, get: (s) => (s.check?.can ?? []).map(label).join(", ") || "—" },
              { key: "x", label: "", width: 6, interactive: false, get: () => "",
                render: (s) => (
                  <button type="button" className="btn btn-sm" aria-label={`Take ${s.code} out of the group`}
                    onClick={() => { group.remove(s.code); group.focus(); }}>×</button>
                ) },
            ]}
          />
        </FoldSection>
      ) : null}
    </div>
  );
}
