/** One card that holds a list or a group, and folds it when it is long
 *  (decision 0103).
 *
 *  The rule is the same on every page: a secondary list with more than
 *  `FOLD_LIMIT` rows starts folded, and the folded line says what the list holds
 *  — the title, the count, up to four `StatChip`s and the main action. A count
 *  that needs action goes in an amber or red chip, so a fold never hides a
 *  problem. A short list has no toggle at all: there is nothing to save.
 *
 *  The main list of a page does not use this. It keeps its rows and puts the same
 *  chips above its filter row.
 *
 *  The children render only while open, so a folded list of 1,000 devices costs
 *  no DOM. `foldKey` remembers the choice across a reload (see `readOpen`).
 */
import { useState, type ReactNode } from "react";

import { readOpen, writeOpen } from "../scrollRestore";

/** Fold a list above this many rows. One number for the whole platform. */
export const FOLD_LIMIT = 8;

export type ChipTone = "ok" | "warn" | "err" | "acc";

/** A count and its word. A number with no meaning alone is the point of a chip,
 *  so `n` comes first and is drawn apart from the word. */
export function StatChip({ n, tone, children, on, onClick, title }: {
  n?: ReactNode;
  tone?: ChipTone;
  children?: ReactNode;
  /** a chip that filters a main list: it is on */
  on?: boolean;
  onClick?: () => void;
  title?: string;
}) {
  const cls = `stat-chip${tone ? ` ${tone}` : ""}${on ? " on" : ""}`;
  const body = <>{n !== undefined ? <b>{n}</b> : null}{children ? <span>{children}</span> : null}</>;
  return onClick
    ? <button type="button" className={cls} title={title} onClick={onClick}>{body}</button>
    : <span className={cls} title={title}>{body}</span>;
}

/** A chip that narrows a main list to one value. A second click takes it off
 *  again, and the list goes back to `off`. */
export function NarrowChip<V extends string>({ value, current, onNarrow, off = "" as V, ...chip }: {
  value: V;
  current: V;
  onNarrow: (next: V) => void;
  off?: V;
  n?: ReactNode;
  tone?: ChipTone;
  children?: ReactNode;
  title?: string;
}) {
  return <StatChip {...chip} on={current === value} onClick={() => onNarrow(current === value ? off : value)} />;
}

export default function FoldSection({
  title, count, chips, actions, foldKey, limit = FOLD_LIMIT, forceOpen, bare, children,
}: {
  title: ReactNode;
  /** the rows it holds; above `limit` it starts folded. `null`: not known until
   *  it opens, because its children load on mount. It starts folded, prints no
   *  count, and the list costs nobody a request until somebody asks for it. */
  count: number | null;
  chips?: ReactNode;
  /** the list's main action: stays visible while folded */
  actions?: ReactNode;
  /** remembers open or folded across a reload; unique per list */
  foldKey?: string;
  limit?: number;
  /** a link that names a row in this list opens it */
  forceOpen?: boolean;
  /** no card of its own: a list inside another card */
  bare?: boolean;
  children: ReactNode;
}) {
  const foldable = count === null || count > limit;
  const [open, setOpenState] = useState<boolean>(() => (foldKey ? readOpen(foldKey) === "1" : false));
  // The same card can show another record (a link from one component to the
  // next), so a new key reads its own remembered state.
  const [seenKey, setSeenKey] = useState(foldKey);
  if (seenKey !== foldKey) {
    setSeenKey(foldKey);
    setOpenState(foldKey ? readOpen(foldKey) === "1" : false);
  }
  const setOpen = (next: boolean) => {
    setOpenState(next);
    if (foldKey) writeOpen(foldKey, next ? "1" : null);
  };
  const shown = !foldable || open || !!forceOpen;
  const head = (
    <>
      <span className="fold-title">
        {foldable ? <span className="fold-caret" aria-hidden="true">{shown ? "▾" : "▸"}</span> : null}
        <h2 className="card-title">{title}</h2>
      </span>
      {count === null ? null : <span className="fold-count">{count.toLocaleString()}</span>}
      {chips}
    </>
  );
  return (
    <div className={bare ? "fold-bare" : "card pad"}>
      <div className="fold-bar">
        {foldable ? (
          <button type="button" className="fold-toggle" aria-expanded={shown} onClick={() => setOpen(!shown)}>
            {head}
          </button>
        ) : (
          <div className="fold-toggle">{head}</div>
        )}
        {actions}
      </div>
      {shown ? <div className="fold-body">{children}</div> : null}
    </div>
  );
}
