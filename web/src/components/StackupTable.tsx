/** One board stackup, drawn top to bottom as a colour-coded table.
 *
 *  There is a single visualiser for three views, on purpose: a fab stackup on its own
 *  in the field solver, a `.kicad_pcb` on its own, and the two compared on a project.
 *  All three take the same row list, which the BACKEND builds and aligns
 *  (`services/field_state.py: stack_rows`). Aligning in the page instead would let the
 *  picture drift away from the verdict the platform computed, which is the one thing
 *  this table must never do.
 *
 *  Colour carries the layer KIND, so the eye finds copper, core and prepreg without
 *  reading a word — the same job Altium's stackup editor gives it. In compare mode a
 *  second colour, on the row's right edge only, carries the verdict, so the two
 *  meanings never fight for the same pixels.
 *
 *  NOT a DataTable, and this is the exception the house rule allows for. A stackup's
 *  order IS its meaning: the rows are a physical sequence from the top of the board to
 *  the bottom, so a sortable header would let a reader destroy the only thing the table
 *  says. There is nothing to filter either — a stackup is sixteen rows at most. What
 *  the rule is really protecting (fixed layout, no sideways scroll, one line per row)
 *  is honoured in the stylesheet.
 */
import type { CSSProperties, ReactNode } from "react";
import type { FsStackFace, FsStackRow } from "../api";

export type StackupMode = "single" | "compare";

/** Which side a single-mode table draws. */
export type StackupSide = "board" | "stackup";

export interface StackupTableProps {
  rows: FsStackRow[];
  mode?: StackupMode;
  /** Single mode only: which side of each row holds the data. */
  side?: StackupSide;
  /** Column-group headers for the two sides in compare mode. */
  boardLabel?: string;
  stackupLabel?: string;
  /** Extra columns appended after the built-in ones (the field solver's profiles). */
  extraColumns?: { key: string; header: ReactNode; cell: (row: FsStackRow, i: number) => ReactNode }[];
  /** Copper-row selection, for the field solver. */
  selectedCopper?: string | null;
  onSelectCopper?: (name: string) => void;
  /** Draw the relative-thickness rail. Default true. */
  showProfile?: boolean;
  /** The board's own colours, when a PROJECT has chosen them. Paints the mask and
   *  overlay rows in the ink the board will actually be made in. Never comes from the
   *  stackup — a stackup describes conduction, not appearance. */
  colors?: { mask?: string; silk?: string };
  /** A trailing column whose body is ONE cell spanning every row, vertically centred.
   *  The field solver puts "add a profile" here, so the control sits in the column
   *  position the new profile will actually take rather than under the table. */
  trailingColumn?: { header?: ReactNode; cell: ReactNode };
  /** Put a control in a cell instead of its text — this is what makes the stackup
   *  EDITOR the same table as every other view of a stackup rather than a second one
   *  that drifts. Return undefined to keep the default rendering for that cell. */
  renderCell?: (row: FsStackRow, col: StackupColumn, i: number) => ReactNode | undefined;
  /** A per-row control in a trailing column (the editor's "remove"). */
  rowActions?: (row: FsStackRow, i: number) => ReactNode;
}

export type StackupColumn = "name" | "material" | "thickness" | "dk";

/** Black or white text, whichever the board's own ink can be read against.
 *
 *  A project may pick a black solder mask or a black legend, and the table then paints
 *  a row in it — at which point the theme's text colour is unreadable on that one row.
 *  Relative luminance per WCAG, so the answer is the same one a contrast checker
 *  gives rather than a guess at "dark-looking". */
function readableOn(hex: string): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return "";
  const n = parseInt(m[1], 16);
  const lin = (c: number) => {
    const x = c / 255;
    return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4;
  };
  const L =
    0.2126 * lin((n >> 16) & 255) + 0.7152 * lin((n >> 8) & 255) + 0.0722 * lin(n & 255);
  return L > 0.45 ? "#16181c" : "#f4f6f8";
}

const inkStyle = (hex?: string): CSSProperties | undefined =>
  hex ? ({ "--stk-fill": hex, "--stk-text": readableOn(hex) } as CSSProperties) : undefined;

const trim = (v: number) => v.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
const mm = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${trim(v)}mm`);
const DIELECTRIC = new Set(["core", "prepreg", "dielectric"]);
/** Only a dielectric has a Dk. A dash on a copper or mask row reads as missing data
 *  for something that has none, so those cells stay empty. */
const dk = (v: number | null | undefined, kind: string) =>
  v === null || v === undefined ? (DIELECTRIC.has(kind) ? "—" : "") : String(v);

export default function StackupTable({
  rows,
  mode = "single",
  side = "stackup",
  boardLabel = "Board file",
  stackupLabel = "Stackup",
  extraColumns = [],
  trailingColumn,
  renderCell,
  rowActions,
  selectedCopper = null,
  onSelectCopper,
  showProfile = true,
  colors,
}: StackupTableProps) {
  const compare = mode === "compare";

  // The rail is a SQUARE-ROOT scale of the thickest layer, and its header says so.
  // At true scale a 0.0152 mm foil beside a 0.218 mm prepreg sheet is 7% of the
  // column and reads as nothing, which makes the rail decoration rather than
  // information. The root keeps the order of the layers honest — thicker is always
  // longer — while leaving every copper layer visible.
  const thickest = Math.max(
    0.0001,
    ...rows.map((r) => Math.max(r.board?.thickness_mm ?? 0, r.stackup?.thickness_mm ?? 0)),
  );
  const railPct = (t: number | null | undefined) =>
    t === null || t === undefined || t <= 0 ? 0 : Math.max(7, Math.round(Math.sqrt(t / thickest) * 100));

  const primary = (r: FsStackRow): FsStackFace | null =>
    compare ? r.board ?? r.stackup : r[side] ?? r.board ?? r.stackup;

  const cols =
    4 + (showProfile ? 1 : 0) + (compare ? 3 : 1) + extraColumns.length + (trailingColumn ? 1 : 0) + (rowActions ? 1 : 0);
  const custom = (r: FsStackRow, c: StackupColumn, i: number, fallback: ReactNode): ReactNode => {
    const node = renderCell?.(r, c, i);
    return node === undefined ? fallback : node;
  };

  return (
    <div className="stk-wrap">
      <table
        className={`stk ${compare ? "stk-compare" : "stk-single"}${extraColumns.length ? " stk-has-extra" : ""}${
          renderCell ? " stk-edit" : ""
        }`}
      >
        <colgroup>
          <col className="stk-c-num" />
          {showProfile ? <col className="stk-c-rail" /> : null}
          <col className="stk-c-name" />
          <col className="stk-c-mat" />
          <col className="stk-c-t" />
          <col className="stk-c-dk" />
          {compare ? <col className="stk-c-t" /> : null}
          {compare ? <col className="stk-c-dk" /> : null}
          {compare ? <col className="stk-c-check" /> : null}
          {extraColumns.map((c) => (
            <col key={c.key} />
          ))}
          {trailingColumn ? <col className="stk-c-add" /> : null}
          {rowActions ? <col className="stk-c-act" /> : null}
        </colgroup>
        <thead>
          <tr>
            <th className="stk-num" rowSpan={2}>
              #
            </th>
            {showProfile ? (
              <th className="stk-rail" rowSpan={2} title="Square-root scale of the thickest layer">
                Rel.
              </th>
            ) : null}
            <th rowSpan={2}>Name</th>
            <th rowSpan={2}>Material</th>
            {compare ? (
              <>
                <th className="stk-right stk-grp" colSpan={2}>
                  {boardLabel}
                </th>
                <th className="stk-right stk-grp" colSpan={2}>
                  {stackupLabel}
                </th>
                <th rowSpan={2} className="stk-verdict">
                  Check
                </th>
              </>
            ) : (
              <>
                <th className="stk-right" rowSpan={2}>
                  Thickness
                </th>
                <th className="stk-right" rowSpan={2}>
                  Dk
                </th>
              </>
            )}
            {extraColumns.map((c) => (
              <th key={c.key} rowSpan={2}>
                {c.header}
              </th>
            ))}
            {trailingColumn ? (
              <th rowSpan={2} className="stk-add">
                {trailingColumn.header}
              </th>
            ) : null}
            {rowActions ? <th rowSpan={2} /> : null}
          </tr>
          <tr>
            {compare ? (
              <>
                <th className="stk-right stk-sub2">Thickness</th>
                <th className="stk-right stk-sub2">Dk</th>
                <th className="stk-right stk-sub2">Thickness</th>
                <th className="stk-right stk-sub2">Dk</th>
              </>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={cols} className="muted stk-empty">
                Nothing to draw.
              </td>
            </tr>
          ) : null}
          {rows.map((r, i) => {
            const f = primary(r);
            const s = r.stackup;
            const b = r.board;
            const copper = r.kind === "copper";
            const pick = !!onSelectCopper && copper && !!f?.name;
            const selected = copper && f?.name === selectedCopper;
            const material = f?.material && !copper ? f.material : "";
            // Shown where the PAIRING is the point — which fab layer a KiCad layer is, and
            // which finish the stackup carries against the one the board asks for. On every
            // dielectric row it would only repeat the material column.
            const alias =
              compare && (copper || r.kind === "finish") && b && s && b.name !== s.name ? s.name : "";
            return (
              <tr
                key={`${r.kind}-${i}`}
                className={[
                  `stk-${r.kind}`,
                  compare ? `stk-v-${r.severity}` : "",
                  selected ? "stk-sel" : "",
                  pick ? "stk-pick" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                onClick={pick ? () => onSelectCopper!(f!.name) : undefined}
                style={
                  // The chosen ink overrides the palette's generic green for these two
                  // rows only; every other row keeps the colour that means its KIND.
                  // The text colour comes with it — a black mask is a legal choice and
                  // the theme's own text is unreadable on it.
                  r.kind === "mask" ? inkStyle(colors?.mask) : r.kind === "overlay" ? inkStyle(colors?.silk) : undefined
                }
              >
                <td className="stk-num">{r.index ?? ""}</td>
                {showProfile ? (
                  <td className="stk-rail">
                    <i className="stk-bar" style={{ width: `${railPct(f?.thickness_mm)}%` }} />
                  </td>
                ) : null}
                <td className="stk-name" title={[f?.name, alias].filter(Boolean).join(" / ") || undefined}>
                  {custom(r, "name", i, f?.name || "—")}
                  {alias ? <span className="stk-alias"> / {alias}</span> : null}
                  {r.note ? (
                    <span className="stk-info" tabIndex={0} role="note" aria-label={r.note}>
                      {" "}
                      ⓘ<span className="stk-tip">{r.note}</span>
                    </span>
                  ) : null}
                </td>
                <td className="stk-mat" title={material || undefined}>{custom(r, "material", i, material)}</td>
                {compare ? (
                  <>
                    <td className={cellClass(r.ok.thickness)}>{mm(b?.thickness_mm)}</td>
                    <td className={cellClass(r.ok.dk)}>{dk(b?.dk, r.kind)}</td>
                    <td className={cellClass(r.ok.thickness)}>{mm(s?.thickness_mm)}</td>
                    <td className={cellClass(r.ok.dk)}>{dk(s?.dk, r.kind)}</td>
                    <td className="stk-verdict">
                      <Verdict severity={r.severity} />
                    </td>
                  </>
                ) : (
                  <>
                    <td className="stk-right">{custom(r, "thickness", i, mm(f?.thickness_mm))}</td>
                    <td className="stk-right">{custom(r, "dk", i, dk(f?.dk, r.kind))}</td>
                  </>
                )}
                {extraColumns.map((c) => (
                  <td key={c.key}>{c.cell(r, i)}</td>
                ))}
                {trailingColumn && i === 0 ? (
                  <td className="stk-add" rowSpan={rows.length}>
                    {trailingColumn.cell}
                  </td>
                ) : null}
                {rowActions ? <td className="stk-act">{rowActions(r, i)}</td> : null}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const cellClass = (ok: boolean | null | undefined) =>
  ok === false ? "stk-right stk-cell-bad" : "stk-right";

function Verdict({ severity }: { severity: FsStackRow["severity"] }) {
  if (severity === "match") return <span className="pill ok">same</span>;
  if (severity === "differs") return <span className="pill err">differs</span>;
  if (severity === "note") return <span className="pill warn">note</span>;
  return <span className="pill neutral">—</span>;
}

/** The colours the table paints, for a legend. */
export const STACKUP_LEGEND: { kind: string; label: string }[] = [
  { kind: "overlay", label: "Overlay" },
  { kind: "mask", label: "Solder mask" },
  { kind: "finish", label: "Surface finish" },
  { kind: "copper", label: "Copper" },
  { kind: "core", label: "Core" },
  { kind: "prepreg", label: "Prepreg" },
];

export function StackupLegend({ note }: { note?: ReactNode }) {
  return (
    <div className="stk-legend">
      {STACKUP_LEGEND.map((l) => (
        <span key={l.kind} className="stk-legend-item">
          <i className={`stk-chip stk-${l.kind}`} />
          {l.label}
        </span>
      ))}
      {note ? <span className="stk-legend-note">{note}</span> : null}
    </div>
  );
}
