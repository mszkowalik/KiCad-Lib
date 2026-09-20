/** Shared cost-domain primitives: the line-kind list, the production-step
 *  select and the charge-to destination select. Each of these existed as
 *  three drifting literal copies before this file. */
import { useId } from "react";
import type { ReactNode } from "react";
import type { CostLineKind, CostStepCatalog } from "../api";

export const COST_LINE_KINDS: CostLineKind[] = [
  "part", "fab", "assembly", "tooling", "freight",
  "duty", "tax", "rework", "packaging", "service", "other",
];

/** A run a cost line can be charged to, with its project named for display. */
export interface RunOption {
  id: number;
  label: string;
  project_id: number;
  project_name: string;
}

export interface ProjectOption {
  id: number;
  name: string;
}

/** The production-step catalog as a select, grouped by stage (fab → pcba →
 *  final). `useLabels` switches the option text from the mono step key (dense
 *  tables) to the human label (forms). Extra options — e.g. "link to a plan
 *  item…" — go in as children and come back through onChange as their value. */
export function StepSelect({
  catalog,
  value,
  onChange,
  emptyLabel = "— no step —",
  useLabels = false,
  className = "row-input",
  disabled,
  title,
  children,
}: {
  catalog: CostStepCatalog | null;
  value: string;
  onChange: (value: string) => void;
  emptyLabel?: string;
  useLabels?: boolean;
  className?: string;
  disabled?: boolean;
  title?: string;
  children?: ReactNode;
}) {
  return (
    <select
      className={className}
      value={value}
      disabled={disabled}
      title={title}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">{emptyLabel}</option>
      {Object.entries(catalog?.stages ?? {}).map(([stage, stageLabel]) => (
        <optgroup key={stage} label={stageLabel}>
          {(catalog?.steps ?? [])
            .filter((st) => st.stage === stage)
            .map((st) => (
              <option key={st.key} value={st.key}>
                {useLabels ? st.label : st.key}
              </option>
            ))}
        </optgroup>
      ))}
      {children}
    </select>
  );
}

/** WHERE a cost line's money goes — the first of the two questions an invoice
 *  position has to answer (decision 0045).
 *
 *  Every option names an outcome, and there is no silent default. The control
 *  this replaces offered one empty value, worded "— nobody —", which resolved to
 *  FIVE different things depending on the line's `kind`, the line's `allocate`
 *  and the document's own destination — none of which were on screen. A `part`
 *  line left alone went to the shared pool; a `freight` line left alone became
 *  money nobody paid for.
 *
 *  `inherit` is only offered when the DOCUMENT names a destination of its own.
 *  Leaving it selected keeps the line storing nothing, exactly as today — it is
 *  here so that "the document decides" is a thing you can read, rather than the
 *  same blank that means "nobody has decided".
 */
export type GoesTo = "" | "inherit" | "pool" | "nobody" | string;

export function GoesToSelect({
  runs, projects, value, onChange, docDefault = "",
  className = "row-input", disabled,
}: {
  runs: RunOption[];
  projects: ProjectOption[];
  value: GoesTo;
  onChange: (value: GoesTo) => void;
  /** what the DOCUMENT charges to, worded, when it names anything */
  docDefault?: string;
  className?: string;
  disabled?: boolean;
}) {
  // A PROFORMA's positions are not special here. `line_destination` does not
  // look at `doc_type`, so a proforma part line reports "pool" like any other —
  // what makes a proforma different is that `_pool_events` skips the whole
  // document, which is the document's business and not the line's. Hiding the
  // option made the Italtronic proforma read "not decided" beside a register row
  // saying "pool: 1,651.00".
  return (
    <select
      className={`${className}${value === "" ? " needs-answer" : ""}`}
      value={value}
      disabled={disabled}
      title={value === "" ? "Nobody pays for this position yet — the register "
        + "reports it as unassigned money" : undefined}
      onChange={(e) => onChange(e.target.value)}
    >
      {/* Not an option anybody should pick, and not hidden either: the rows that
          are already in this state have to be selectable so they can be read. */}
      <option value="">⬦ not decided</option>
      {docDefault ? <option value="inherit">from this document ({docDefault})</option> : null}
      <option value="pool">Stock — the shared pool</option>
      {runs.map((r) => (
        <option key={`run:${r.id}`} value={`run:${r.id}`}>
          {r.project_name} · {r.label}
        </option>
      ))}
      {projects.map((p) => (
        <option key={`project:${p.id}`} value={`project:${p.id}`}>
          {p.name} (no batch)
        </option>
      ))}
      <option value="nobody">Nobody, on purpose</option>
    </select>
  );
}

/** HOW the money reaches wherever it is going — the second question, and the
 *  one that had no control at all (decision 0045).
 *
 *  It carries a different stored field for each destination, because "how" means
 *  a different thing for each, and all three were previously unreachable from
 *  the browser:
 *
 *  | Goes to | writes | choices |
 *  |---|---|---|
 *  | Stock | `allocate` | it IS stock · spread over this document's parts by value / by quantity |
 *  | a batch or project | `basis` | as its own amount · per device x units built |
 *  | Nobody | `exclude_reason` | a short reason, typed |
 *
 *  `basis` was hard-coded `per_run` in the line table and `allocate` was only
 *  ever written as `excluded`, so a transport line on a parts invoice could not
 *  be marked as landed cost at all — it silently became unassigned money.
 */
// Worded to FIT. The column is 14% wide and a select cannot be ellipsised
// usefully — "it is stock" rendered as "it is s…", which says nothing. The long
// form goes in the title instead.
export const HOW_FOR_STOCK = [
  ["pooled", "stock", "This position IS stock. It enters the shared pool and every project draws from it."],
  ["by_value", "spread by value", "Landed cost: spread over this document's part lines in proportion to their value, so it raises what that stock really cost to arrive."],
  ["by_qty", "spread by qty", "Landed cost: spread over this document's part lines per piece."],
] as const;

export const HOW_FOR_CHARGE = [
  ["per_run", "own amount", "Charged once, as the amount printed on the invoice."],
  ["per_device", "per device", "A rate per board: charged at this amount times the units the batch was billed for."],
] as const;

/** The reasons in use, offered as suggestions and NOT as a closed list.
 *
 *  A select here would refuse the first honest reason nobody thought of, and
 *  the API takes free text for that reason. But an unlabelled exclusion is
 *  invisible — `excluded` passes every check the register has — so 44 positions
 *  reached production saying nothing at all, and consistency is what makes
 *  `excluded_by_reason_usd` readable instead of a list of near-synonyms.
 *  The vocabulary itself is in the production-run skill. */
export const EXCLUDE_REASONS: readonly (readonly [string, string])[] = [
  ["reclaimable_vat", "import VAT and customs — everything here is recorded net"],
  ["prepaid_components", "already paid for and already in the pool"],
  ["external_project", "a product this platform does not track"],
  ["cancelled_by_supplier", "printed, then cancelled — nobody delivered it"],
  ["payment_fee", "a transfer charge no product should carry"],
] as const;

/** WHY a position is charged to nobody. Used by the line table's "How" column
 *  and by the split dialog, because a share can be excluded from either and the
 *  split dialog could not state a reason at all until 2026-09-21. */
export function ExcludeReasonInput({
  value, onChange, className = "row-input", disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  className?: string;
  disabled?: boolean;
}) {
  // A `<datalist>` per input, with an id from `useId`. One shared id would be
  // the obvious thing and is invalid HTML the moment a document has two
  // excluded positions — nine copies of `id="exclude-reasons"` appeared on the
  // first invoice tried. Five options per instance is nothing.
  const listId = useId();
  return (
    <>
      <input
        className={`${className}${value.trim() ? "" : " needs-answer"}`}
        value={value}
        disabled={disabled}
        list={listId}
        placeholder="why? e.g. reclaimable_vat"
        title="Money recorded so the document adds up and charged to nobody on
purpose. The reason is what makes it auditable rather than merely missing, and
the API refuses an exclusion without one."
        onChange={(e) => onChange(e.target.value)}
      />
      <datalist id={listId}>
        {EXCLUDE_REASONS.map(([v, hint]) => (
          <option key={v} value={v} label={hint} />
        ))}
      </datalist>
    </>
  );
}

export function HowSelect({
  goesTo, value, onChange, onReasonChange, reason = "", isPart = false,
  className = "row-input", disabled,
}: {
  goesTo: GoesTo;
  value: string;
  onChange: (value: string) => void;
  onReasonChange?: (value: string) => void;
  reason?: string;
  /** only a `part` line can BE stock; anything else can only be spread onto it */
  isPart?: boolean;
  className?: string;
  disabled?: boolean;
}) {
  if (goesTo === "nobody") {
    return (
      <ExcludeReasonInput
        value={reason}
        disabled={disabled}
        className={className}
        onChange={(v) => onReasonChange?.(v)}
      />
    );
  }
  // Nothing has been decided yet, so there is no second question to ask.
  if (goesTo === "") return <span className="muted">—</span>;
  const opts = goesTo === "pool"
    // A non-part cannot BE stock; it can only ride onto the stock as landed
    // cost. Offering "it is stock" for a freight line would produce a pool
    // entry with no part behind it.
    ? HOW_FOR_STOCK.filter(([v]) => v !== "pooled" || isPart)
    : HOW_FOR_CHARGE;
  const why = opts.find(([v]) => v === value)?.[2];
  return (
    <select className={className} value={value} disabled={disabled} title={why}
            onChange={(e) => onChange(e.target.value)}>
      {opts.map(([v, label, why]) => (
        <option key={v} value={v} title={why}>{label}</option>
      ))}
    </select>
  );
}

/** Where a cost line's money goes: a batch (`run:<id>`), a project with no batch
 *  (`project:<id>`), nobody on purpose (`excluded`), or the empty value the
 *  caller words via `emptyLabel`. The value encoding is shared with the API
 *  helpers — do not re-derive it locally.
 *
 *  Kept for the NEW-invoice header's "charge every position to" field, which
 *  genuinely is one destination applied to a whole document and has no second
 *  question to ask. The per-line control is `GoesToSelect` above. */
export function ChargeToSelect({
  runs,
  projects,
  value,
  onChange,
  emptyLabel = "— nobody —",
  withExcluded = true,
  className = "row-input",
  disabled,
}: {
  runs: RunOption[];
  projects: ProjectOption[];
  value: string;
  onChange: (value: string) => void;
  emptyLabel?: string;
  withExcluded?: boolean;
  className?: string;
  disabled?: boolean;
}) {
  return (
    <select
      className={className}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">{emptyLabel}</option>
      {runs.map((r) => (
        <option key={`run:${r.id}`} value={`run:${r.id}`}>
          {r.project_name} · {r.label}
        </option>
      ))}
      {projects.map((p) => (
        <option key={`project:${p.id}`} value={`project:${p.id}`}>
          {p.name} (no batch)
        </option>
      ))}
      {withExcluded && <option value="excluded">nobody, on purpose (excluded)</option>}
    </select>
  );
}
