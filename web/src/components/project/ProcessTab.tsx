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
 *  Process), and the pool's figures for bought parts are on the Stock page.
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
  makeProcessCurrent,
  publishProcessVersion,
  voidTransformation,
  type PreparedRecipe,
  type PreparedStock,
  type ProjectInfo,
  type ProjectProcess,
  type RunInfo,
  type StageLot,
  type TransformationRow,
} from "../../api";
import { usd } from "../../format";
import DataTable, { type Column } from "../DataTable";
import { useDialog } from "../Dialog";
import Field from "../Field";
import MakeDialog from "../process/MakeDialog";
import ProcessEditor from "../process/ProcessEditor";
import ProcessMap from "../process/ProcessMap";
import { BankDialog, StocktakeDialog, WriteOffDialog } from "../process/StageDialogs";
import { ErrorBanner, Spinner, StatusPill } from "../Ui";

type LotRow = StageLot & { stage: string };

export default function ProcessTab({ project }: { project: ProjectInfo }) {
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
    { key: "stage", label: "Prepared part", width: 20, get: (r) => r.stage },
    { key: "lot", label: "Lot", width: 6, className: "mono", get: (r) => `A${r.adjustment_id}` },
    { key: "date", label: "Date", width: 9, className: "mono", get: (r) => r.date },
    { key: "how", label: "From", width: 24, get: (r) => (r.transformation_id ? `transformation #${r.transformation_id}` : r.note || r.reason),
      title: (r) => r.note },
    { key: "qty", label: "Held", width: 6, numeric: true, get: (r) => r.qty },
    { key: "left", label: "Left", width: 6, numeric: true, get: (r) => r.remaining },
    { key: "unit", label: "Each", width: 8, numeric: true, get: (r) => r.unit_cost_usd, render: (r) => usd(r.unit_cost_usd) },
    { key: "value", label: "Value left", width: 9, numeric: true, get: (r) => r.value_remaining_usd,
      render: (r) => usd(r.value_remaining_usd) },
    { key: "act", label: "", width: 12, interactive: false, get: () => "",
      render: (r) => (r.open && isCurrent
        ? <button type="button" className="btn btn-sm" onClick={() => setWriting(r)}>Write off…</button>
        : null) },
  ];

  const tColumns: Column<TransformationRow>[] = [
    { key: "date", label: "Date", width: 10, className: "mono", get: (t) => t.made_at },
    { key: "recipe", label: "Step", width: 16, get: (t) => t.recipe_label },
    { key: "out", label: "Made", width: 16, get: (t) => t.output_name ?? "" },
    { key: "qty", label: "Qty", width: 6, numeric: true, get: (t) => t.qty },
    { key: "scrap", label: "Scrap", width: 6, numeric: true, get: (t) => t.scrap },
    { key: "batch", label: "Batch", width: 12, get: (t) => t.run_label ?? "",
      render: (t) => (t.run_id ? <Link to={`/runs/${t.run_id}?tab=process`}>{t.run_label}</Link> : <span className="muted">—</span>) },
    // Invoice positions aimed at this step on the Invoices page (decision 0058 §4).
    { key: "conv", label: "Conversion", width: 8, numeric: true, get: (t) => t.conversion_usd,
      title: () => "Invoice positions aimed at this step as its conversion cost — set on the Invoices page",
      render: (t) => (t.conversion_usd ? usd(t.conversion_usd) : <span className="muted">—</span>) },
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
        </div>
        {shown ? (
          <p className="muted dim">
            {shown.status === "published"
              ? <>Published {shown.published_at ? new Date(shown.published_at).toLocaleDateString("sv-SE") : ""} by {shown.approved_by}: {shown.comment.replace(/[.\s]*$/, ".")}</>
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
            canMake={isCurrent}
            onMake={setMaking}
            onBank={setBanking}
            onStocktake={setCounting}
          />
        </div>
      ) : null}

      <div className="card pad">
        <h2 className="card-title">Lots</h2>
        <p className="muted dim">
          Stock of every prepared part, one row per lot. A lot is what one recipe run made, or
          what was banked. A step takes one lot per click, so the units it touches stay one pile.
        </p>
        <DataTable rows={lotRows} columns={lotColumns} rowKey={(r) => r.adjustment_id}
          empty="No prepared-part stock yet." defaultSort={{ key: "date", dir: "desc" }} />
      </div>

      <div className="card pad">
        <h2 className="card-title">Prepared parts made</h2>
        <DataTable rows={data.transformations} columns={tColumns} rowKey={(t) => t.id}
          empty="No prepared part made yet." />
      </div>

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
    </>
  );
}
