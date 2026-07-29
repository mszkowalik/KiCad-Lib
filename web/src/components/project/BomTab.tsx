/** Priced BOM at a chosen production volume: schematic lines (variant-aware),
 *  manual extra items, cost items, totals, cost-vs-volume curve, LCSC stock
 *  check and BOM diff against another snapshot. */
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  errorMessage,
  getBom,
  getBomCurve,
  getBomDiff,
  isAbortError,
  runStockCheck,
  type BomDiff,
  type BomLine,
  type CurvePoint,
  type PricedBom,
  type ProjectInfo,
  type SnapshotInfo,
  type StockCheck,
} from "../../api";
import DataTable from "../DataTable";
import { ErrorBanner, Spinner } from "../Ui";
import { useStickyState } from "../../useStickyState";
import CostCurve from "./CostCurve";

import { price as money } from "../../format";

interface Props {
  project: ProjectInfo;
  snapshot: SnapshotInfo;
  snapshots: SnapshotInfo[];
  board: string;
  variant: string;
}

export default function BomTab({ project, snapshot, snapshots, board, variant }: Props) {
  // BOM settings — remembered per project across navigation.
  const [volume, setVolume] = useStickyState(`project:${project.id}:bom:volume`, 100);
  const [volumeInput, setVolumeInput] = useState(() => String(volume));
  const [currency, setCurrency] = useStickyState(
    `project:${project.id}:bom:currency`,
    project.effective_currency,
  );
  const [bom, setBom] = useState<PricedBom | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const [curve, setCurve] = useState<CurvePoint[] | null>(null);
  const [stock, setStock] = useState<StockCheck | null>(null);
  const [stockRunning, setStockRunning] = useState(false);
  const [diffAgainst, setDiffAgainst] = useStickyState<number | "">(
    `project:${project.id}:bom:diffAgainst`,
    "",
  );
  const [diff, setDiff] = useState<BomDiff | null>(null);
  const [showExcluded, setShowExcluded] = useStickyState(`project:${project.id}:bom:showExcluded`, true);

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    setStock(null);
    getBom(snapshot.id, board, variant, volume, currency, ctrl.signal)
      .then((b) => {
        setBom(b);
        setLoading(false);
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        setError(errorMessage(err));
        setLoading(false);
      });
    getBomCurve(snapshot.id, board, variant, [1, 10, 100, 1000], currency, ctrl.signal)
      .then(setCurve)
      .catch(() => setCurve(null));
    return () => ctrl.abort();
  }, [snapshot.id, board, variant, volume, currency]);

  const stockByKey = useMemo(() => {
    const map = new Map<string, StockCheck["lines"][number]>();
    for (const li of stock?.lines ?? []) map.set(`${li.refs}`, li);
    return map;
  }, [stock]);

  const doStockCheck = () => {
    setStockRunning(true);
    runStockCheck(snapshot.id, board, variant, volume)
      .then((s) => {
        setStock(s);
        setStockRunning(false);
      })
      .catch((err) => {
        setError(errorMessage(err));
        setStockRunning(false);
      });
  };

  useEffect(() => {
    if (diffAgainst === "") {
      setDiff(null);
      return;
    }
    const ctrl = new AbortController();
    getBomDiff(project.id, diffAgainst as number, snapshot.id, board, variant, ctrl.signal)
      .then(setDiff)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, [diffAgainst, snapshot.id, board, variant, project.id]);

  const lines = bom?.lines.filter((li) => showExcluded || !li.excluded) ?? [];
  const cur = bom?.currency ?? currency;

  // Schematic lines + manual extra items in one interactive table; extras
  // stay pinned after the lines whatever the sort order.
  type BomRow =
    | { kind: "line"; li: BomLine }
    | { kind: "extra"; x: PricedBom["extra"][number] };
  const bomRows: BomRow[] = [
    ...lines.map((li): BomRow => ({ kind: "line", li })),
    ...(bom?.extra ?? []).map((x): BomRow => ({ kind: "extra", x })),
  ];

  // 1,492,500 → "1.5M": the cells are too narrow for full numbers; exact
  // values live in the pill tooltips
  const compact = (n: number) =>
    n.toLocaleString("en", { notation: "compact", maximumFractionDigits: 1 });

  // One pill per row (constant row height): the best procurable quantity =
  // own JLC stock + the larger market pool (LCSC retail and JLCPCB assembly
  // are alternatives, not additive). Per-pool breakdown in the tooltip.
  const stockCell = (li: BomLine) => {
    const s = stockByKey.get(li.refs);
    const lcsc = s ? s.stock : li.stock;
    const jlc = s ? s.jlc_stock : li.jlc_stock;
    const own = s ? s.private_stock : 0;
    const ok = s ? s.ok : li.stock_ok;
    if (lcsc == null && jlc == null && !own) return <span className="muted">—</span>;
    const best = own + Math.max(lcsc ?? 0, jlc ?? 0);
    const tone = ok === false ? "err" : ok ? "ok" : "neutral";
    const detail = [
      `LCSC retail: ${lcsc == null ? "unknown" : lcsc.toLocaleString()}`,
      `JLCPCB assembly: ${jlc == null ? "unknown" : jlc.toLocaleString()}`,
    ];
    if (own > 0) detail.push(`Your JLC library: ${own.toLocaleString()}`);
    if (s) {
      detail.push(
        `Needed: ${s.needed.toLocaleString()}${s.to_buy > 0 ? ` — to buy ${s.to_buy.toLocaleString()}` : " — covered by your stock"}`,
      );
    }
    detail.push("Shown: own stock + larger market pool");
    return (
      <span className={`pill ${tone}`} title={detail.join("\n")}>
        {compact(best)}
      </span>
    );
  };

  return (
    <div>
      <div className="toolbar">
        <label className="proj-inline-field">
          Volume
          <input
            className="text num-input"
            value={volumeInput}
            onChange={(e) => setVolumeInput(e.target.value)}
            onBlur={() => {
              const v = Math.max(1, parseInt(volumeInput, 10) || 1);
              setVolumeInput(String(v));
              setVolume(v);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") (e.target as HTMLInputElement).blur();
            }}
          />
        </label>
        <div className="seg" role="group" aria-label="Quick volumes">
          {[1, 10, 100, 1000].map((v) => (
            <button
              key={v}
              type="button"
              className={volume === v ? "on" : ""}
              onClick={() => {
                setVolume(v);
                setVolumeInput(String(v));
              }}
            >
              {v}
            </button>
          ))}
        </div>
        <label className="proj-inline-field">
          Currency
          <input
            className="text num-input"
            value={currency}
            onChange={(e) => setCurrency(e.target.value.toUpperCase())}
            maxLength={3}
          />
        </label>
        <label className="proj-inline-field proj-check">
          <input
            type="checkbox"
            checked={showExcluded}
            onChange={(e) => setShowExcluded(e.target.checked)}
          />
          show DNP/excluded
        </label>
        <span className="toolbar-total" />
        <button className="btn btn-sm" disabled={stockRunning} onClick={doStockCheck}>
          {stockRunning ? "Checking stock…" : "Check stock"}
        </button>
        <label className="proj-inline-field">
          Diff vs
          <select
            className="text"
            value={diffAgainst}
            onChange={(e) => setDiffAgainst(e.target.value === "" ? "" : Number(e.target.value))}
          >
            <option value="">—</option>
            {snapshots
              .filter((s) => s.id !== snapshot.id && s.status === "ready")
              .map((s) => (
                <option key={s.id} value={s.id}>
                  {s.ref_name} ({s.sha.slice(0, 8)})
                </option>
              ))}
          </select>
        </label>
      </div>

      {error ? <ErrorBanner message={error} /> : null}
      {loading && !bom ? <Spinner label="Pricing BOM" /> : null}

      {bom ? (
        <>
          <div className="counts counts-sm">
            <div className="count-tile">
              <div className="v">{money(bom.totals.device_total, cur)}</div>
              <div className="muted">per device</div>
            </div>
            <div className="count-tile">
              <div className="v">{money(bom.totals.bom_per_device, cur)}</div>
              <div className="muted">parts / device</div>
            </div>
            <div className="count-tile">
              <div className="v">{money(bom.totals.extra_per_device, cur)}</div>
              <div className="muted">extra parts / device</div>
            </div>
            <div className="count-tile">
              <div className="v">{money(bom.totals.cost_per_device, cur)}</div>
              <div className="muted">mfg costs / device</div>
            </div>
            <div className="count-tile">
              <div className="v">{money(bom.totals.run_total, cur)}</div>
              <div className="muted">run total × {bom.volume}</div>
            </div>
            <div className="count-tile">
              <div className="v">{money(bom.totals.order_parts_total, cur)}</div>
              <div className="muted">parts order (MOQ-rounded)</div>
            </div>
          </div>

          {bom.totals.unpriced_lines > 0 ? (
            <div className="banner-warn">
              {bom.totals.unpriced_lines} line(s) have no price — refresh ladders on the component
              pages or add manual price points.
            </div>
          ) : null}
          {bom.totals.unknown_rates.length > 0 ? (
            <div className="banner-warn">
              No exchange rate for: {bom.totals.unknown_rates.join(", ")} — amounts kept 1:1.
            </div>
          ) : null}
          {stock ? (
            <div className={stock.shortages > 0 ? "banner-warn" : "banner-ok"}>
              Stock check at volume {stock.volume}: {stock.shortages} shortage(s),{" "}
              {stock.covered_by_private} line(s) fully covered by your private JLC stock,{" "}
              {stock.unknown} unknown.
              {stock.private_inventory === 0
                ? " (No private JLC inventory synced — see the JLC Stock page.)"
                : ""}
            </div>
          ) : null}

          <div className="card table-wrap">
            <DataTable<BomRow>
              rows={bomRows}
              rowKey={(r) => (r.kind === "line" ? `l:${r.li.key}` : `x:${r.x.key}`)}
              rowClass={(r) =>
                r.kind === "extra" ? "row-extra" : r.li.excluded ? "row-dim" : ""
              }
              group={(r) => (r.kind === "line" ? 0 : 1)}
              empty="No BOM lines."
              columns={[
                {
                  key: "refs",
                  label: "Refs",
                  width: 11,
                  className: "mono",
                  get: (r) => (r.kind === "line" ? r.li.refs : "extra"),
                  render: (r) =>
                    r.kind === "line" ? (
                      <>
                        {r.li.refs}
                        {r.li.dnp ? <span className="pill err">DNP</span> : null}
                        {r.li.exclude_from_bom ? <span className="pill warn">no-BOM</span> : null}
                        {r.li.not_purchasable ? (
                          <span
                            className="pill neutral"
                            title="Virtual part (test point, logo, fiducial, mounting hole) — never bought, so it is left out of totals, orders and stock checks. Change this on the component page."
                          >
                            virtual
                          </span>
                        ) : null}
                      </>
                    ) : (
                      <span className="muted">extra</span>
                    ),
                },
                {
                  key: "value",
                  label: "Value",
                  width: 11,
                  get: (r) => (r.kind === "line" ? r.li.value : r.x.label),
                  title: (r) => (r.kind === "line" ? r.li.footprint : r.x.label),
                },
                {
                  key: "component",
                  label: "Component",
                  width: 14,
                  get: (r) =>
                    r.kind === "line"
                      ? r.li.component_name || r.li.symbol_name || "external"
                      : r.x.component_name || r.x.mpn || "manual",
                  render: (r) => {
                    const id = r.kind === "line" ? r.li.component_id : r.x.component_id;
                    const name = r.kind === "line" ? r.li.component_name : r.x.component_name;
                    if (id) {
                      return (
                        <Link className="comp-link" to={`/library/components/${id}`}>
                          {name}
                        </Link>
                      );
                    }
                    return (
                      <span className="muted" title="not matched to the library">
                        {r.kind === "line" ? r.li.symbol_name || "external" : r.x.mpn || "manual"}
                      </span>
                    );
                  },
                },
                {
                  key: "lcsc",
                  label: "LCSC",
                  width: 9,
                  className: "mono",
                  get: (r) =>
                    r.kind === "line" ? r.li.lcsc : (r.x as { lcsc?: string }).lcsc ?? "",
                  render: (r) =>
                    (r.kind === "line" ? r.li.lcsc : (r.x as { lcsc?: string }).lcsc) || "—",
                },
                {
                  key: "qty_per",
                  label: "Qty/dev",
                  width: 6,
                  numeric: true,
                  get: (r) => (r.kind === "line" ? r.li.qty_per : r.x.qty_per),
                },
                {
                  key: "qty_total",
                  label: "Qty tot",
                  width: 7,
                  numeric: true,
                  get: (r) => (r.kind === "line" ? r.li.qty_total : r.x.qty_total),
                  render: (r) =>
                    (r.kind === "line" ? r.li.qty_total : r.x.qty_total).toLocaleString(),
                },
                {
                  key: "unit",
                  label: "Unit",
                  width: 10,
                  numeric: true,
                  get: (r) => (r.kind === "line" ? r.li.unit_price : r.x.unit_price) ?? null,
                  render: (r) =>
                    money((r.kind === "line" ? r.li.unit_price : r.x.unit_price) ?? null, cur),
                },
                {
                  key: "total",
                  label: "Line total",
                  width: 11,
                  numeric: true,
                  get: (r) =>
                    r.kind === "line"
                      ? r.li.excluded
                        ? null
                        : r.li.line_total
                      : r.x.line_total ?? null,
                  render: (r) =>
                    r.kind === "line"
                      ? r.li.excluded
                        ? "—"
                        : money(r.li.line_total, cur)
                      : money(r.x.line_total ?? null, cur),
                },
                {
                  key: "tier",
                  label: "Tier",
                  width: 8,
                  className: "muted",
                  get: (r) =>
                    r.kind === "line"
                      ? r.li.price_qty_from != null
                        ? `@${r.li.price_qty_from.toLocaleString()} ${r.li.price_source ?? ""}`
                        : "—"
                      : r.x.price_source ?? "—",
                  title: (r) =>
                    r.kind === "line" && r.li.price_updated
                      ? `updated ${r.li.price_updated.slice(0, 10)}`
                      : undefined,
                },
                {
                  key: "stock",
                  label: "Stock",
                  width: 13,
                  numeric: true,
                  interactive: false,
                  get: (r) => (r.kind === "line" ? r.li.stock : null),
                  render: (r) => (r.kind === "line" ? stockCell(r.li) : "—"),
                },
              ]}
            />
          </div>

          {bom.costs.length > 0 ? (
            <div className="card pad">
              <div className="card-title">Manufacturing costs</div>
              <DataTable
                rows={bom.costs}
                rowKey={(c) => c.key}
                columns={[
                  { key: "label", label: "Item", width: 32, get: (c) => c.label },
                  {
                    key: "basis",
                    label: "Basis",
                    width: 13,
                    className: "muted",
                    get: (c) => (c.basis === "per_run" ? "per run" : "per device"),
                  },
                  {
                    key: "company",
                    label: "Company",
                    width: 18,
                    className: "muted",
                    get: (c) => c.company,
                    render: (c) => c.company || "—",
                  },
                  {
                    key: "price",
                    label: "Price",
                    width: 18,
                    numeric: true,
                    get: (c) => c.price_src,
                    render: (c) => `${c.price_src.toLocaleString()} ${c.currency}`,
                  },
                  {
                    key: "per_device",
                    label: `Per device @ ${bom.volume}`,
                    width: 19,
                    numeric: true,
                    get: (c) => c.per_device,
                    render: (c) => money(c.per_device, cur),
                  },
                ]}
              />
            </div>
          ) : null}

          <div className="card pad">
            <div className="card-title">Unit cost vs production volume</div>
            {curve ? <CostCurve points={curve} currency={cur} /> : <Spinner />}
          </div>

          {diff ? (
            <div className="card pad">
              <div className="card-title">
                BOM diff: {diff.from.ref} → {diff.to.ref}
              </div>
              {diff.added.length + diff.removed.length + diff.changed.length === 0 ? (
                <p className="muted">No BOM changes between these snapshots.</p>
              ) : (
                <DataTable
                  rows={[
                    ...diff.added.map((l, i) => ({
                      id: `a${i}`, change: "added", refs: l.refs, value: l.value,
                      lcsc: l.lcsc, qty: String(l.qty),
                    })),
                    ...diff.removed.map((l, i) => ({
                      id: `r${i}`, change: "removed", refs: l.refs, value: l.value,
                      lcsc: l.lcsc, qty: String(l.qty),
                    })),
                    ...diff.changed.map((c, i) => ({
                      id: `c${i}`, change: "changed", refs: c.to.refs,
                      value:
                        c.to.value +
                        (c.from.dnp !== c.to.dnp
                          ? ` (DNP ${String(c.from.dnp)} → ${String(c.to.dnp)})`
                          : ""),
                      lcsc: c.to.lcsc, qty: `${c.from.qty} → ${c.to.qty}`,
                    })),
                  ]}
                  rowKey={(r) => r.id}
                  columns={[
                    {
                      key: "change",
                      label: "Change",
                      width: 13,
                      get: (r) => r.change,
                      render: (r) => (
                        <span
                          className={`pill ${
                            r.change === "added" ? "ok" : r.change === "removed" ? "err" : "warn"
                          }`}
                        >
                          {r.change}
                        </span>
                      ),
                    },
                    { key: "refs", label: "Refs", width: 24, className: "mono", get: (r) => r.refs },
                    { key: "value", label: "Value", width: 33, get: (r) => r.value },
                    {
                      key: "lcsc",
                      label: "LCSC",
                      width: 15,
                      className: "mono",
                      get: (r) => r.lcsc,
                      render: (r) => r.lcsc || "—",
                    },
                    { key: "qty", label: "Qty", width: 15, numeric: true, get: (r) => r.qty },
                  ]}
                />
              )}
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
