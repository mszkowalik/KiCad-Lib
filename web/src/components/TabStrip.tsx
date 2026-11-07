/** One strip of tabs, the same on every page. A strip with more than 7 tabs gets
 *  group labels (decision 0103): pass `group` on the first tab of each group. The
 *  page owns the value, because a tab belongs in the URL.
 */
import { Fragment, type ReactNode } from "react";

export interface TabDef<T extends string> {
  id: T;
  label: ReactNode;
  /** starts a group, with this word before it */
  group?: string;
}

export default function TabStrip<T extends string>({ tabs, value, onChange, label }: {
  tabs: readonly TabDef<T>[];
  value: T;
  onChange: (id: T) => void;
  /** what the strip is, for a screen reader */
  label: string;
}) {
  return (
    <div className={`seg proj-tabs${tabs.some((t) => t.group) ? " grouped" : ""}`} role="tablist" aria-label={label}>
      {tabs.map((t) => (
        <Fragment key={t.id}>
          {t.group ? <span className="seg-group">{t.group}</span> : null}
          <button type="button" role="tab" aria-selected={value === t.id}
            className={value === t.id ? "on" : ""} onClick={() => onChange(t.id)}>
            {t.label}
          </button>
        </Fragment>
      ))}
    </div>
  );
}
