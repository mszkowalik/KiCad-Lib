/** The process as a board (decision 0103): each step is a field on a path, and
 *  an arrow leads to the next one. The path runs left to right, turns down, and
 *  runs back, 5 fields to a row, so a route of 10 fits one screen. The number on
 *  a field gives the order, so the turn does not hide it.
 *
 *  One component draws every view of a process, so they cannot drift apart about
 *  what a step is:
 *
 *  - LIVE, on the batch page: the figures of `twins.board`.
 *  - PLAN, on the project's Process tab: the same fields from a version and the
 *    stock of its inputs, coloured against a number of devices.
 *  - MINI, in lists: one small square per field.
 *
 *  **Every figure comes from the server.** The pool, the company and the lots
 *  decide the stock, so a page that computed "can go now" could disagree with the
 *  click it is about to make.
 */
import { Fragment, type ReactNode } from "react";
import { STEP_STATION, type BoardState, type BoardStep, type StepKind } from "../../api";
import type { ChipTone } from "../FoldSection";

/** Kinds done at a bench: their action is a link, never a click here. */
const BENCH_KINDS: StepKind[] = ["program", "test", "mark_laser", "label"];

export function isBench(kind: StepKind): boolean {
  return BENCH_KINDS.includes(kind);
}

/** One field, in either mode. Plan mode leaves the unit figures out. */
export interface BoardField {
  key: string;
  label: string;
  kind: StepKind;
  required: boolean;
  /** "choice: branding" */
  note?: string;
  state: BoardState;
  needsText?: string;
  beforeText?: string;
  unit?: { done: number; total: number; waiting: number; canGo: number };
  stock: { name: string; line: ReactNode; tone: ChipTone }[];
  procedure?: ReactNode;
}

export function stockTone(covers: number | null, needed: number): ChipTone {
  if (covers === null) return "ok";
  if (needed > 0 && covers <= 0) return "err";
  return covers < needed ? "warn" : "ok";
}

/** The fields of a batch, from its board figures. */
export function liveFields(steps: BoardStep[]): BoardField[] {
  const label = (k: string) => steps.find((s) => s.key === k)?.label ?? k;
  return steps.map((s) => ({
    key: s.key,
    label: s.label,
    kind: s.kind,
    required: s.required,
    state: s.state,
    needsText: s.needs.map(label).join(", "),
    unit: { done: s.done, total: s.total, waiting: s.waiting, canGo: s.can_go },
    stock: s.inputs.map((i) => ({
      name: i.name,
      line: <b>{Math.floor(i.on_hand).toLocaleString()}</b>,
      tone: stockTone(i.covers, s.still_to_do),
    })),
    procedure: s.procedure
      ? <>{s.procedure.name}{s.procedure.version_no ? ` v${s.procedure.version_no}` : " (nothing published)"}</>
      : undefined,
  }));
}

function Field({ f, n, selected, onSelect, action, extra }: {
  f: BoardField;
  n?: number;
  selected?: boolean;
  onSelect?: (key: string) => void;
  action?: ReactNode;
  extra?: ReactNode;
}) {
  const pct = f.unit && f.unit.total ? Math.round((100 * f.unit.done) / f.unit.total) : 0;
  const open = () => onSelect?.(f.key);
  return (
    <div
      className={`pf ${f.state}${f.required ? "" : " optional"}${onSelect ? " clickable" : ""}${selected ? " selected" : ""}`}
      {...(onSelect ? {
        role: "button",
        tabIndex: 0,
        "aria-pressed": !!selected,
        onClick: open,
        onKeyDown: (e: React.KeyboardEvent) => {
          if ((e.key === "Enter" || e.key === " ") && e.target === e.currentTarget) { e.preventDefault(); open(); }
        },
      } : {})}
    >
      <div className="pf-head">
        <span className="pf-title">{n !== undefined ? <span className="pf-n">{n}</span> : null}{f.label}</span>
        <span className={`pf-station${isBench(f.kind) ? " bench" : ""}`}>{STEP_STATION[f.kind]}</span>
      </div>
      {f.note ? <div className="pf-why">{f.note}</div> : null}
      {f.unit ? (
        <>
          <div className="progress-bar progress-bar-sm"><i style={{ width: `${pct}%` }} /></div>
          <div className="pf-nums">
            <span>{f.unit.done.toLocaleString()} / {f.unit.total.toLocaleString()} done</span>
            {f.unit.waiting ? <span>{f.unit.waiting.toLocaleString()} waiting</span> : null}
          </div>
          {f.state === "done" ? null : f.unit.canGo ? (
            <div className="pf-can"><b>{f.unit.canGo.toLocaleString()}</b> can go now</div>
          ) : f.unit.waiting ? (
            <div className="pf-why">stock covers none</div>
          ) : f.needsText ? (
            <div className="pf-why">waits for {f.needsText}</div>
          ) : null}
        </>
      ) : f.needsText ? (
        <div className="pf-why">needs {f.needsText}</div>
      ) : null}
      {f.beforeText ? <div className="pf-why">before {f.beforeText}</div> : null}
      {f.stock.length ? (
        <div className="pf-chips">
          {f.stock.map((c) => (
            <span key={c.name} className={`stat-chip ${c.tone}`} title={c.name}><span>{c.name}</span>{c.line}</span>
          ))}
        </div>
      ) : null}
      {extra ? <div className="pf-chips">{extra}</div> : null}
      {f.procedure ? <div className="pf-recipe">procedure {f.procedure}</div> : null}
      {action ? <div className="pf-act" onClick={(e) => e.stopPropagation()}>{action}</div> : null}
    </div>
  );
}

const PER_ROW = 5;

/** Where field `i` sits on the snake: odd rows run right to left. */
function cell(i: number): { row: number; col: number } {
  const row = Math.floor(i / PER_ROW);
  const pos = i % PER_ROW;
  return { row, col: row % 2 ? PER_ROW - 1 - pos : pos };
}

interface BoardProps {
  fields: BoardField[];
  selected?: string | null;
  onSelect?: (key: string) => void;
  action?: (key: string) => ReactNode;
  extra?: (key: string) => ReactNode;
}

export default function ProcessBoard({ fields, selected, onSelect, action, extra }: BoardProps) {
  return (
    <div className="process-board">
      {fields.map((f, i) => {
        const here = cell(i);
        const next = i + 1 < fields.length ? cell(i + 1) : null;
        const turns = next !== null && next.row !== here.row;
        return (
          <Fragment key={f.key}>
            <div className="pf-cell" style={{ gridRow: here.row * 2 + 1, gridColumn: here.col * 2 + 1 }}>
              <Field f={f} n={i + 1} selected={selected === f.key} onSelect={onSelect}
                action={action?.(f.key)} extra={extra?.(f.key)} />
            </div>
            {next ? (
              <span
                aria-hidden="true"
                className={`pf-arrow${turns ? " down" : here.row % 2 ? " left" : ""}`}
                style={turns
                  ? { gridRow: here.row * 2 + 2, gridColumn: here.col * 2 + 1 }
                  : { gridRow: here.row * 2 + 1, gridColumn: here.col * 2 + (here.row % 2 ? 0 : 2) }}
              />
            ) : null}
          </Fragment>
        );
      })}
    </div>
  );
}

/** Steps off the route: they take no place on the path, so they sit under it. */
export function OffRouteFields({ fields, selected, onSelect, action, extra }: BoardProps) {
  if (!fields.length) return null;
  return (
    <>
      <div className="card-subtitle">Off the route: any time their needs are met</div>
      <div className="process-map">
        {fields.map((f) => (
          <div key={f.key} className="process-col">
            <Field f={f} selected={selected === f.key} onSelect={onSelect} action={action?.(f.key)} extra={extra?.(f.key)} />
          </div>
        ))}
      </div>
    </>
  );
}

/** One square per route field, for a row in a list. */
export function MiniBoard({ steps }: { steps: BoardStep[] }) {
  return (
    <span className="mini-board">
      {steps.filter((s) => s.on_route).map((s, i) => (
        <i key={s.key} className={`${s.state}${s.required ? "" : " optional"}`}
          title={`${i + 1} · ${s.label}: ${s.done} / ${s.total} done${s.can_go ? `, ${s.can_go} can go now` : ""}`} />
      ))}
    </span>
  );
}

/** The first field where units can go: what a list says about a batch in work. */
export function nextUp(steps: BoardStep[]): BoardStep | null {
  return steps.find((s) => s.on_route && s.can_go > 0) ?? null;
}

export function BoardLegend() {
  return (
    <div className="pf-legend">
      <span><i className="done" />every unit has done the step</span>
      <span><i className="ready" />units wait and can go now</span>
      <span><i className="idle" />no unit waits here</span>
      <span><i className="short" />stock does not cover the units still to do</span>
      <span><i className="blocked" />units wait and stock covers none</span>
    </div>
  );
}
