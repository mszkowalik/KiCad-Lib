/** A `.kicad_sch` drawn by the browser, from the document `sch_draw.py` emits.
 *
 *  It replaces `kicad-cli sch export svg` in the simulator for two reasons a
 *  picture cannot answer: a picture cannot show a switch closing, and an
 *  editor needs to know where things are, not what they looked like.
 *
 *  Colours come from the same theme file kicad-cli reads (`/api/sim/theme`),
 *  so this drawing and the project's schematic tab are one colour scheme.
 *
 *  Everything is in the file's own millimetres, which is also the coordinate
 *  space the overlay, the geometry and the netlist all speak.
 */
import { memo } from "react";
import type {
  At, DrawLabel, DrawLine, DrawSheet, DrawSymbol, DrawText,
  LibPin, LibShape, LibSymbol, Matrix, SchTheme, SheetDrawing,
} from "./types";
import {
  BUS_WIDTH, DEFAULT_LINE, JUNCTION_DIAM, NO_CONNECT_ARM, WIRE_WIDTH,
  apply, arcPath, bezierPath, matrixString, placePin, placeText, polyPath,
  round, textWidth,
} from "./geom";

/** A browser font is measured by its em box, KiCad's by the height of a
 *  capital. The ratio between them is what this constant is. */
const TEXT_SCALE = 1.36;

export interface View {
  x: number;
  y: number;
  w: number;
  h: number;
}

interface Props {
  drawing: SheetDrawing;
  theme: SchTheme;
  view: View;
  className?: string;
  /** Drawn BENEATH the sheet, in the same millimetre space — the editor's
   *  grid, which has to sit under the circuit and not over it. */
  underlay?: React.ReactNode;
  /** Layers drawn on top, in the same millimetre space. */
  children?: React.ReactNode;
}

function dashOf(kind: string, w: number): string | undefined {
  const u = Math.max(w, DEFAULT_LINE);
  switch (kind) {
    case "dash": return `${round(u * 12)} ${round(u * 6)}`;
    case "dot": return `${round(u)} ${round(u * 4)}`;
    case "dash_dot": return `${round(u * 12)} ${round(u * 4)} ${round(u)} ${round(u * 4)}`;
    case "dash_dot_dot": return `${round(u * 12)} ${round(u * 4)} ${round(u)} ${round(u * 4)} ${round(u)} ${round(u * 4)}`;
    default: return undefined;
  }
}

function fillOf(kind: string, outline: string, body: string): string {
  if (kind === "outline") return outline;
  if (kind === "background") return body;
  return "none";
}

// -------------------------------------------------------------------- text

interface TextProps {
  at: [number, number, number];
  just: string[];
  h: number;
  fill: string;
  bold?: boolean;
  italic?: boolean;
  children: string;
}

function Text({ at, just, h, fill, bold, italic, children }: TextProps) {
  if (!children) return null;
  const p = placeText(at, just);
  const lines = children.split("\n");
  return (
    <text
      x={round(p.x)}
      y={round(p.y)}
      fill={fill}
      fontSize={round(h * TEXT_SCALE)}
      fontWeight={bold ? 600 : 400}
      fontStyle={italic ? "italic" : undefined}
      textAnchor={p.anchor}
      dominantBaseline={lines.length > 1 ? undefined : p.baseline}
      transform={p.rotate ? `rotate(${p.rotate} ${round(p.x)} ${round(p.y)})` : undefined}
    >
      {lines.length === 1
        ? children
        : lines.map((line, i) => (
            <tspan key={i} x={round(p.x)} dy={i === 0 ? 0 : round(h * 1.6)}>
              {line || " "}
            </tspan>
          ))}
    </text>
  );
}

// ------------------------------------------------------------------ shapes

function Shape({ s, outline, body }: { s: LibShape; outline: string; body: string }) {
  if (s.t === "text") {
    return <Text at={s.at} just={s.just} h={s.h} fill={outline} bold={s.bold} italic={s.italic}>{s.s}</Text>;
  }
  const common = {
    stroke: outline,
    strokeWidth: round(s.w || DEFAULT_LINE),
    strokeDasharray: dashOf(s.dash, s.w),
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    fill: fillOf(s.fill, outline, body),
  };
  switch (s.t) {
    case "rect":
      return (
        <rect
          x={round(Math.min(s.a[0], s.b[0]))}
          y={round(Math.min(s.a[1], s.b[1]))}
          width={round(Math.abs(s.b[0] - s.a[0]))}
          height={round(Math.abs(s.b[1] - s.a[1]))}
          {...common}
        />
      );
    case "circle":
      return <circle cx={round(s.c[0])} cy={round(s.c[1])} r={round(s.r)} {...common} />;
    case "arc":
      return <path d={arcPath(s.a, s.m, s.b)} {...common} />;
    case "bezier":
      return <path d={bezierPath(s.pts)} {...common} />;
    default:
      return <path d={polyPath(s.pts)} {...common} />;
  }
}

// -------------------------------------------------------------------- pins

/** The pin line and its decoration, in SYMBOL space (inside the placement
 *  matrix). Text is not here — text must stay upright, so it is drawn in
 *  sheet space by `PinText`. */
function PinBody({ pin, colour }: { pin: LibPin; colour: string }) {
  const [x, y, a] = pin.at;
  const rad = (a * Math.PI) / 180;
  const dx = Math.cos(rad);
  const dy = Math.sin(rad);
  const inverted = pin.shape.startsWith("inverted");
  const clock = pin.shape.includes("clock");
  const r = 0.508;
  const startAt = inverted ? [x + dx * r * 2, y + dy * r * 2] : [x, y];
  const bx = x + pin.len * dx;
  const by = y + pin.len * dy;
  const stroke = { stroke: colour, strokeWidth: DEFAULT_LINE, fill: "none", strokeLinecap: "round" as const };
  return (
    <g>
      <line x1={round(startAt[0])} y1={round(startAt[1])} x2={round(bx)} y2={round(by)} {...stroke} />
      {inverted ? <circle cx={round(x + dx * r)} cy={round(y + dy * r)} r={r} {...stroke} /> : null}
      {clock ? (
        <path
          d={polyPath([
            [bx - dy * r, by + dx * r],
            [bx + dx * r * 2, by + dy * r * 2],
            [bx + dy * r, by - dx * r],
          ])}
          {...stroke}
        />
      ) : null}
    </g>
  );
}

/** Pin number and name, upright on the sheet.
 *
 *  KiCad puts the number across the stub and the name past the body end, and
 *  it never turns either upside down — a vertical pin reads bottom to top. */
function PinText({
  pin, xf, lib, numberColour, nameColour,
}: { pin: LibPin; xf: Matrix; lib: LibSymbol; numberColour: string; nameColour: string }) {
  const placed = placePin(pin, xf);
  const horizontal = Math.abs(placed.dir[0]) >= Math.abs(placed.dir[1]);
  const rotate = horizontal ? 0 : -90;
  const out: React.ReactNode[] = [];

  if (!lib.hide_numbers && pin.n && pin.len > 0) {
    const mx = (placed.at[0] + placed.root[0]) / 2;
    const my = (placed.at[1] + placed.root[1]) / 2;
    const off = pin.num_h * 0.5 + 0.25;
    out.push(
      <text
        key="n"
        x={round(mx)}
        y={round(my - off)}
        fill={numberColour}
        fontSize={round(pin.num_h * TEXT_SCALE)}
        textAnchor="middle"
        dominantBaseline="auto"
        transform={rotate ? `rotate(${rotate} ${round(mx)} ${round(my)})` : undefined}
      >
        {pin.n}
      </text>,
    );
  }

  const name = pin.name === "~" ? "" : pin.name;
  if (!lib.hide_names && name) {
    const off = Math.max(lib.name_offset, 0.508);
    const nx = placed.root[0] + placed.dir[0] * off;
    const ny = placed.root[1] + placed.dir[1] * off;
    // The name reads away from the connection point: rightwards for a
    // horizontal pin, upwards for a vertical one.
    const forward = horizontal ? placed.dir[0] > 0 : placed.dir[1] < 0;
    out.push(
      <text
        key="m"
        x={round(nx)}
        y={round(ny)}
        fill={nameColour}
        fontSize={round(pin.name_h * TEXT_SCALE)}
        textAnchor={forward ? "start" : "end"}
        dominantBaseline="middle"
        transform={rotate ? `rotate(${rotate} ${round(nx)} ${round(ny)})` : undefined}
      >
        {name}
      </text>,
    );
  }
  return <>{out}</>;
}

// ----------------------------------------------------------------- symbols

function fieldColour(key: string, theme: SchTheme): string {
  if (key === "Reference") return theme.reference;
  if (key === "Value") return theme.value;
  return theme.fields;
}

/** KiCad draws a field at the field's own angle PLUS the symbol's — a
 *  reference stored at 0 on a symbol turned 90 degrees is drawn upright along
 *  the part. Checked on a real sheet: R157 (symbol 90, field 90) comes out
 *  horizontal and D29 (symbol 90, field 0) vertical, which only the sum
 *  explains. Mirroring turns the text no further; it swaps the side the text
 *  is justified to. */
function fieldAt(f: { at: At }, sym: DrawSymbol): At {
  return [f.at[0], f.at[1], f.at[2] + sym.at[2]];
}

function fieldJust(just: string[], sym: DrawSymbol, drawnAngle: number): string[] {
  if (!sym.mirror) return just;
  const flip = (a: string, b: string) => just.map((j) => (j === a ? b : j === b ? a : j));
  return (((drawnAngle % 180) + 180) % 180) === 0 ? flip("left", "right") : flip("top", "bottom");
}

const SymbolItem = memo(function SymbolItem({
  sym, lib, theme,
}: { sym: DrawSymbol; lib: LibSymbol | undefined; theme: SchTheme }) {
  if (!lib) return null;
  const mine = (u: number, b: number) => (u === 0 || u === sym.unit) && (b === 0 || b === sym.body);
  const shapes = lib.shapes.filter((s) => mine(s.unit, s.body));
  const pins = lib.pins.filter((p) => mine(p.unit, p.body) && !p.hide);
  const outline = theme.component_outline;
  // A filled body drawn after the lettering inside it would hide it, and
  // KiCad puts the "&" of a gate inside exactly such a body.
  const graphics = shapes.filter((s) => s.t !== "text");
  const lettering = shapes.filter((s) => s.t === "text");
  const suffix = lib.unit_count > 1 ? String.fromCharCode(64 + sym.unit) : "";
  return (
    <g>
      <g transform={matrixString(sym.xf)}>
        {graphics.map((s, i) => (
          <Shape key={i} s={s} outline={outline} body={theme.component_body} />
        ))}
        {pins.map((p, i) => (
          <PinBody key={i} pin={p} colour={theme.pin} />
        ))}
      </g>
      {/* Lettering is placed by the matrix but never turned by it: the y flip
          in a placement would print it back to front. */}
      {lettering.map((s, i) => {
        if (s.t !== "text") return null;
        const at = apply(sym.xf, [s.at[0], s.at[1]]);
        return (
          <Text
            key={`t${i}`}
            at={[at[0], at[1], s.at[2] + sym.at[2]]}
            just={s.just}
            h={s.h}
            fill={outline}
            bold={s.bold}
            italic={s.italic}
          >
            {s.s}
          </Text>
        );
      })}
      {pins.map((p, i) => (
        <PinText
          key={i}
          pin={p}
          xf={sym.xf}
          lib={lib}
          numberColour={theme.pin_number}
          nameColour={theme.pin_name}
        />
      ))}
      {sym.fields.filter((f) => !f.hide).map((f, i) => (
        <Text
          key={i}
          at={fieldAt(f, sym)}
          just={fieldJust(f.just, sym, f.at[2] + sym.at[2])}
          h={f.h}
          fill={fieldColour(f.k, theme)}
          bold={f.bold}
          italic={f.italic}
        >
          {f.k === "Reference" ? f.v + suffix : f.v}
        </Text>
      ))}
    </g>
  );
});

// ------------------------------------------------------------------ labels

/** The flag KiCad draws around a hierarchical or global label. The local x
 *  axis runs the way the text runs, so the same polygon serves every
 *  orientation. */
function flagPath(shape: string, length: number, half: number): string {
  switch (shape) {
    case "output":
      return polyPath([[0, -half], [length - half, -half], [length, 0], [length - half, half], [0, half]]) + " Z";
    case "bidirectional":
    case "tri_state":
      return polyPath([[0, 0], [half, -half], [length - half, -half], [length, 0], [length - half, half], [half, half]]) + " Z";
    case "passive":
    case "unspecified":
      return polyPath([[0, -half], [length, -half], [length, half], [0, half]]) + " Z";
    default: // input
      return polyPath([[0, 0], [half, -half], [length, -half], [length, half], [half, half]]) + " Z";
  }
}

function Label({ label, theme }: { label: DrawLabel; theme: SchTheme }) {
  const colour =
    label.kind === "global" ? theme.label_global
      : label.kind === "hier" ? theme.label_hier
        : theme.label_local;
  const p = placeText(label.at, label.just);
  if (label.kind === "local") {
    return (
      <Text at={label.at} just={label.just} h={label.h} fill={colour}>{label.text}</Text>
    );
  }
  const half = label.h * 0.75;
  const length = label.kind === "hier" ? label.h * 1.5 : textWidth(label.text, label.h) + label.h * 2;
  const back = p.anchor === "end";
  // The text starts past the flag, so it never sits inside it.
  const gap = label.kind === "hier" ? label.h * 1.9 : label.h;
  return (
    <g>
      <g transform={`translate(${round(p.x)} ${round(p.y)}) rotate(${p.rotate})${back ? " scale(-1 1)" : ""}`}>
        <path
          d={flagPath(label.shape, length, half)}
          stroke={colour}
          strokeWidth={DEFAULT_LINE}
          strokeLinejoin="round"
          fill="none"
        />
      </g>
      <Text
        at={[
          p.x + (p.rotate ? 0 : (back ? -gap : gap)),
          p.y + (p.rotate ? (back ? gap : -gap) : 0),
          label.at[2],
        ]}
        just={label.just}
        h={label.h}
        fill={colour}
      >
        {label.text}
      </Text>
    </g>
  );
}

// ------------------------------------------------------------------ sheets

function SubSheet({ sheet, theme }: { sheet: DrawSheet; theme: SchTheme }) {
  return (
    <g>
      <rect
        x={round(sheet.at[0])}
        y={round(sheet.at[1])}
        width={round(sheet.size[0])}
        height={round(sheet.size[1])}
        stroke={theme.sheet}
        strokeWidth={round(sheet.w || DEFAULT_LINE)}
        fill={fillOf(sheet.fill, theme.sheet, theme.sheet_background)}
      />
      {sheet.fields.filter((f) => !f.hide).map((f, i) => (
        <Text
          key={i}
          at={f.at}
          just={f.just}
          h={f.h}
          fill={f.k.toLowerCase().startsWith("sheetname") || f.k === "Sheet name" ? theme.sheet_name
            : f.k.toLowerCase().startsWith("sheetfile") || f.k === "Sheet file" ? theme.sheet_filename
              : theme.sheet_fields}
        >
          {f.v}
        </Text>
      ))}
      {sheet.pins.map((pin, i) => {
        const p = placeText(pin.at, pin.just);
        const half = pin.h * 0.75;
        const back = p.anchor === "end";
        return (
          <g key={i}>
            <g transform={`translate(${round(p.x)} ${round(p.y)}) rotate(${p.rotate})${back ? " scale(-1 1)" : ""}`}>
              <path
                d={flagPath(pin.shape, pin.h * 1.5, half)}
                stroke={theme.sheet_label}
                strokeWidth={DEFAULT_LINE}
                strokeLinejoin="round"
                fill="none"
              />
            </g>
            <Text
              at={[
                p.x + (p.rotate ? 0 : (back ? -pin.h * 1.9 : pin.h * 1.9)),
                p.y + (p.rotate ? (back ? pin.h * 1.9 : -pin.h * 1.9) : 0),
                pin.at[2],
              ]}
              just={pin.just}
              h={pin.h}
              fill={theme.sheet_label}
            >
              {pin.name}
            </Text>
          </g>
        );
      })}
    </g>
  );
}

// ------------------------------------------------------------------- sheet

function Line({ line, colour }: { line: DrawLine; colour: string }) {
  return (
    <polyline
      points={line.pts.map((p) => `${round(p[0])},${round(p[1])}`).join(" ")}
      stroke={colour}
      strokeWidth={round(line.w || (line.kind === "bus" ? BUS_WIDTH : WIRE_WIDTH))}
      strokeDasharray={dashOf(line.dash, line.w)}
      strokeLinecap="round"
      strokeLinejoin="round"
      fill="none"
    />
  );
}

function Note({ item, theme }: { item: DrawText; theme: SchTheme }) {
  return (
    <Text
      at={item.at}
      just={item.just.length ? item.just : ["left", "top"]}
      h={item.h}
      fill={item.excluded ? theme.excluded_from_sim : theme.note}
      bold={item.bold}
      italic={item.italic}
    >
      {item.text}
    </Text>
  );
}

function KicadSheet({ drawing, theme, view, className, underlay, children }: Props) {
  return (
    <svg
      className={className}
      viewBox={`${round(view.x)} ${round(view.y)} ${round(view.w)} ${round(view.h)}`}
      preserveAspectRatio="xMidYMid meet"
      style={{ background: theme.background }}
      fontFamily='"DejaVu Sans", "Segoe UI", system-ui, sans-serif'
    >
      {underlay}
      <g className="sch-sheets">
        {drawing.sheets.map((s, i) => <SubSheet key={i} sheet={s} theme={theme} />)}
      </g>
      <g className="sch-shapes">
        {drawing.shapes.map((s, i) => (
          <Shape key={i} s={s} outline={theme.note} body={theme.note_background || "none"} />
        ))}
      </g>
      <g className="sch-buses">
        {drawing.buses.map((b) => <Line key={b.id} line={b} colour={theme.bus} />)}
        {drawing.bus_entries.map((e, i) => (
          <line
            key={i}
            x1={round(e.at[0])}
            y1={round(e.at[1])}
            x2={round(e.at[0] + e.size[0])}
            y2={round(e.at[1] + e.size[1])}
            stroke={theme.bus}
            strokeWidth={BUS_WIDTH}
          />
        ))}
      </g>
      <g className="sch-wires">
        {drawing.wires.map((w) => <Line key={w.id} line={w} colour={theme.wire} />)}
      </g>
      <g className="sch-junctions">
        {drawing.junctions.map((j, i) => (
          <circle
            key={i}
            cx={round(j.at[0])}
            cy={round(j.at[1])}
            r={round((j.d || JUNCTION_DIAM) / 2)}
            fill={theme.junction}
          />
        ))}
      </g>
      <g className="sch-nc">
        {drawing.no_connects.map((n, i) => (
          <g key={i} stroke={theme.no_connect} strokeWidth={DEFAULT_LINE} strokeLinecap="round">
            <line
              x1={round(n.at[0] - NO_CONNECT_ARM)} y1={round(n.at[1] - NO_CONNECT_ARM)}
              x2={round(n.at[0] + NO_CONNECT_ARM)} y2={round(n.at[1] + NO_CONNECT_ARM)}
            />
            <line
              x1={round(n.at[0] - NO_CONNECT_ARM)} y1={round(n.at[1] + NO_CONNECT_ARM)}
              x2={round(n.at[0] + NO_CONNECT_ARM)} y2={round(n.at[1] - NO_CONNECT_ARM)}
            />
          </g>
        ))}
      </g>
      <g className="sch-symbols">
        {drawing.symbols.map((s) => (
          <SymbolItem key={s.index} sym={s} lib={drawing.libs[s.lib_id]} theme={theme} />
        ))}
      </g>
      <g className="sch-labels">
        {drawing.labels.map((l) => <Label key={l.id} label={l} theme={theme} />)}
      </g>
      <g className="sch-notes">
        {drawing.texts.map((t, i) => <Note key={i} item={t} theme={theme} />)}
      </g>
      {children}
    </svg>
  );
}

export default memo(KicadSheet);
