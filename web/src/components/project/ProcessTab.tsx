/** Project → Process (decisions 0058, 0059): how this product is made.
 *
 *  Four cards, top to bottom:
 *
 *  1. The VERSION — which one is shown, in effect since when, and the draft
 *     actions (edit as a new version, publish with a comment, delete).
 *  2. The MAP — the main route of steps, the steps off it, and the prepared
 *     parts with their stock; "Make…" on a prepared part runs its recipe. A
 *     draft is edited here instead.
 *  3. The LOTS of the prepared parts — where a write-off starts.
 *  4. The prepared-part TRANSFORMATIONS — what was made, when, at what cost.
 *
 *  Each number has one home: a batch is crafted on its own page (Batch →
 *  Floor), and the pool's figures for bought parts are on Stock → Parts.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  composeProcessVersion,
  deleteProcessDraft,
  errorMessage,
  getProjectProcess,
  getRuns,
  isAbortError,
  linkBenchRunsByTopic,
  makeProcessCurrent,
  publishProcessVersion,
  voidTransformation,
  type BenchLinkPlan,
  type PreparedRecipe,
  type PreparedStock,
  type ProjectInfo,
  type ProjectProcess,
  type RunInfo,
  type StageLot,
  type TransformationRow,
} from "../../api";
import { localDate, pln, usd } from "../../format";
import { useTodayRate } from "../../useTodayRate";
import DataTable, { type Column } from "../DataTable";
import { useDialog } from "../Dialog";
import Field from "../Field";
import FoldSection, { StatChip } from "../FoldSection";
import MakeDialog from "../process/MakeDialog";
import ProcessEditor from "../process/ProcessEditor";
import ProcessMap from "../process/ProcessMap";
import { BankDialog, DryRunDialog, StocktakeDialog, WriteOffDialog } from "../process/StageDialogs";
import { ErrorBanner, Spinner, StatusPill } from "../Ui";

type LotRow = StageLot & { stage: string };

/** Link old marking and test runs to their devices by the topic they captured
 *  (decision 0075 §1). This is the first step of rebuilding an old batch: the runs
 *  are the evidence a rebuild reads. It writes the link and records no step. */
function LinkBenchRunsDialog({ project, onClose }: { project: ProjectInfo; onClose: (c: boolean) => void }) {
  type Left = { run_id: number; kind: string; why: string; topic: string; started_at: string | null };
  const leftOf = (p: BenchLinkPlan): Left[] => [
    ...p.ambiguous.map((r) => ({ ...r, why: `${r.devices.length} devices match` })),
    ...p.unmatched.map((r) => ({ ...r, why: "no device matches" })),
    ...p.no_topic.map((r) => ({ ...r, why: "the run captured no topic", topic: "" })),
  ];
  return (
    <DryRunDialog<BenchLinkPlan>
      wide
      title="Link old bench runs"
      intro={`A marking or test run reads no MAC, so a run recorded before 2026-10-04 names no device. This links each such run of ${project.name} to its device by the topic it captured, only where the topic names exactly one device. It records no step: a rebuild reads the run as evidence. Do this before you rebuild a batch.`}
      onClose={onClose}
      run={(dry) => linkBenchRunsByTopic(project.id, dry)}
      canApply={(p) => p.linked.length > 0}
      applyLabel={(p) => `Link ${p.linked.length}`}
      describe={(p) => <>{p.linked.length} of {p.runs} run(s) with no device can be linked.</>}
      detail={(p) => {
        const left = leftOf(p);
        return (
          <>
            {p.devices_with_an_active_twin.length ? (
              <div className="banner-warn">
                {p.devices_with_an_active_twin.length} of these devices have an active twin. Its bench step is
                recorded when a later step or a merge catches it up.
              </div>
            ) : null}
            <FoldSection bare title="Runs to link" count={p.linked.length}
              chips={Object.entries(p.by_batch).slice(0, 4).map(([batch, n]) => <StatChip key={batch} n={n}>{batch}</StatChip>)}>
              <DataTable rows={p.linked} rowKey={(r) => r.run_id}
                columns={[
                  { key: "run", label: "Run", width: 9, numeric: true, get: (r) => r.run_id },
                  { key: "kind", label: "Kind", width: 8, get: (r) => r.kind },
                  { key: "topic", label: "Topic", width: 22, className: "mono", get: (r) => r.topic, title: (r) => r.topic },
                  { key: "device", label: "Device", width: 16, className: "mono", get: (r) => r.serial ?? String(r.device_id) },
                  { key: "batch", label: "Batch", width: 20, get: (r) => r.batch ?? "no batch", title: (r) => r.batch ?? "no batch" },
                  { key: "when", label: "Started", width: 13, className: "mono", get: (r) => localDate(r.started_at) },
                  { key: "status", label: "Status", width: 12, get: (r) => r.status, render: (r) => <StatusPill status={r.status} /> },
                ]} />
            </FoldSection>
            <FoldSection bare title="Runs that stay unlinked" count={left.length}
              chips={left.length ? <StatChip n={left.length} tone="warn">no single device</StatChip> : null}>
              <DataTable rows={left} rowKey={(r) => r.run_id} empty="Every run has its device."
                columns={[
                  { key: "run", label: "Run", width: 10, numeric: true, get: (r) => r.run_id },
                  { key: "kind", label: "Kind", width: 10, get: (r) => r.kind },
                  { key: "why", label: "Why", width: 34, get: (r) => r.why },
                  { key: "topic", label: "Topic", width: 30, className: "mono", get: (r) => r.topic, title: (r) => r.topic },
                  { key: "when", label: "Started", width: 16, className: "mono", get: (r) => localDate(r.started_at) },
                ]} />
            </FoldSection>
          </>
        );
      }}
      fields={null}
    />
  );
}

export default function ProcessTab({ project }: { project: ProjectInfo }) {
  const rate = useTodayRate();
  const dialog = useDialog();
  const [versionId, setVersionId] = useState<number | null>(null);
  const [data, setData] = useState<ProjectProcess | null>(null);
  const [runs, setRuns] = useState<RunInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [making, setMaking] = useState<PreparedRecipe | null>(null);
  const [banking, setBanking] = useState<PreparedStock | null>(null);
  const [counting, setCounting] = useState<PreparedStock | null>(null);
  const [writing, setWriting] = useState<LotRow | null>(null);
  const [linking, setLinking] = useState(false);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    const ac = new AbortController();
    getProjectProcess(project.id, versionId, ac.signal)
      .then((d) => { setData(d); setError(null); })
      .catch((err) => { if (!isAbortError(err)) setError(errorMessage(err)); });
    getRuns(project.id, ac.signal).then(setRuns).catch(() => undefined);
    return () => ac.abort();
  }, [project.id, versionId, tick]);

  const shown = data?.shown ?? null;
  const draft = data?.versions.find((v) => v.status === "draft") ?? null;
  const isCurrent = !!shown && shown.id === data?.current_version_id;

  const lotsByPart = useMemo(() => {
    const out: Record<number, StageLot[]> = {};
    for (const s of data?.stock?.prepared ?? []) out[s.component_id] = s.lots.filter((lt) => lt.open);
    return out;
  }, [data]);

  const lotRows: LotRow[] = useMemo(() => (data?.stock?.prepared ?? []).flatMap((s) =>
    s.lots.map((lt) => ({ ...lt, stage: s.name ?? String(s.component_id) }))), [data]);

  if (error) return <ErrorBanner message={error} />;
  if (!data) return <Spinner />;

  const compose = async (fromId: number | null) => {
    try {
      const v = await composeProcessVersion(project.id, fromId);
      setVersionId(v.id);
      reload();
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "Could not start a draft" });
    }
  };

  const publish = async (historical: boolean) => {
    if (!shown) return;
    const comment = await dialog.prompt(
      historical
        ? "How were the older devices made with this version, and which batches is it for? (required)"
        : "What changed, and why? (required — it is the version's history)",
      { title: historical ? `Publish process v${shown.version_no} as history` : `Publish process v${shown.version_no}`,
        initial: shown.comment, maxLength: 500 });
    if (comment === null) return;
    try {
      await publishProcessVersion(shown.id, comment, historical);
      setVersionId(null);
      reload();
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "Publishing was refused" });
    }
  };

  // Decision 0074: the version in effect is a pointer, not the newest number.
  const makeCurrent = async () => {
    if (!shown) return;
    if (!(await dialog.confirm(
      `Make v${shown.version_no} the version in effect? New batches and the project's planned BOM follow it. ` +
        "Batches that exist keep the version they run.",
      { title: "Make current", confirmLabel: "Make current" }))) return;
    try {
      await makeProcessCurrent(shown.id);
      setVersionId(null);
      reload();
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "Could not make it current" });
    }
  };

  const removeDraft = async () => {
    if (!shown) return;
    if (!(await dialog.confirm(`Delete draft v${shown.version_no}? Nothing published changes.`,
      { title: "Delete draft", confirmLabel: "Delete", tone: "danger" }))) return;
    try {
      await deleteProcessDraft(shown.id);
      setVersionId(null);
      reload();
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "Could not delete the draft" });
    }
  };

  const voidRow = async (t: TransformationRow) => {
    const reason = await dialog.prompt(
      `Void “${t.recipe_label}” of ${t.made_at} (${t.qty} made)? Its input draws are voided and its lot is removed. Why?`,
      { title: "Void transformation", confirmLabel: "Void", maxLength: 200 });
    if (!reason) return;
    try {
      await voidTransformation(t.id, reason);
      reload();
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "Voiding was refused" });
    }
  };

  if (!data.versions.length) {
    return (
      <div className="card pad">
        <h2 className="card-title">Process</h2>
        <p className="muted dim">
          No process yet. A process lists the steps a unit of {project.name} can go through —
          receive the board, add the antenna and the enclosure, program, mark, pack, finish —
          what each step needs before it and which parts it adds. Once it is published, every
          new batch is crafted step by step, and each device keeps its own history and price.
        </p>
        <button type="button" className="btn btn-primary" onClick={() => compose(null)}>Start the process</button>
      </div>
    );
  }

  const lotColumns: Column<LotRow>[] = [
    { key: "stage", label: "Prepared part", width: 17, get: (r) => r.stage },
    { key: "lot", label: "Lot", width: 7, className: "mono", get: (r) => `A${r.adjustment_id}` },
    { key: "date", label: "Date", width: 9, className: "mono", get: (r) => r.date },
    { key: "how", label: "From", width: 20, get: (r) => (r.transformation_id ? `transformation #${r.transformation_id}` : r.note || r.reason),
      title: (r) => r.note },
    { key: "qty", label: "Held", width: 7, numeric: true, get: (r) => r.qty },
    { key: "left", label: "Left", width: 7, numeric: true, get: (r) => r.remaining },
    { key: "unit", label: "Each", width: 8, numeric: true, get: (r) => r.unit_cost_usd, render: (r) => usd(r.unit_cost_usd) },
    { key: "value", label: "Value left", width: 13, numeric: true, get: (r) => r.value_remaining_usd,
      render: (r) => pln(r.value_remaining_usd, rate) },
    { key: "act", label: "", width: 12, interactive: false, get: () => "",
      render: (r) => (r.open && isCurrent
        ? <button type="button" className="btn btn-sm" onClick={() => setWriting(r)}>Write off…</button>
        : null) },
  ];

  const tColumns: Column<TransformationRow>[] = [
    { key: "date", label: "Date", width: 10, className: "mono", get: (t) => t.made_at },
    { key: "recipe", label: "Step", width: 14, get: (t) => t.recipe_label },
    { key: "out", label: "Made", width: 12, get: (t) => t.output_name ?? "" },
    { key: "qty", label: "Qty", width: 7, numeric: true, get: (t) => t.qty },
    { key: "scrap", label: "Scrap", width: 7, numeric: true, get: (t) => t.scrap },
    { key: "batch", label: "Batch", width: 12, get: (t) => t.run_label ?? "",
      render: (t) => (t.run_id ? <Link to={`/production/batches/${t.run_id}?tab=floor`}>{t.run_label}</Link> : <span className="muted">—</span>) },
    // Invoice positions aimed at this step on Finance → Purchase invoices (decision 0058 §4).
    { key: "conv", label: "Conversion", width: 12, numeric: true, get: (t) => t.conversion_usd,
      title: () => "Invoice positions aimed at this step as its conversion cost — set on Finance → Purchase invoices",
      render: (t) => (t.conversion_usd ? pln(t.conversion_usd, rate) : <span className="muted">—</span>) },
    { key: "unit", label: "Each", width: 8, numeric: true, get: (t) => t.unit_cost_usd ?? 0, render: (t) => usd(t.unit_cost_usd) },
    { key: "by", label: "By", width: 8, get: (t) => t.actor },
    { key: "act", label: "", width: 10, interactive: false, get: (t) => (t.voided ? "voided" : ""),
      render: (t) => (t.voided
        ? <span className="pill neutral" title={t.void_reason}>voided</span>
        : <button type="button" className="btn btn-sm" onClick={() => voidRow(t)}>Void…</button>) },
  ];

  return (
    <>
      <div className="card pad">
        <h2 className="card-title">Process</h2>
        <div className="toolbar">
          <Field label="Version">
            <select className="text" value={shown?.id ?? ""} onChange={(e) => setVersionId(Number(e.target.value) || null)}>
              {data.versions.map((v) => (
                <option key={v.id} value={v.id}>
                  v{v.version_no} · {v.status}{v.id === data.current_version_id ? " · in effect" : ""}
                </option>
              ))}
            </select>
          </Field>
          {shown ? <StatusPill status={shown.status} /> : null}
          {shown?.status === "published" && !draft ? (
            <button type="button" className="btn" onClick={() => compose(shown.id)}>Edit as new version</button>
          ) : null}
          {shown?.status === "published" && !isCurrent ? (
            <button type="button" className="btn" onClick={makeCurrent}>Make current…</button>
          ) : null}
          {draft && shown?.id !== draft.id ? (
            <button type="button" className="btn" onClick={() => setVersionId(draft.id)}>Open draft v{draft.version_no}</button>
          ) : null}
          {shown?.status === "draft" ? (
            <>
              <button type="button" className="btn btn-primary" disabled={!shown.check?.ok} onClick={() => publish(false)}>Publish…</button>
              <button type="button" className="btn" disabled={!shown.check?.ok} onClick={() => publish(true)}
                title="For the history of older devices: their batches pin it, and the version in effect stays">
                Publish as history…</button>
              <button type="button" className="btn btn-danger" onClick={removeDraft}>Delete draft</button>
            </>
          ) : null}
          <button type="button" className="btn" onClick={() => setLinking(true)}
            title="Link old marking and test runs to their devices, before you rebuild a batch">
            Link old bench runs…
          </button>
        </div>
        {shown ? (
          <p className="muted dim">
            {shown.status === "published"
              ? <>Published {shown.published_at ? localDate(shown.published_at) : ""} by {shown.approved_by}: {shown.comment.replace(/[.\s]*$/, ".")}</>
              : <>Draft started by {shown.created_by}. Publishing needs a comment and a clean check.</>}
            {shown.batches.length ? <> Batches on this version: {shown.batches.map((b) => b.label).join(", ")}.</> : null}
          </p>
        ) : null}
        {shown?.check && shown.status === "draft" ? (
          <>
            {shown.check.errors.length ? (
              <div className="banner-error">{shown.check.errors.map((e) => <div key={e}>{e}</div>)}</div>
            ) : <div className="banner-ok">The draft passes its check.</div>}
            {shown.check.warnings.length ? (
              <div className="banner-warn">{shown.check.warnings.map((w) => <div key={w}>{w}</div>)}</div>
            ) : null}
          </>
        ) : null}
      </div>

      {shown?.status === "draft" ? (
        <div className="card pad">
          <h2 className="card-title">Edit draft v{shown.version_no}</h2>
          <ProcessEditor
            key={shown.id}
            draft={shown}
            internalParts={data.internal_parts}
            deployments={data.deployments}
            onSaved={(v) => setData((d) => (d ? { ...d, shown: v } : d))}
            onPartCreated={reload}
          />
        </div>
      ) : null}

      {shown ? (
        <div className="card pad">
          <h2 className="card-title">Map</h2>
          {!isCurrent && shown.status === "published" ? (
            <p className="muted dim">Not the version in effect — read only. New batches run on the version in effect.</p>
          ) : null}
          <ProcessMap
            version={shown}
            prepared={data.stock?.prepared ?? null}
            deployments={data.deployments}
            stock={data.input_stock ?? {}}
            canMake={isCurrent}
            onMake={setMaking}
            onBank={setBanking}
            onStocktake={setCounting}
          />
        </div>
      ) : null}

      <FoldSection title="Lots" count={lotRows.length} foldKey={`project:${project.id}:lots`}
        chips={lotRows.length ? (
          <>
            <StatChip n={lotRows.filter((r) => r.open).length} tone="acc">open</StatChip>
            <StatChip n={pln(lotRows.reduce((a, r) => a + r.value_remaining_usd, 0), rate)}>value left</StatChip>
          </>
        ) : undefined}>
        <p className="muted dim">
          Stock of every prepared part, one row per lot. A lot is what one recipe run made, or
          what was banked. A step takes one lot per click, so the units it touches stay one pile.
        </p>
        <DataTable rows={lotRows} columns={lotColumns} rowKey={(r) => r.adjustment_id}
          empty="No prepared-part stock yet." defaultSort={{ key: "date", dir: "desc" }} />
      </FoldSection>

      <FoldSection title="Prepared parts made" count={data.transformations.length} foldKey={`project:${project.id}:made`}
        chips={data.transformations.length ? (
          <>
            <StatChip n={data.transformations.filter((t) => !t.voided).reduce((a, t) => a + t.qty, 0).toLocaleString()}>units made</StatChip>
            {data.transformations.some((t) => t.voided) ? <StatChip n={data.transformations.filter((t) => t.voided).length}>voided</StatChip> : null}
          </>
        ) : undefined}>
        <DataTable rows={data.transformations} columns={tColumns} rowKey={(t) => t.id}
          empty="No prepared part made yet." />
      </FoldSection>

      {making && shown ? (
        <MakeDialog projectId={project.id} version={shown} recipe={making} runs={runs}
          lotsByPart={lotsByPart}
          onClose={(made) => { setMaking(null); if (made) reload(); }} />
      ) : null}
      {banking ? (
        <BankDialog projectId={project.id} componentId={banking.component_id} name={banking.name ?? String(banking.component_id)}
          onClose={(c) => { setBanking(null); if (c) reload(); }} />
      ) : null}
      {counting ? (
        <StocktakeDialog projectId={project.id} componentId={counting.component_id}
          name={counting.name ?? String(counting.component_id)} onBooks={counting.on_hand}
          onClose={(c) => { setCounting(null); if (c) reload(); }} />
      ) : null}
      {writing ? (
        <WriteOffDialog projectId={project.id} lot={writing} name={writing.stage} runs={runs}
          onClose={(c) => { setWriting(null); if (c) reload(); }} />
      ) : null}
      {linking ? <LinkBenchRunsDialog project={project} onClose={(c) => { setLinking(false); if (c) reload(); }} /> : null}
    </>
  );
}
