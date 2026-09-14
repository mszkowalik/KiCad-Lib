import { useState } from "react";
import type { ReviewPart } from "../api";
import { readOpen, writeOpen } from "../scrollRestore";
import ReviewCard from "./ReviewCard";
import { ReviewPill } from "./Ui";

export type SubjectKey = "component" | "symbol" | "footprint";

export interface SubjectRow {
  key: SubjectKey;
  label: string;
  id: number | null;
}

/**
 * A component's three verification subjects, one collapsible row each.
 *
 * Shared by the component page and the review workbench because the fold rule
 * is a RULE, not a layout detail: the workbench stacked all three cards open,
 * so the checklist somebody came for started one and a half screens down, below
 * two other subjects' checks (user report 2026-09-14).
 *
 * Three things it gets right, each of which took a report to learn:
 *
 * - **Every row starts CLOSED, whatever its state.** A failing row used to open
 *   itself; that guesses which subject the reader came for, and guesses wrong
 *   on every part that is merely `partial`. See `components/CLAUDE.md`,
 *   "Count the folds between a state and the control that changes it".
 * - **Only ONE row opens at a time.** The three are read one after another, not
 *   side by side, and stacking them is what the workbench already proved bad.
 * - **The whole head is the target**, not the caret. A 20px triangle beside a
 *   clickable-looking label reads as no target at all.
 *
 * The card MOUNTS on expand, so its fetch only happens when somebody is
 * actually verifying — which is also why a closed workbench costs three
 * requests fewer than it used to.
 */
export default function ReviewSubjectRows({
  rows,
  parts,
  onChanged,
  storageKey,
}: {
  rows: SubjectRow[];
  parts: Partial<Record<SubjectKey, ReviewPart>>;
  onChanged?: () => void;
  /** Remembers which row was open across a reload. Restoring the scroll offset
   *  alone would put the reader at the same pixel with the section they had
   *  expanded closed again — the content that was there is somewhere else. */
  storageKey?: string;
}) {
  const [open, setOpenState] = useState<SubjectKey | null>(
    () => (storageKey ? (readOpen(storageKey) as SubjectKey | null) : null),
  );
  const setOpen = (next: SubjectKey | null) => {
    setOpenState(next);
    if (storageKey) writeOpen(storageKey, next);
  };
  return (
    <ul className="notes-list">
      {rows.map((r) => (
        <li key={r.key} className="note">
          <div
            className="note-head clickable"
            role="button"
            tabIndex={0}
            onClick={() => setOpen(open === r.key ? null : r.key)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                setOpen(open === r.key ? null : r.key);
              }
            }}
          >
            <span aria-hidden>{open === r.key ? "▾" : "▸"}</span> <span>{r.label}</span>{" "}
            <ReviewPill state={parts[r.key]?.state} provenance={parts[r.key]?.provenance ?? null} />
          </div>
          {open === r.key && r.id !== null ? (
            <ReviewCard kind={r.key} id={r.id} label={r.label} onChange={onChanged} />
          ) : null}
        </li>
      ))}
    </ul>
  );
}
