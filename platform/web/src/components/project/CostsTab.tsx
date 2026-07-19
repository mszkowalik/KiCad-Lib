/** Manufacturing cost items (free-form labels, per-device / per-run, any
 *  currency) and extra BOM items (parts outside the schematic — linked to a
 *  library/BOM-only component or freehand priced).
 *
 *  The whole list is versioned against the project's git history: the list
 *  shown is the revision in effect at the selected snapshot's commit, and
 *  any edit made while viewing commit Y creates a new revision effective
 *  from Y FORWARD — earlier commits keep the older list (see
 *  api/app/services/cost_state.py). */
import { useEffect, useState } from "react";
import {
  addCostItem,
  addExtraItem,
  deleteCostItem,
  deleteExtraItem,
  errorMessage,
  getCostItems,
  getExtraItems,
  isAbortError,
  listComponents,
  updateCostItem,
  updateExtraItem,
  type CostItem,
  type CostItemIn,
  type CostRevisionInfo,
  type ExtraItem,
  type ExtraItemIn,
  type SnapshotInfo,
} from "../../api";
import DataTable from "../DataTable";
import { ErrorBanner, Spinner } from "../Ui";

const EMPTY_COST: CostItemIn = {
  label: "", basis: "per_device", price: 0, steps: [], currency: "USD",
  company: "", mpn: "", notes: "", position: 0,
};

const EMPTY_EXTRA: ExtraItemIn = {
  label: "", qty: 1, component_id: null, manufacturer: "", mpn: "",
  unit_price: null, currency: "USD", notes: "", position: 0,
};

/** Render a stepped price as explicit volume ranges ("1–999: 5.2 · ≥1000:
 *  3.8") — the base price is the qty-1 tier, so misconfigurations (e.g. a
 *  base price meant only for high volumes) become visible at a glance. */
function ladderText(basePrice: number, steps: { qty_from: number; price: number }[]): string {
  const sorted = [...steps].sort((a, b) => a.qty_from - b.qty_from);
  const tiers = [{ qty_from: 1, price: basePrice }, ...sorted];
  return tiers
    .map((t, i) => {
      const next = tiers[i + 1];
      const range =
        next === undefined
          ? `≥${t.qty_from}`
          : next.qty_from - 1 === t.qty_from
            ? `${t.qty_from}`
            : `${t.qty_from}–${next.qty_from - 1}`;
      return `${range}: ${t.price.toLocaleString()}`;
    })
    .join(" · ");
}

export default function CostsTab({
  projectId,
  snapshot,
}: {
  projectId: number;
  snapshot: SnapshotInfo | null;
}) {
  const [costs, setCosts] = useState<CostItem[] | null>(null);
  const [extras, setExtras] = useState<ExtraItem[] | null>(null);
  const [revision, setRevision] = useState<CostRevisionInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [costDraft, setCostDraft] = useState<CostItemIn>(EMPTY_COST);
  const [editCostId, setEditCostId] = useState<number | null>(null);
  const [extraDraft, setExtraDraft] = useState<ExtraItemIn>(EMPTY_EXTRA);
  const [editExtraId, setEditExtraId] = useState<number | null>(null);
  const [componentQuery, setComponentQuery] = useState("");
  const [componentHits, setComponentHits] = useState<{ id: number; name: string }[]>([]);

  const snapshotId = snapshot?.id ?? null;

  const load = (signal?: AbortSignal) => {
    getCostItems(projectId, snapshotId, signal)
      .then((r) => {
        setCosts(r.items);
        setRevision(r.revision);
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    getExtraItems(projectId, snapshotId, signal)
      .then((r) => setExtras(r.items))
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
  };

  useEffect(() => {
    const ctrl = new AbortController();
    setCosts(null);
    setExtras(null);
    load(ctrl.signal);
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, snapshotId]);

  // Component search for linking extra items (BOM-only parts included).
  useEffect(() => {
    if (!componentQuery.trim()) {
      setComponentHits([]);
      return;
    }
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      listComponents({ q: componentQuery.trim(), page_size: 8 }, ctrl.signal)
        .then((r) => setComponentHits(r.items.map((i) => ({ id: i.id, name: i.name }))))
        .catch(() => setComponentHits([]));
    }, 250);
    return () => {
      ctrl.abort();
      clearTimeout(t);
    };
  }, [componentQuery]);

  const saveCost = () => {
    const op = editCostId
      ? updateCostItem(editCostId, costDraft, snapshotId)
      : addCostItem(projectId, costDraft, snapshotId);
    op.then(() => {
      setCostDraft(EMPTY_COST);
      setEditCostId(null);
      load();
    }).catch((err) => {
      setError(errorMessage(err));
      load();
    });
  };

  const saveExtra = () => {
    const op = editExtraId
      ? updateExtraItem(editExtraId, extraDraft, snapshotId)
      : addExtraItem(projectId, extraDraft, snapshotId);
    op.then(() => {
      setExtraDraft(EMPTY_EXTRA);
      setEditExtraId(null);
      setComponentQuery("");
      load();
    }).catch((err) => {
      setError(errorMessage(err));
      load();
    });
  };

  // Which commit the shown list is anchored at, vs. which commit is viewed.
  const anchorLabel = revision
    ? revision.anchor_ref || (revision.anchor_sha ? revision.anchor_sha.slice(0, 8) : "the beginning")
    : null;
  const editsCreateNewRevision =
    snapshot !== null && (revision === null || revision.anchor_sha !== snapshot.sha);

  return (
    <div>
      {error ? <ErrorBanner message={error} /> : null}

      {snapshot === null ? (
        <p className="muted">
          No snapshot selected — showing the current cost list; edits apply to its latest
          version.
        </p>
      ) : revision === null && costs !== null ? (
        <p className="muted">
          No cost list exists at {snapshot.ref_name} ({snapshot.sha.slice(0, 8)}) yet — items
          added here take effect from this commit <b>forward</b> (earlier commits stay empty).
        </p>
      ) : revision !== null ? (
        editsCreateNewRevision ? (
          <div className="banner-warn">
            Cost list in effect since <b>{anchorLabel}</b>. You are viewing{" "}
            <span className="mono">{snapshot.ref_name} ({snapshot.sha.slice(0, 8)})</span> — any
            change here creates a new list version effective from this commit <b>forward</b>;
            earlier commits keep the list from {anchorLabel}.
          </div>
        ) : (
          <p className="muted">
            Cost list version created at this commit ({anchorLabel}) — edits update it in
            place and apply from here forward.
          </p>
        )
      ) : null}

      <div className="card pad">
        <div className="card-title">Manufacturing costs</div>
        <p className="muted">
          Free-form cost positions — PCB fab, assembly, enclosure rework, programming…
          "Per run" items are amortized over the production volume in the BOM view.
        </p>
        {costs === null ? <Spinner /> : null}
        {costs && costs.length > 0 ? (
          <DataTable
            rows={costs}
            rowKey={(c) => c.id}
            columns={[
              { key: "label", label: "Item", width: 22, get: (c) => c.label },
              {
                key: "basis",
                label: "Basis",
                width: 10,
                className: "muted",
                get: (c) => (c.basis === "per_run" ? "per run" : "per device"),
              },
              {
                key: "price",
                label: "Price",
                width: 22,
                numeric: true,
                className: "mono",
                get: (c) => c.price,
                render: (c) =>
                  c.steps.length > 0 ? (
                    <span title="Price by production volume — the tier covering the volume applies">
                      {ladderText(c.price, c.steps)} {c.currency}
                    </span>
                  ) : (
                    <>
                      {c.price.toLocaleString()} {c.currency}
                    </>
                  ),
                title: (c) =>
                  c.steps.length > 0
                    ? `${ladderText(c.price, c.steps)} ${c.currency}`
                    : `${c.price.toLocaleString()} ${c.currency}`,
              },
              {
                key: "company",
                label: "Company",
                width: 13,
                className: "muted",
                get: (c) => c.company,
                render: (c) => c.company || "—",
              },
              {
                key: "mpn",
                label: "MPN",
                width: 10,
                className: "mono",
                get: (c) => c.mpn,
                render: (c) => c.mpn || "—",
              },
              { key: "notes", label: "Notes", width: 11, className: "muted", get: (c) => c.notes },
              {
                key: "actions",
                label: "",
                width: 12,
                interactive: false,
                get: () => "",
                render: (c) => (
                  <>
                    <button
                      className="btn btn-sm"
                      onClick={() => {
                        setEditCostId(c.id);
                        setCostDraft({
                          label: c.label, basis: c.basis, price: c.price,
                          steps: c.steps.map((s) => ({ ...s })), currency: c.currency,
                          company: c.company, mpn: c.mpn, notes: c.notes, position: c.position,
                        });
                      }}
                    >
                      Edit
                    </button>{" "}
                    <button
                      className="btn btn-sm btn-danger"
                      onClick={() =>
                        deleteCostItem(c.id, snapshotId)
                          .then(() => load())
                          .catch((err) => {
                            setError(errorMessage(err));
                            load();
                          })
                      }
                    >
                      Delete
                    </button>
                  </>
                ),
              },
            ]}
          />
        ) : null}
        <div className="edit-grid">
          <label>
            Label
            <input className="text" value={costDraft.label} placeholder="PCB assembly"
              onChange={(e) => setCostDraft({ ...costDraft, label: e.target.value })} />
          </label>
          <label>
            Basis
            <select className="text" value={costDraft.basis}
              onChange={(e) => setCostDraft({ ...costDraft, basis: e.target.value })}>
              <option value="per_device">per device</option>
              <option value="per_run">per production run</option>
            </select>
          </label>
          <label>
            Price
            <input className="text" type="number" step="0.01" value={costDraft.price}
              onChange={(e) => setCostDraft({ ...costDraft, price: Number(e.target.value) })} />
          </label>
          <label>
            Currency
            <input className="text" value={costDraft.currency} maxLength={3}
              onChange={(e) => setCostDraft({ ...costDraft, currency: e.target.value.toUpperCase() })} />
          </label>
          <label>
            Company / manufacturer
            <input className="text" value={costDraft.company}
              onChange={(e) => setCostDraft({ ...costDraft, company: e.target.value })} />
          </label>
          <label>
            MPN <span className="muted">(if applies)</span>
            <input className="text" value={costDraft.mpn}
              onChange={(e) => setCostDraft({ ...costDraft, mpn: e.target.value })} />
          </label>
          <label>
            Notes
            <input className="text" value={costDraft.notes}
              onChange={(e) => setCostDraft({ ...costDraft, notes: e.target.value })} />
          </label>
        </div>
        <div className="cost-steps">
          <span className="muted">
            Price steps <span title="Quantity breaks: from this volume up, this price replaces the base price. The base price above is the qty-1 tier.">ⓘ</span>
          </span>
          {costDraft.steps.map((s, i) => (
            <span key={i} className="cost-step-row">
              ≥
              <input className="text step-qty" type="number" min="2" value={s.qty_from}
                aria-label={`Step ${i + 1} from quantity`}
                onChange={(e) => {
                  const steps = costDraft.steps.map((st, j) =>
                    j === i ? { ...st, qty_from: Number(e.target.value) } : st,
                  );
                  setCostDraft({ ...costDraft, steps });
                }} />
              pcs:
              <input className="text step-price" type="number" step="0.01" min="0" value={s.price}
                aria-label={`Step ${i + 1} price`}
                onChange={(e) => {
                  const steps = costDraft.steps.map((st, j) =>
                    j === i ? { ...st, price: Number(e.target.value) } : st,
                  );
                  setCostDraft({ ...costDraft, steps });
                }} />
              {costDraft.currency}
              <button type="button" className="row-del" title="Remove step"
                onClick={() =>
                  setCostDraft({ ...costDraft, steps: costDraft.steps.filter((_, j) => j !== i) })
                }>
                &#x2715;
              </button>
            </span>
          ))}
          <button type="button" className="btn btn-sm"
            onClick={() => {
              const last = costDraft.steps[costDraft.steps.length - 1];
              setCostDraft({
                ...costDraft,
                steps: [...costDraft.steps,
                  { qty_from: last ? last.qty_from * 10 : 10, price: costDraft.price }],
              });
            }}>
            ＋ Add price step
          </button>
          {costDraft.steps.length > 0 ? (
            <span className="muted mono cost-steps-preview">
              → {ladderText(costDraft.price, costDraft.steps)} {costDraft.currency}
            </span>
          ) : null}
        </div>
        <div className="btn-row">
          <button className="btn btn-primary btn-sm" disabled={!costDraft.label.trim()} onClick={saveCost}>
            {editCostId ? "Save changes" : "Add cost item"}
          </button>
          {editCostId ? (
            <button className="btn btn-sm" onClick={() => { setEditCostId(null); setCostDraft(EMPTY_COST); }}>
              Cancel edit
            </button>
          ) : null}
        </div>
      </div>

      <div className="card pad">
        <div className="card-title">Extra BOM items</div>
        <p className="muted">
          Parts not in the schematic — cables, enclosures, fasteners. Link a library
          component (including BOM-only parts, priced from its LCSC/manual ladder) or
          enter a freehand price. Quantity is per device.
        </p>
        {extras === null ? <Spinner /> : null}
        {extras && extras.length > 0 ? (
          <DataTable
            rows={extras}
            rowKey={(x) => x.id}
            columns={[
              { key: "label", label: "Item", width: 24, get: (x) => x.label },
              { key: "qty", label: "Qty/dev", width: 8, numeric: true, get: (x) => x.qty },
              {
                key: "component",
                label: "Component",
                width: 13,
                className: "muted",
                get: (x) => (x.component_id ? `#${x.component_id}` : ""),
                render: (x) => (x.component_id ? `#${x.component_id}` : "—"),
              },
              {
                key: "manufacturer",
                label: "Manufacturer",
                width: 15,
                className: "muted",
                get: (x) => x.manufacturer,
                render: (x) => x.manufacturer || "—",
              },
              {
                key: "mpn",
                label: "MPN",
                width: 13,
                className: "mono",
                get: (x) => x.mpn,
                render: (x) => x.mpn || "—",
              },
              {
                key: "unit_price",
                label: "Unit price",
                width: 15,
                numeric: true,
                className: "mono",
                get: (x) => x.unit_price,
                render: (x) =>
                  x.unit_price != null ? `${x.unit_price} ${x.currency}` : "from ladder",
              },
              {
                key: "actions",
                label: "",
                width: 12,
                interactive: false,
                get: () => "",
                render: (x) => (
                  <>
                    <button
                      className="btn btn-sm"
                      onClick={() => {
                        setEditExtraId(x.id);
                        setExtraDraft({
                          label: x.label, qty: x.qty, component_id: x.component_id,
                          manufacturer: x.manufacturer, mpn: x.mpn, unit_price: x.unit_price,
                          currency: x.currency, notes: x.notes, position: x.position,
                        });
                      }}
                    >
                      Edit
                    </button>{" "}
                    <button
                      className="btn btn-sm btn-danger"
                      onClick={() =>
                        deleteExtraItem(x.id, snapshotId)
                          .then(() => load())
                          .catch((err) => {
                            setError(errorMessage(err));
                            load();
                          })
                      }
                    >
                      Delete
                    </button>
                  </>
                ),
              },
            ]}
          />
        ) : null}
        <div className="edit-grid">
          <label>
            Label
            <input className="text" value={extraDraft.label} placeholder="SMA – u.FL cable"
              onChange={(e) => setExtraDraft({ ...extraDraft, label: e.target.value })} />
          </label>
          <label>
            Qty per device
            <input className="text" type="number" step="0.1" min="0" value={extraDraft.qty}
              onChange={(e) => setExtraDraft({ ...extraDraft, qty: Number(e.target.value) })} />
          </label>
          <label>
            Link component <span className="muted">(search; empty = freehand)</span>
            <input className="text" value={componentQuery}
              placeholder={extraDraft.component_id ? `linked #${extraDraft.component_id}` : "search by name / LCSC…"}
              onChange={(e) => setComponentQuery(e.target.value)} />
            {componentHits.length > 0 ? (
              <span className="proj-hits">
                {componentHits.map((h) => (
                  <button key={h.id} type="button" className="btn btn-sm"
                    onClick={() => {
                      setExtraDraft({ ...extraDraft, component_id: h.id });
                      setComponentQuery("");
                      setComponentHits([]);
                    }}>
                    {h.name}
                  </button>
                ))}
              </span>
            ) : null}
            {extraDraft.component_id ? (
              <span className="muted">
                linked #{extraDraft.component_id}{" "}
                <button type="button" className="btn btn-sm"
                  onClick={() => setExtraDraft({ ...extraDraft, component_id: null })}>
                  unlink
                </button>
              </span>
            ) : null}
          </label>
          <label>
            Unit price <span className="muted">(ignored when linked)</span>
            <input className="text" type="number" step="0.0001" min="0"
              value={extraDraft.unit_price ?? ""}
              onChange={(e) =>
                setExtraDraft({
                  ...extraDraft,
                  unit_price: e.target.value === "" ? null : Number(e.target.value),
                })
              } />
          </label>
          <label>
            Currency
            <input className="text" value={extraDraft.currency} maxLength={3}
              onChange={(e) => setExtraDraft({ ...extraDraft, currency: e.target.value.toUpperCase() })} />
          </label>
          <label>
            Manufacturer
            <input className="text" value={extraDraft.manufacturer}
              onChange={(e) => setExtraDraft({ ...extraDraft, manufacturer: e.target.value })} />
          </label>
          <label>
            MPN
            <input className="text" value={extraDraft.mpn}
              onChange={(e) => setExtraDraft({ ...extraDraft, mpn: e.target.value })} />
          </label>
          <label>
            Notes
            <input className="text" value={extraDraft.notes}
              onChange={(e) => setExtraDraft({ ...extraDraft, notes: e.target.value })} />
          </label>
        </div>
        <div className="btn-row">
          <button className="btn btn-primary btn-sm" disabled={!extraDraft.label.trim()} onClick={saveExtra}>
            {editExtraId ? "Save changes" : "Add extra item"}
          </button>
          {editExtraId ? (
            <button className="btn btn-sm"
              onClick={() => { setEditExtraId(null); setExtraDraft(EMPTY_EXTRA); setComponentQuery(""); }}>
              Cancel edit
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
