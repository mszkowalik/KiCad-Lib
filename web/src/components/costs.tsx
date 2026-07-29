/** Shared cost-domain primitives: the line-kind list, the production-step
 *  select and the charge-to destination select. Each of these existed as
 *  three drifting literal copies before this file. */
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

/** Where a cost line's money goes: a batch (`run:<id>`), a project with no batch
 *  (`project:<id>`), nobody on purpose (`excluded`), or the empty value the
 *  caller words via `emptyLabel`. The value encoding is shared with the API
 *  helpers — do not re-derive it locally. */
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
