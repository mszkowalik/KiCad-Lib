/** Approved alternates of a library part (decision 0108): the parts that may
 *  replace it in every project, the parts it may itself replace, and the
 *  projects that refuse one. One direction per row. Approving costs no
 *  verification, like a supplier link; Remove is the undo. */
import { useState } from "react";
import { Link } from "react-router-dom";
import {
  approveAlternate,
  blockAlternate,
  errorMessage,
  getComponentAlternates,
  getProjects,
  removeAlternate,
  unblockAlternate,
  updateAlternate,
  type AlternateBlockRow,
  type ComponentAlternateRow,
  type ComponentAlternates,
} from "../api";
import ComponentPickDialog from "./ComponentPickDialog";
import DataTable, { type Column } from "./DataTable";
import { useDialog } from "./Dialog";
import FoldSection, { StatChip } from "./FoldSection";
import { ErrorBanner } from "./Ui";
import { useLoad } from "./useLoad";

export default function AlternatesCard({ compId, name }: { compId: number; name: string }) {
  const dialog = useDialog();
  const { data, setData, error } = useLoad<ComponentAlternates>(
    (signal) => getComponentAlternates(compId, signal),
    [compId],
    { keep: true },
  );
  const [picking, setPicking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function run(fn: () => Promise<ComponentAlternates>) {
    setBusy(true);
    setErr(null);
    try {
      setData(await fn());
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function approve(altId: number | null) {
    setPicking(false);
    if (!altId) return;
    const note = await dialog.prompt(`Why may it replace ${name}? (shown to everybody who plans or buys it)`, {
      title: "Approve alternate",
      maxLength: 500,
      placeholder: "e.g. same value, case and voltage; ESR lower",
    });
    if (note === null) return;
    await run(() => approveAlternate(compId, { alternate_id: altId, note }));
  }

  async function block(r: ComponentAlternateRow) {
    const projects = await getProjects().catch(() => []);
    const pid = await dialog.select(
      `In which project must ${r.alternate_name} NOT replace ${r.component_name}?`,
      projects.map((p) => ({ value: String(p.id), label: p.name })),
      { title: "Refuse in a project", confirmLabel: "Next" },
    );
    if (!pid) return;
    // the prompt refuses an empty answer, so "every position" is a choice, not a blank
    const scope = await dialog.select("Where in that project?", [
      { value: "all", label: "Every position of the part" },
      { value: "some", label: "Some designators only" },
    ], { title: "Refuse in a project", confirmLabel: "Next" });
    if (!scope) return;
    let refs = "";
    if (scope === "some") {
      const typed = await dialog.prompt("Designators where the circuit cares:", {
        title: "Refuse in a project",
        maxLength: 200,
        placeholder: "C2, C5",
      });
      if (typed === null) return;
      refs = typed;
    }
    const note = await dialog.prompt("Why?", { title: "Refuse in a project", maxLength: 500 });
    if (note === null) return;
    await run(() => blockAlternate(Number(pid), {
      component_id: r.component_id, alternate_id: r.alternate_id, refs, note,
    }));
  }

  const rows = data?.alternates ?? [];
  const of = data?.alternate_of ?? [];
  const blocks = data?.blocks ?? [];

  const altCols: Column<ComponentAlternateRow>[] = [
    {
      key: "alternate_name",
      label: "May be replaced by",
      width: 27,
      get: (r) => r.alternate_name,
      render: (r) => (
        <Link className="comp-link mono" to={`/library/components/${r.alternate_id}`}>{r.alternate_name}</Link>
      ),
    },
    {
      key: "buy",
      label: "Buy",
      width: 7,
      className: "ctr",
      interactive: false,
      sortable: true,
      get: (r) => (r.buy ? "buy" : ""),
      title: () => "A purchase proposal for the part names this alternate. At most one per part.",
      render: (r) => (
        <input
          type="checkbox"
          checked={r.buy}
          disabled={busy}
          onChange={(e) => run(() => updateAlternate(compId, r.id, { buy: e.target.checked }))}
        />
      ),
    },
    { key: "note", label: "Why", width: 28, className: "muted", get: (r) => r.note || "—", title: (r) => r.note },
    { key: "created_by", label: "By", width: 13, className: "muted dim", get: (r) => r.created_by },
    {
      key: "actions",
      label: "",
      width: 25,
      interactive: false,
      get: () => "",
      render: (r) => (
        <span className="btn-row">
          <button className="btn btn-sm" disabled={busy} onClick={() => block(r)}
                  title="This project's circuit must keep the specified part">
            Refuse in…
          </button>
          <button className="btn btn-sm btn-danger" disabled={busy}
                  onClick={async () => {
                    if (await dialog.confirm(`Withdraw ${r.alternate_name} as an alternate of ${r.component_name}? `
                      + "Every project refusal of it goes too.", { tone: "danger", confirmLabel: "Withdraw" })) {
                      await run(() => removeAlternate(compId, r.id));
                    }
                  }}>
            ×
          </button>
        </span>
      ),
    },
  ];

  const blockCols: Column<AlternateBlockRow>[] = [
    {
      key: "project_name",
      label: "Project refuses",
      width: 24,
      get: (b) => b.project_name,
      render: (b) => <Link className="comp-link" to={`/projects/${b.project_id}`}>{b.project_name}</Link>,
    },
    { key: "pair", label: "Alternate", width: 34, className: "mono",
      get: (b) => `${b.alternate_name} for ${b.component_name}` },
    { key: "refs", label: "At", width: 12, className: "mono", get: (b) => b.refs || "everywhere" },
    { key: "note", label: "Why", width: 24, className: "muted", get: (b) => b.note || "—" },
    {
      key: "actions",
      label: "",
      width: 6,
      interactive: false,
      get: () => "",
      render: (b) => (
        <button className="btn btn-sm" disabled={busy} title="Allow the alternate in this project again"
                onClick={() => run(() => unblockAlternate(b.project_id, b.id))}>
          ×
        </button>
      ),
    },
  ];

  return (
    <FoldSection
      title="Approved alternates"
      count={rows.length + of.length + blocks.length}
      foldKey={`component:${compId}:alternates`}
      chips={
        <>
          {rows.length ? <StatChip n={rows.length}>approved</StatChip> : null}
          {of.length ? <StatChip n={of.length}>replaces</StatChip> : null}
          {blocks.length ? <StatChip n={blocks.length} tone="warn">refused</StatChip> : null}
        </>
      }
      actions={
        <button className="btn btn-sm" disabled={busy} onClick={() => setPicking(true)}>
          Approve alternate…
        </button>
      }
    >
      {error || err ? <ErrorBanner message={error || err || ""} /> : null}
      <p className="muted dim">
        An approved alternate may replace this part in every project without a schematic change: its stock and
        purchases count as this part in a plan, and a batch that fitted it raises no finding. One direction only.
      </p>
      {rows.length ? <DataTable rows={rows} columns={altCols} rowKey={(r) => String(r.id)} /> : null}
      {of.length ? (
        <p className="muted">
          May itself replace:{" "}
          {of.map((r, i) => (
            <span key={r.id}>
              {i ? ", " : ""}
              <Link className="comp-link mono" to={`/library/components/${r.component_id}`}>{r.component_name}</Link>
            </span>
          ))}
        </p>
      ) : null}
      {blocks.length ? <DataTable rows={blocks} columns={blockCols} rowKey={(b) => String(b.id)} /> : null}
      {picking ? (
        <ComponentPickDialog
          line={{ kind: "an alternate" }}
          title={`Approve an alternate of ${name}`}
          confirmLabel="Next"
          onClose={() => setPicking(false)}
          onPick={(id) => approve(id)}
        />
      ) : null}
    </FoldSection>
  );
}
