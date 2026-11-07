/** Admin → Data jobs: the ledger's size and state maps (decisions 0097, 0098), the
 *  company backfill (decision 0063), and the rebuild of programming checks.
 *
 *  A job with a dry run goes through `DryRunDialog`. A job with none asks first and
 *  says so. A dialog closes when its write lands, so each `run` keeps the answer of
 *  the real write for the card to print.
 */
import { useEffect, useState } from "react";
import {
  companyBackfill,
  deleteMaterialStateMap,
  errorMessage,
  getComponent,
  getMaterialLedgerSummary,
  getMaterialStateMaps,
  getProjects,
  isAbortError,
  putMaterialStateMap,
  recomputeChecks,
  type CompanyBackfillResult,
  type MaterialLedgerSummary,
  type MaterialStateMapRow,
  type ProjectInfo,
} from "../api";
import AutoTextarea from "./AutoTextarea";
import ComponentPickDialog from "./ComponentPickDialog";
import DataTable, { type Column } from "./DataTable";
import { useDialog } from "./Dialog";
import Field, { FieldGrid } from "./Field";
import FoldSection, { StatChip } from "./FoldSection";
import NumberInput from "./NumberInput";
import { DryRunDialog } from "./process/StageDialogs";
import { ErrorBanner, Spinner } from "./Ui";
import { plural } from "../format";

/** The ledger's tables, in the order a reader meets them. */
const LEDGER_TABLES: [string, string][] = [
  ["material_items", "items"],
  ["material_lots", "lots"],
  ["material_events", "events"],
  ["material_moves", "moves"],
  ["material_move_lots", "move lots"],
  ["material_event_lots", "event lots"],
  ["material_links", "links"],
  ["material_properties", "properties"],
  ["material_cost_aims", "cost aims"],
  ["material_state_maps", "state maps"],
];

function propertiesText(props: Record<string, unknown>): string {
  return Object.entries(props)
    .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join("\n");
}

/** One `name=value` per line. A plain number or true/false keeps its type, because
 *  the column is JSON, and anything else stays text. */
function parseProperties(text: string): { props: Record<string, unknown>; problem: string } {
  const props: Record<string, unknown> = {};
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  for (const line of lines) {
    const at = line.indexOf("=");
    if (at < 1) return { props, problem: `This line has no name=value: ${line}` };
    const name = line.slice(0, at).trim();
    const raw = line.slice(at + 1).trim();
    if (raw === "true" || raw === "false") props[name] = raw === "true";
    else if (raw !== "" && /^-?\d+(\.\d+)?$/.test(raw)) props[name] = Number(raw);
    else props[name] = raw;
  }
  return { props, problem: lines.length ? "" : "Name at least one property." };
}

interface PickedPart {
  id: number;
  name: string;
}

const EMPTY_FORM = { part: null as PickedPart | null, item: null as PickedPart | null, properties: "", note: "" };

export function MaterialLedgerCard() {
  const dialog = useDialog();
  const [summary, setSummary] = useState<MaterialLedgerSummary | null>(null);
  const [maps, setMaps] = useState<MaterialStateMapRow[] | null>(null);
  const [err, setErr] = useState("");
  const [form, setForm] = useState(EMPTY_FORM);
  const [picking, setPicking] = useState<"part" | "item" | null>(null);
  const [busy, setBusy] = useState(false);

  const load = (signal?: AbortSignal) =>
    Promise.all([getMaterialLedgerSummary(signal), getMaterialStateMaps(signal)])
      .then(([s, m]) => {
        setSummary(s);
        setMaps(m);
        setErr("");
      })
      .catch((e) => {
        if (!isAbortError(e)) setErr(errorMessage(e));
      });

  useEffect(() => {
    const ac = new AbortController();
    void load(ac.signal);
    return () => ac.abort();
  }, []);

  /** The picker returns an id and an MPN, and an internal part often has no MPN. */
  const pick = async (which: "part" | "item", id: number | null) => {
    if (id === null) return;
    const name = await getComponent(id).then((c) => c.name).catch(() => `#${id}`);
    setForm((f) => ({ ...f, [which]: { id, name } }));
  };

  const save = async () => {
    if (!form.part || !form.item) return;
    const { props, problem } = parseProperties(form.properties);
    if (problem) {
      setErr(problem);
      return;
    }
    const replaces = maps?.some((m) => m.component_id === form.part?.id);
    if (!(await dialog.confirm(
      `State that ${form.part.name} is a state of ${form.item.name}, with ${plural(Object.keys(props).length, "property", "properties")}?` +
        (replaces ? " This replaces the map that this part has now." : "") +
        " Nothing reads a map for stock or cost today.",
      { title: "Save the state map", confirmLabel: "Save" },
    ))) return;
    setBusy(true);
    setErr("");
    try {
      await putMaterialStateMap({
        component_id: form.part.id,
        item_component_id: form.item.id,
        properties: props,
        note: form.note,
      });
      setForm(EMPTY_FORM);
      await load();
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (m: MaterialStateMapRow) => {
    if (!(await dialog.confirm(
      `Remove the state map of ${m.component ?? `#${m.component_id}`}? The part and its stock stay as they are.`,
      { title: "Remove the state map", confirmLabel: "Remove", tone: "danger" },
    ))) return;
    setBusy(true);
    setErr("");
    try {
      await deleteMaterialStateMap(m.component_id);
      await load();
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const columns: Column<MaterialStateMapRow>[] = [
    { key: "part", label: "Internal part", width: 20, get: (m) => m.component ?? `#${m.component_id}` },
    { key: "item", label: "A state of", width: 20, get: (m) => m.item ?? `#${m.item_component_id}` },
    { key: "props", label: "Properties", width: 24, className: "mono",
      get: (m) => propertiesText(m.properties).replace(/\n/g, ", ") },
    { key: "note", label: "Note", width: 12, className: "muted", get: (m) => m.note },
    { key: "by", label: "By", width: 8, get: (m) => m.decided_by },
    { key: "act", label: "", width: 16, interactive: false, get: () => "",
      render: (m) => (
        <span className="btn-row">
          <button type="button" className="btn btn-sm" disabled={busy}
            onClick={() => setForm({
              part: { id: m.component_id, name: m.component ?? `#${m.component_id}` },
              item: { id: m.item_component_id, name: m.item ?? `#${m.item_component_id}` },
              properties: propertiesText(m.properties),
              note: m.note,
            })}>
            Edit
          </button>
          <button type="button" className="btn btn-danger btn-sm" disabled={busy} onClick={() => void remove(m)}>
            Remove…
          </button>
        </span>
      ) },
  ];

  return (
    <FoldSection title="Material ledger" count={null} foldKey="admin:jobs:material-ledger">
      <p className="muted dim">
        The ledger is the one storage of stock, work and units (decisions 0097 and 0098). This shows its size
        and the state maps.
      </p>
      <ErrorBanner message={err} />
      {summary === null ? (!err ? <Spinner label="Reading the ledger…" /> : null) : (
        <>
          <div className="toolbar">
            {LEDGER_TABLES.map(([table, word]) => (
              <StatChip key={table} n={(summary.rows[table] ?? 0).toLocaleString()} title={table}>{word}</StatChip>
            ))}
          </div>
          <div className="toolbar">
            <span className="muted">Items by tracking level:</span>
            {Object.entries(summary.tracking).map(([level, n]) => (
              <StatChip key={level} n={n.toLocaleString()}>{level}</StatChip>
            ))}
          </div>
        </>
      )}
      <FoldSection bare title="State maps" count={maps?.length ?? 0} foldKey="admin-state-maps">
        <p className="muted dim">
          A state map says that an internal part is a state of another item, with named properties. For example,
          &ldquo;SIM6-12-3W cut&rdquo; is SIM6-12-3W with four <span className="mono">cut_*</span> properties.
          Nothing reads a map for stock or cost today. The work on phase 4 of decision 0097 reads it. One internal
          part has one map, so a second map for the part replaces the first.
        </p>
        {maps !== null ? (
          <DataTable rows={maps} rowKey={(m) => m.component_id} columns={columns} empty="No state maps." />
        ) : null}
      </FoldSection>
      <h3>{form.part && maps?.some((m) => m.component_id === form.part?.id) ? "Change a state map" : "Add a state map"}</h3>
      <FieldGrid>
        <Field label="Internal part" hint="The part that names the state. It must be internal.">
          <button type="button" className="btn btn-sm" onClick={() => setPicking("part")}>
            {form.part ? form.part.name : "Choose…"}
          </button>
        </Field>
        <Field label="A state of" hint="The item itself. It must not be internal.">
          <button type="button" className="btn btn-sm" onClick={() => setPicking("item")}>
            {form.item ? form.item.name : "Choose…"}
          </button>
        </Field>
        <Field label="Properties" hint="One name=value per line. A number stays a number. Anything else stays text." wide>
          <AutoTextarea className="text mono" value={form.properties} spellCheck={false}
            placeholder="cut_length=120"
            onChange={(e) => setForm((f) => ({ ...f, properties: e.target.value }))} />
        </Field>
        <Field label="Note" wide>
          <input className="text" value={form.note} maxLength={500}
            onChange={(e) => setForm((f) => ({ ...f, note: e.target.value }))} />
        </Field>
      </FieldGrid>
      <div className="btn-row">
        <button type="button" className="btn btn-primary btn-sm"
          disabled={busy || !form.part || !form.item || !form.properties.trim()}
          onClick={() => void save()}>
          {busy ? "Saving…" : "Save map…"}
        </button>
        <button type="button" className="btn btn-sm" disabled={busy} onClick={() => setForm(EMPTY_FORM)}>
          Clear
        </button>
      </div>
      {picking ? (
        <ComponentPickDialog
          line={{ label: picking === "part" ? "The internal part" : "The item it is a state of" }}
          title={picking === "part" ? "Choose the internal part" : "Choose the item"}
          confirmLabel="Choose"
          onPick={(id) => void pick(picking, id)}
          onClose={() => setPicking(null)}
        />
      ) : null}
    </FoldSection>
  );
}

/** Rows the backfill writes, as one sentence. */
function backfillSentence(r: CompanyBackfillResult, verb: string): string {
  return `${verb} ${r.ownership.length} ownership period(s), ${r.runs.length} batch(es), ` +
    `${r.orders.length} order(s) and ${r.memberships.length} user(s).`;
}

function backfillSize(r: CompanyBackfillResult): number {
  return r.ownership.length + r.runs.length + r.orders.length + r.memberships.length;
}

export function CompanyBackfillCard() {
  const [open, setOpen] = useState(false);
  const [done, setDone] = useState("");

  return (
    <FoldSection title="Company backfill" count={null} foldKey="admin:jobs:company-backfill">
      <p className="muted dim">
        Gives the older data its companies (decision 0063). You run it once per deployment. A row that has a
        company stays as it is, so a second run writes nothing.
      </p>
      {done ? <div className="banner-ok">{done}</div> : null}
      <div className="btn-row">
        <button type="button" className="btn btn-sm" onClick={() => setOpen(true)}>Company backfill…</button>
      </div>
      {open ? (
        <DryRunDialog<CompanyBackfillResult>
          title="Company backfill"
          intro={
            "CE_Dongle_V2, CE_Aqua_V2 and CE_Dongle_V3 go to 9Sigma, and every other project to 7Sigma. CE_Dongle_V2 " +
            "and CE_Aqua_V2 stay 7Sigma's until 9Sigma started. A batch takes the company that sold its devices, or " +
            "else its project's owner on its date. An order takes the seller its invoices name, or else the owner. " +
            "A user with no company gets both. Preview writes nothing."
          }
          fields={null}
          run={async (dry) => {
            const r = await companyBackfill(dry);
            if (!dry) setDone(backfillSentence(r, "Wrote"));
            return r;
          }}
          describe={(r) => (backfillSize(r) === 0 && r.unresolved.length === 0
            ? <>Nothing to write. Every project, batch, order and user has a company.</>
            : (
              <>
                {backfillSentence(r, "Writes")}{" "}
                {r.unresolved.length
                  ? "No company for: " +
                    r.unresolved.map((u) => `${u.run ?? `order ${u.order_id}`} (${u.why})`).join("; ") + "."
                  : ""}
              </>
            ))}
          canApply={(r) => backfillSize(r) > 0}
          applyLabel={(r) => (backfillSize(r) ? `Write ${backfillSize(r)} row(s)` : "Apply")}
          onClose={() => setOpen(false)}
        />
      ) : null}
    </FoldSection>
  );
}

export function RecomputeChecksCard() {
  const dialog = useDialog();
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [projectId, setProjectId] = useState<number | null>(null);
  const [runId, setRunId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [done, setDone] = useState("");

  useEffect(() => {
    const ac = new AbortController();
    getProjects(ac.signal)
      .then(setProjects)
      .catch((e) => {
        if (!isAbortError(e)) setErr(errorMessage(e));
      });
    return () => ac.abort();
  }, []);

  const run = async () => {
    const project = projects.find((p) => p.id === projectId);
    const scope = [project ? `project ${project.name}` : "", runId ? `programming run ${runId}` : ""]
      .filter(Boolean).join(" and ");
    if (!(await dialog.confirm(
      `Rebuild the checks of ${scope || "every programming run"}? For each finished run, this deletes its check ` +
        "rows and writes them again from the run's own steps and results. There is no dry run.",
      { title: "Re-compute programming checks", confirmLabel: "Rebuild" },
    ))) return;
    setBusy(true);
    setErr("");
    setDone("");
    try {
      const r = await recomputeChecks({ projectId, runId });
      setDone(`Rebuilt ${r.checks.toLocaleString()} check(s) on ${r.runs.toLocaleString()} run(s).`);
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <FoldSection title="Re-compute programming checks" count={null} foldKey="admin:jobs:recompute-checks">
      <p className="muted dim">
        A functional check is derived from a programming run&rsquo;s stored steps and results. After a change to how
        checks are read, this job upgrades the history. It skips a run that is still running. You can run it at any
        time. An empty scope means every run.
      </p>
      <ErrorBanner message={err} />
      {done ? <div className="banner-ok">{done}</div> : null}
      <FieldGrid>
        <Field label="Project">
          <select className="text" value={projectId ?? ""}
            onChange={(e) => setProjectId(e.target.value ? Number(e.target.value) : null)}>
            <option value="">every project</option>
            {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </Field>
        <Field label="Programming run" hint="Optional. The run's number.">
          <NumberInput className="text" value={runId} min={1} step={1} onChange={setRunId}
            onEmpty={() => setRunId(null)} />
        </Field>
      </FieldGrid>
      <div className="btn-row">
        <button type="button" className="btn btn-sm" disabled={busy} onClick={() => void run()}>
          {busy ? "Rebuilding…" : "Re-compute…"}
        </button>
      </div>
    </FoldSection>
  );
}
