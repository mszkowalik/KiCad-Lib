import { useCallback, useEffect, useMemo, useState } from "react";
import {
  errorMessage,
  getAllChecklists,
  getCategories,
  getChecklistCoverage,
  getChecklistMeta,
  isAbortError,
  saveChecklistScope,
  type CheckParamValue,
  type ChecklistItem,
  type ChecklistMeta,
  type ChecklistScopeRows,
  type ReviewKind,
  type VariantCoverage,
} from "../api";
import DataTable, { type Column } from "../components/DataTable";
import { flattenCats } from "../components/editing";
import Field from "../components/Field";
import SiInput from "../components/SiInput";
import { ErrorBanner, Spinner } from "../components/Ui";

/**
 * Every check in the platform, in ONE table.
 *
 * The screen has been three shapes. One sidebar entry per checklist became
 * sixteen entries the moment every category stated its own rules. One tab per
 * kind with a scope dropdown fixed that, but you could still only look at one
 * scope at a time — so "which categories change `cmp.required_props`, and for
 * which transistor types" meant opening scopes one by one and holding the
 * answer in your head. This is the third shape and the right one: one row per
 * (scope, check), and the question is a column filter.
 *
 * Five things this screen has to be honest about, or it quietly breaks reviews:
 *
 * 1. **It goes through `DataTable`**, like every other list here — per-column
 *    filter row, sortable headers, expandable rows, remembered across
 *    navigation. The two earlier shapes hand-rolled a table with their own
 *    filter chips, which is exactly what `web/CLAUDE.md` forbids and why the
 *    filtering was weaker than the browse page's.
 * 2. **Rows are what a scope STATES, not the cross product.** Sixteen component
 *    checks against nineteen scopes is three hundred rows of "not stated". The
 *    base lists state everything, so the catalogue is covered; a category
 *    contributes only what it changes.
 * 3. **The validator owns WHAT each automatic check does.** Rows come from
 *    `validator.machine_checks`; their wording is never typed here — the API
 *    rewrites it on save from the row's own `params`. An automatic item whose
 *    text disagrees with the number the code compares against is worse than no
 *    item, because the reviewer believes the text.
 * 4. **A row is FOLDED to what you scan for.** Settings, the `when` predicate
 *    and a judgment check's wording are behind the row's expansion: one check
 *    can carry four regular expressions.
 * 5. **Editing this list changes nothing already recorded.** Switching a check
 *    off stops it running, but the `failed` answer it already wrote is copied
 *    forward by every later record. "Apply to existing parts" is the one button
 *    that clears those, and it cannot touch a human or agent answer.
 *
 * **Publishing is per scope.** A checklist version belongs to one scope, so
 * editing rows from three scopes and pressing Publish writes three versions.
 * The toolbar says how many before you press it — silently publishing three
 * documents from one button would be the kind of thing nobody forgives.
 */
type Item = ChecklistItem;

const KIND_LABEL: Record<ReviewKind, string> = {
  component: "Component",
  symbol: "Symbol",
  footprint: "Footprint",
};

/** A scope is addressed by (kind, category) — never by checklist id, which does
 *  not exist until the scope states something for the first time. */
type ScopeKey = string;
const scopeKey = (kind: ReviewKind, categoryId: number | null): ScopeKey =>
  `${kind}:${categoryId ?? ""}`;

interface Scope {
  key: ScopeKey;
  id: number | null;
  kind: ReviewKind;
  categoryId: number | null;
  label: string;
  versionNo: number | null;
}

/** One line of the table: a check, in one scope.
 *
 *  The FIRST row is a draft — the same seven columns, with Kind, Scope, Key and
 *  the text editable in place, so a new check is defined where every existing
 *  one is read. It replaced a scope dropdown and an Add button in the toolbar,
 *  which sat above the filter row, looked like a filter for the table, and made
 *  "which scope am I adding to" a separate question from "what am I adding".
 *  `DataTable`'s `group` pins it first whatever the sort; a column filter hides
 *  it like any other row, which is correct — filtering is looking, not adding.
 */
interface Row {
  key: string;
  scope: Scope;
  item: Item;
  machine: boolean;
  draft?: boolean;
  /** `validator`'s defaults for this check, so a changed setting reads as changed. */
  defaults?: Record<string, CheckParamValue>;
}

const PARAM_LABELS: Record<string, string> = {
  crtyd_line_width_mm: "Courtyard line width",
  fab_line_width_mm: "F.Fab line width",
  silk_line_width_mm: "F.SilkS line width",
  silk_polarity_mark_width_mm: "Polarity mark width",
  coordinate_grid_mm: "Coordinate grid",
  min_drill_diameter: "Smallest drill",
  min_pad_size: "Smallest through-hole pad",
  min_via_size: "Smallest via pad",
  min_via_drill: "Smallest via drill",
  thermal_via_warning_only: "A thermal via may go below it",
  pin_grid_mm: "Pin grid",
  required_properties: "Must be present",
  non_empty_properties: "Must not be empty",
  manufacturer_properties: "Any one of these",
  allowed_base_symbols: "Base symbols allowed",
  namespace: "Namespace",
  pattern: "Pattern",
  patterns: "Patterns",
};

/** The assertions a declarative check may make. Closed on purpose: ONE fact and
 *  ONE assertion. Needing two joined by a boolean, or arithmetic between facts,
 *  means it has stopped being a check and become a rules language — which is
 *  what `models.Rule` was and what this platform spent 2026-09-14 deleting.
 *
 *  The list is local because the LABEL and the input SHAPE are the UI's own;
 *  `validator.ASSERTIONS` is the authority on which keys exist, and the loader
 *  warns when it offers one this file cannot render. A comparison between two
 *  facts never belongs here — it belongs in a derived FACT, in Python. */
const ASSERTIONS = [
  { key: "one_of", label: "is one of", shape: "list" },
  { key: "matches", label: "matches", shape: "text" },
  { key: "equals", label: "is exactly", shape: "text" },
  { key: "at_least", label: "is at least", shape: "number" },
  { key: "at_most", label: "is at most", shape: "number" },
  { key: "present", label: "is present", shape: "none" },
] as const;

type AssertSpec = NonNullable<Item["assert"]>;

const assertionOf = (spec: AssertSpec) =>
  ASSERTIONS.find((a) => a.key in spec) ?? ASSERTIONS[0];

/** One fact, one assertion. The check's sentence is GENERATED from this by the
 *  API, so there is no text box here: a sentence typed beside a rule can
 *  disagree with it, and the reviewer believes the sentence. */
function AssertEditor({
  spec,
  onChange,
}: {
  spec: AssertSpec;
  onChange: (next: AssertSpec) => void;
}) {
  const current = assertionOf(spec);
  const set = (name: string, value: unknown) => onChange({ fact: spec.fact, [name]: value });
  return (
    <Field
      label="Checks that"
      hint="One fact, one assertion. The check's wording is written from it."
    >
      <div className="param-pattern">
        <input
          className="text row-input mono"
          value={spec.fact}
          list="when-facts"
          placeholder="$symbol_reference"
          aria-label="Fact the check reads"
          onChange={(e) => onChange({ ...spec, fact: e.target.value })}
        />
        <select
          className="text row-input"
          value={current.key}
          aria-label="What it asserts"
          onChange={(e) => {
            const next = ASSERTIONS.find((a) => a.key === e.target.value) ?? ASSERTIONS[0];
            set(
              next.key,
              next.shape === "list" ? [] : next.shape === "number" ? 1 : next.shape === "none" ? true : "",
            );
          }}
        >
          {ASSERTIONS.map((a) => (
            <option key={a.key} value={a.key}>
              {a.label}
            </option>
          ))}
        </select>
        {current.shape === "none" ? null : current.shape === "list" ? (
          <input
            className="text row-input"
            value={(spec.one_of ?? []).join(", ")}
            placeholder="J, CN, BAT"
            aria-label="Accepted values"
            onChange={(e) =>
              set(
                "one_of",
                e.target.value
                  .split(",")
                  .map((x) => x.trim())
                  .filter(Boolean),
              )
            }
          />
        ) : current.shape === "number" ? (
          <input
            className="text row-input num-input"
            type="number"
            value={String((spec[current.key as "at_least" | "at_most"] ?? 0) as number)}
            aria-label="Value it is compared against"
            onChange={(e) => set(current.key, Number(e.target.value))}
          />
        ) : (
          <input
            className="text row-input mono"
            value={String(spec[current.key as "matches" | "equals"] ?? "")}
            placeholder={current.key === "matches" ? "^J$" : "J"}
            aria-label="Value it is compared against"
            onChange={(e) => set(current.key, e.target.value)}
          />
        )}
      </div>
    </Field>
  );
}

/** What a failing check means, and — at `ignore` — whether it runs here.
 *  One control with three values. It replaced an on/off switch beside a missing
 *  severity, which is why four checks used to ship "off" when what was meant
 *  was "on, but not urgent". */
const SEVERITIES = [
  { key: "error", label: "Error", tone: "err", hint: "a failure is a defect and fails the part" },
  { key: "warning", label: "Warning", tone: "warn", hint: "worth seeing; never fails the part" },
  { key: "ignore", label: "Ignore", tone: "neutral", hint: "does not run here at all" },
] as const;

const severityOf = (item: Item): "error" | "warning" | "ignore" =>
  item.severity ?? (item.disabled ? "ignore" : "error");

const whenSummary = (when?: Record<string, string>): string =>
  when && Object.keys(when).length
    ? Object.entries(when)
        .map(([f, p]) => `${f} ${p}`)
        .join(" and ")
    : "always";

function CheckParams({
  params,
  defaults,
  disabled,
  onChange,
}: {
  params: Record<string, CheckParamValue>;
  defaults: Record<string, CheckParamValue>;
  disabled: boolean;
  onChange: (next: Record<string, CheckParamValue>) => void;
}) {
  const set = (name: string, value: CheckParamValue) => onChange({ ...params, [name]: value });
  return (
    <div className="check-params">
      {Object.entries(params).map(([name, value]) => {
        const label = PARAM_LABELS[name] ?? name;
        const fallback = defaults[name];
        const changed = JSON.stringify(fallback) !== JSON.stringify(value);
        if (typeof value === "boolean") {
          return (
            <label key={name} className="field-check">
              <input
                type="checkbox"
                checked={value}
                disabled={disabled}
                onChange={(e) => set(name, e.target.checked)}
              />
              <span>{label}</span>
            </label>
          );
        }
        if (typeof value === "number") {
          return (
            <Field key={name} label={label} hint={changed ? `default ${fallback}` : undefined}>
              <SiInput
                value={value}
                quantity="length"
                min={0}
                disabled={disabled}
                validate={(v) => (v > 0 ? "" : "must be above zero")}
                aria-label={label}
                onChange={(v) => set(name, v)}
              />
            </Field>
          );
        }
        if (Array.isArray(value)) {
          return (
            <Field key={name} label={label} hint="Comma-separated">
              <input
                className="text row-input"
                value={value.join(", ")}
                disabled={disabled}
                aria-label={label}
                onChange={(e) =>
                  set(
                    name,
                    e.target.value
                      .split(",")
                      .map((x) => x.trim())
                      .filter(Boolean),
                  )
                }
              />
            </Field>
          );
        }
        if (typeof value === "object") {
          const rows = Object.entries(value);
          return (
            <Field key={name} label={label} hint="One regular expression per property">
              {rows.map(([prop, expr], index) => (
                <div key={`${index}-${prop}`} className="param-pattern">
                  <input
                    className="text row-input mono"
                    value={prop}
                    disabled={disabled}
                    placeholder="Property"
                    aria-label="Property the pattern applies to"
                    onChange={(e) =>
                      set(
                        name,
                        Object.fromEntries(
                          rows.map(([k, v], n) => (n === index ? [e.target.value, v] : [k, v])),
                        ),
                      )
                    }
                  />
                  <input
                    className="text row-input mono"
                    value={expr}
                    disabled={disabled}
                    placeholder="^pattern$"
                    aria-label={`Pattern for ${prop}`}
                    onChange={(e) =>
                      set(
                        name,
                        Object.fromEntries(
                          rows.map(([k, v], n) => (n === index ? [k, e.target.value] : [k, v])),
                        ),
                      )
                    }
                  />
                  <button
                    type="button"
                    className="btn btn-sm btn-danger"
                    disabled={disabled}
                    onClick={() =>
                      set(name, Object.fromEntries(rows.filter((_, n) => n !== index)))
                    }
                  >
                    ✕
                  </button>
                </div>
              ))}
              <button
                type="button"
                className="btn btn-sm"
                disabled={disabled}
                onClick={() => set(name, { ...value, "New property": "^.*$" })}
              >
                Add a pattern
              </button>
            </Field>
          );
        }
        return (
          <Field
            key={name}
            label={label}
            hint={changed ? `default ${String(fallback)}` : undefined}
          >
            <input
              className="text row-input mono"
              value={String(value)}
              disabled={disabled}
              aria-label={label}
              onChange={(e) => set(name, e.target.value)}
            />
          </Field>
        );
      })}
    </div>
  );
}

function WhenEditor({
  when,
  onChange,
}: {
  when: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
}) {
  const rows = Object.entries(when);
  return (
    <Field
      label="Applies when"
      hint={
        rows.length === 0
          ? "Always. Add a condition to narrow it — a property name, or a $fact."
          : "Every condition must match. The value is a regular expression."
      }
    >
      {rows.map(([field, pattern], index) => (
        <div key={`${index}-${field}`} className="param-pattern">
          <input
            className="text row-input mono"
            value={field}
            list="when-facts"
            placeholder="comp_type"
            aria-label="Field the condition reads"
            onChange={(e) =>
              onChange(
                Object.fromEntries(
                  rows.map(([f, p], n) => (n === index ? [e.target.value, p] : [f, p])),
                ),
              )
            }
          />
          <input
            className="text row-input mono"
            value={pattern}
            placeholder="^TVS$"
            aria-label={`Pattern for ${field}`}
            onChange={(e) =>
              onChange(
                Object.fromEntries(
                  rows.map(([f, p], n) => (n === index ? [f, e.target.value] : [f, p])),
                ),
              )
            }
          />
          <button
            type="button"
            className="btn btn-sm btn-danger"
            onClick={() => onChange(Object.fromEntries(rows.filter((_, n) => n !== index)))}
          >
            ✕
          </button>
        </div>
      ))}
      <button
        type="button"
        className="btn btn-sm"
        onClick={() => onChange({ ...when, comp_type: "^.*$" })}
      >
        Add a condition
      </button>
    </Field>
  );
}

/** How the live parts in this scope fall across a key's variants.
 *
 *  This is the mitigation for the one hazard variants cannot design away: a
 *  variant keyed on a PROPERTY is only as reliable as that property. A category
 *  is a row; `comp_type` is free text, and this library already carries `ZENNER`
 *  with an extra "n". A misspelled value makes a part fall silently through to
 *  the fallback — no failure, no warning, nothing to notice.
 *
 *  **A non-zero "no match" on a settled category means the discriminator is not
 *  reliable**, and that category wants a subcategory rather than a predicate.
 *  Fetched only when a row is open, so it costs nothing until somebody asks. */
function Coverage({
  kind,
  itemKey,
  categoryId,
}: {
  kind: ReviewKind;
  itemKey: string;
  categoryId: number | null;
}) {
  const [cov, setCov] = useState<VariantCoverage | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    setCov(null);
    getChecklistCoverage(kind, itemKey, categoryId, ctrl.signal)
      .then(setCov)
      .catch(() => {
        /* a count is a convenience; the editor works without it */
      });
    return () => ctrl.abort();
  }, [kind, itemKey, categoryId]);

  if (kind !== "component") return null;
  if (cov === null) return <p className="rail-hint">Counting parts…</p>;
  return (
    <p className="rail-hint">
      {cov.total} part(s) in scope
      {cov.counts.map((c) => (
        <span key={c.variant}>
          {" · "}
          <span className="mono">{c.variant}</span> {c.count}
        </span>
      ))}
      {cov.no_match > 0 ? (
        <span className="pill err" title="Nothing in this key's variants is about these parts">
          {" "}
          no match {cov.no_match}
        </span>
      ) : null}
    </p>
  );
}

export default function Checklists() {
  const [data, setData] = useState<ChecklistScopeRows | null>(null);
  const [meta, setMeta] = useState<ChecklistMeta | null>(null);
  const [cats, setCats] = useState<{ id: number; label: string }[]>([]);
  /** Edited items per scope. A scope absent here is untouched. */
  const [edits, setEdits] = useState<Record<ScopeKey, Item[]>>({});
  const [draft, setDraft] = useState<{ scope: ScopeKey; key: string; text: string }>({
    scope: "component:",
    key: "",
    text: "",
  });
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(
    (signal?: AbortSignal) =>
      Promise.all([getAllChecklists(signal), getChecklistMeta(signal)])
        .then(([all, m]) => {
          setData(all);
          setMeta(m);
          setEdits({});
          // The labels and input shapes below are the UI's, so the list stays
          // local — but an assertion the validator has and this file does not
          // would be silently unselectable. Say so instead.
          const missing = m.assertions.filter((a) => !ASSERTIONS.some((x) => x.key === a));
          if (missing.length) {
            console.warn(
              `Checklists: the validator offers assertions this editor cannot render: ${missing.join(", ")}. ` +
                "Add them to ASSERTIONS in web/src/pages/Checklists.tsx.",
            );
          }
        })
        .catch((err) => {
          if (!isAbortError(err)) setError(errorMessage(err));
        }),
    [],
  );

  useEffect(() => {
    const ctrl = new AbortController();
    void load(ctrl.signal);
    getCategories(ctrl.signal)
      .then((tree) => setCats(flattenCats(tree)))
      .catch(() => setCats([]));
    return () => ctrl.abort();
  }, [load]);

  /** Every scope that exists, plus every category that could state something —
   *  the second kind is what "add a check to Relays" needs before Relays has a
   *  list at all. */
  const scopes: Scope[] = useMemo(() => {
    const out: Scope[] = [];
    for (const s of data?.scopes ?? []) {
      out.push({
        key: scopeKey(s.subject_kind, s.category_id),
        id: s.id,
        kind: s.subject_kind,
        categoryId: s.category_id,
        label: s.category_path ?? `base — every ${s.subject_kind}`,
        versionNo: s.version_no,
      });
    }
    const have = new Set(out.map((s) => s.key));
    for (const c of cats) {
      const k = scopeKey("component", c.id);
      if (!have.has(k)) {
        out.push({
          key: k,
          id: null,
          kind: "component",
          categoryId: c.id,
          label: c.label.replace(/^(— )+/, ""),
          versionNo: null,
        });
      }
    }
    return out;
  }, [data, cats]);

  const scopeByKey = useMemo(() => new Map(scopes.map((s) => [s.key, s])), [scopes]);

  /** The stored items of a scope, or the edited ones when it has been touched. */
  const itemsOf = useCallback(
    (key: ScopeKey): Item[] => {
      if (edits[key]) return edits[key];
      const s = data?.scopes.find((x) => scopeKey(x.subject_kind, x.category_id) === key);
      return s?.items ?? [];
    },
    [edits, data],
  );

  const setItems = useCallback(
    (key: ScopeKey, next: Item[]) => setEdits((prev) => ({ ...prev, [key]: next })),
    [],
  );

  /** Addressed by (key, variant): a key may hold several variants, so the key
   *  alone would edit or delete the wrong one. */
  const patch = useCallback(
    (key: ScopeKey, item: Item, next: Item | null) => {
      const same = (i: Item) => i.key === item.key && (i.variant ?? "") === (item.variant ?? "");
      setItems(
        key,
        next === null ? itemsOf(key).filter((i) => !same(i)) : itemsOf(key).map((i) => (same(i) ? next : i)),
      );
    },
    [itemsOf, setItems],
  );

  const defaultsByKey = useMemo(() => {
    const out = new Map<string, Record<string, CheckParamValue>>();
    for (const kind of Object.keys(meta?.machine_checks ?? {})) {
      for (const c of meta?.machine_checks[kind] ?? []) {
        if (c.defaults) out.set(`${kind}:${c.key}`, c.defaults);
      }
    }
    return out;
  }, [meta]);

  const rows: Row[] = useMemo(() => {
    const draftScope = scopes.find((s) => s.key === draft.scope) ?? scopes[0];
    const out: Row[] = draftScope
      ? [
          {
            key: "__draft__",
            scope: draftScope,
            item: { key: draft.key, text: draft.text },
            machine: false,
            draft: true,
          },
        ]
      : [];
    for (const s of scopes) {
      for (const item of itemsOf(s.key)) {
        out.push({
          key: `${s.key}|${item.key}|${item.variant ?? ""}`,
          scope: s,
          item,
          machine: Boolean(item.machine),
          defaults: defaultsByKey.get(`${s.kind}:${item.key}`),
        });
      }
    }
    return out;
  }, [scopes, itemsOf, defaultsByKey, draft]);

  const dirtyScopes = useMemo(
    () =>
      Object.keys(edits).filter((k) => {
        const stored = data?.scopes.find((x) => scopeKey(x.subject_kind, x.category_id) === k);
        return JSON.stringify(edits[k]) !== JSON.stringify(stored?.items ?? []);
      }),
    [edits, data],
  );

  const problems = useMemo(() => {
    const out: string[] = [];
    for (const key of dirtyScopes) {
      const seen = new Set<string>();
      for (const i of edits[key]) {
        if (!i.key.trim()) out.push(`${scopeByKey.get(key)?.label}: an item has no key`);
        const id = `${i.key}|${i.variant ?? ""}`;
        if (seen.has(id))
          out.push(
            `${scopeByKey.get(key)?.label}: ${i.key} is stated twice` +
              (i.variant ? ` for variant ${i.variant}` : " with no variant"),
          );
        seen.add(id);
        if (!i.machine && !i.text.trim())
          out.push(`${scopeByKey.get(key)?.label}: ${i.key} needs a text`);
      }
    }
    return [...new Set(out)];
  }, [dirtyScopes, edits, scopeByKey]);

  /** Turn the draft row into a real pending item on its scope, and clear it. */
  const commitDraft = () => {
    const scope = scopeByKey.get(draft.scope);
    const key = draft.key.trim();
    if (!scope || !key) return;
    if (itemsOf(scope.key).some((i) => i.key === key)) return;
    setItems(scope.key, [...itemsOf(scope.key), { key, text: draft.text.trim() }]);
    setDraft((d) => ({ ...d, key: "", text: "" }));
  };

  const draftReady =
    draft.key.trim().length > 0 &&
    draft.text.trim().length > 0 &&
    !itemsOf(draft.scope).some((i) => i.key === draft.key.trim());

  const publish = async () => {
    if (problems.length > 0 || dirtyScopes.length === 0) return;
    setBusy(true);
    setError(null);
    const done: string[] = [];
    try {
      for (const key of dirtyScopes) {
        const s = scopeByKey.get(key);
        if (!s) continue;
        const out = await saveChecklistScope(
          s.kind,
          s.categoryId,
          edits[key],
          comment.trim() || undefined,
        );
        done.push(out.exists ? `${s.label} v${out.version_no}` : `${s.label} (removed)`);
      }
      setComment("");
      await load();
      setNotice(`Published: ${done.join(", ")}.`);
    } catch (err) {
      setError(
        `${errorMessage(err)}${done.length ? ` — already published: ${done.join(", ")}` : ""}`,
      );
      await load();
    } finally {
      setBusy(false);
    }
  };


  const columns: Column<Row>[] = useMemo(
    () => [
      {
        key: "kind",
        label: "Kind",
        width: 9,
        get: (r) => (r.draft ? "" : KIND_LABEL[r.scope.kind]),
        render: (r) => (r.draft ? <span className="badge">new</span> : KIND_LABEL[r.scope.kind]),
      },
      {
        key: "scope",
        label: "Scope",
        width: 15,
        // `Transistors.NMOS` — the second tier is the variant's own name, not
        // a value parsed back out of the predicate, so a variant with a
        // complex condition still gets a label.
        get: (r) => (r.draft ? "" : r.scope.label + (r.item.variant ? `.${r.item.variant}` : "")),
        render: (r) =>
          r.draft ? (
            <select
              className="text row-input mono"
              aria-label="Scope the new check is added to"
              value={draft.scope}
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => setDraft((d) => ({ ...d, scope: e.target.value }))}
            >
              {scopes.map((sc) => (
                <option key={sc.key} value={sc.key}>
                  {KIND_LABEL[sc.kind]} · {sc.label}
                </option>
              ))}
            </select>
          ) : (
          <>
            {r.scope.categoryId === null ? (
              <span className="pill neutral">base</span>
            ) : (
              r.scope.label
            )}
            {r.item.variant ? <span className="mono">.{r.item.variant}</span> : null}
          </>
          ),
      },
      {
        key: "check",
        label: "Key",
        width: 17,
        className: "mono",
        get: (r) => (r.draft ? "" : r.item.key),
        render: (r) =>
          r.draft ? (
            <input
              className="text row-input mono"
              value={draft.key}
              placeholder="cmp.something"
              aria-label="Key for the new check"
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => setDraft((d) => ({ ...d, key: e.target.value.trim() }))}
            />
          ) : (
            r.item.key
          ),
      },
      {
        key: "text",
        label: "What it checks",
        width: 30,
        get: (r) => (r.draft ? "" : r.item.text),
        render: (r) =>
          r.draft ? (
            <input
              className="text row-input"
              value={draft.text}
              placeholder="What a reviewer must confirm"
              aria-label="What the new check asks"
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => setDraft((d) => ({ ...d, text: e.target.value }))}
            />
          ) : (
            r.item.text
          ),
      },
      {
        key: "type",
        label: "Type",
        width: 8,
        get: (r) => (r.draft ? "" : r.machine ? "automatic" : "judgment"),
        render: (r) =>
          r.machine ? <span className="badge">auto</span> : <span className="muted">judgment</span>,
      },
      {
        key: "when",
        label: "Applies when",
        width: 14,
        className: "mono",
        get: (r) => (r.draft ? "" : whenSummary(r.item.when)),
        render: (r) =>
          r.item.when && Object.keys(r.item.when).length ? (
            <span title={whenSummary(r.item.when)}>{whenSummary(r.item.when)}</span>
          ) : (
            <span className="muted">always</span>
          ),
      },
      {
        key: "severity",
        label: "On failure",
        width: 9,
        get: (r) => (r.draft ? "" : severityOf(r.item)),
        render: (r) =>
          r.draft ? (
            <button
              type="button"
              className="btn btn-sm btn-accent"
              disabled={!draftReady}
              title={
                draftReady
                  ? "Add it to the scope chosen on this row"
                  : "Give it a key and a text first"
              }
              onClick={(e) => {
                e.stopPropagation();
                commitDraft();
              }}
            >
              Add
            </button>
          ) : (
            (() => {
              const sev = SEVERITIES.find((x) => x.key === severityOf(r.item)) ?? SEVERITIES[0];
              return (
                <span className={`pill ${sev.tone}`} title={sev.hint}>
                  {sev.label}
                </span>
              );
            })()
          ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [draft, draftReady, scopes],
  );

  const expand = (r: Row) => {
    // The draft row has nothing to expand: it IS the form, in its own cells.
    if (r.draft) return null;
    const scope = r.scope;
    const item = r.item;
    // The vocabulary of THIS row's subject kind — a footprint rule must not be
    // offered `$category`, which a footprint has not got.
    const facts = meta?.facts?.[scope.kind] ?? [];
    const update = (next: Partial<Item>) => patch(scope.key, item, { ...item, ...next });
    return (
      <div className="check-detail-panel">
        {/* ONE datalist for the panel. It used to live inside `WhenEditor`,
            so the assert editor's fact box only offered completions while a
            `when` row happened to be rendered beside it. */}
        <datalist id="when-facts">
          {facts.map((f) => (
            <option key={f.name} value={f.name}>
              {f.what}
            </option>
          ))}
        </datalist>
        {item.hint ? <p className="muted">{item.hint}</p> : null}
        <div className="btn-row">
          <div className="seg">
            {SEVERITIES.map((sev) => (
              <button
                key={sev.key}
                type="button"
                className={severityOf(item) === sev.key ? "on" : ""}
                title={sev.hint}
                // `disabled` is the retired spelling; clear it whenever the
                // severity is set, so an old item never carries both.
                onClick={() => update({ severity: sev.key, disabled: undefined })}
              >
                {sev.label}
              </button>
            ))}
          </div>
          {scope.categoryId !== null ? (
            <button
              type="button"
              className="btn btn-sm"
              title="Stop stating this check here, so it is inherited again"
              onClick={() => patch(scope.key, item, null)}
            >
              Inherit again
            </button>
          ) : null}
          {/* No "apply to existing parts": conformance is computed on read and
              its cache is keyed on a digest of the checklist, so saving this
              re-evaluates every subject on its next read. The button existed
              only because machine answers used to be stored. */}
        </div>

        {!r.machine ? (
          <>
            <Field label="What a reviewer must confirm">
              <input
                className="text"
                value={item.text}
                aria-label={`Text for ${item.key}`}
                onChange={(e) => update({ text: e.target.value })}
              />
            </Field>
            <Field label="Hint" hint="Optional — where to look">
              <input
                className="text"
                value={item.hint ?? ""}
                aria-label={`Hint for ${item.key}`}
                onChange={(e) => update({ hint: e.target.value || undefined })}
              />
            </Field>
          </>
        ) : item.assert ? (
          <AssertEditor spec={item.assert} onChange={(next) => update({ assert: next })} />
        ) : item.params ? (
          <CheckParams
            params={item.params}
            defaults={r.defaults ?? {}}
            disabled={severityOf(item) === "ignore"}
            onChange={(next) => update({ params: next })}
          />
        ) : (
          <>
            <p className="muted">This check takes no settings — it either runs or it does not.</p>
            {!item.machine ? (
              <button
                type="button"
                className="btn btn-sm"
                title="Answer it from a fact about the part instead of asking a person"
                onClick={() =>
                  update({
                    machine: true,
                    assert: { fact: "$symbol_reference", one_of: [] },
                  })
                }
              >
                Make it automatic
              </button>
            ) : null}
          </>
        )}

        <WhenEditor
          when={item.when ?? {}}
          onChange={(next) => update({ when: Object.keys(next).length ? next : undefined })}
        />

        <Field
          label="Variant"
          hint={
            "Name it to state this key more than once — one variant per value of ONE field, " +
            "plus at most one with no condition as the fallback. The name is the label: " +
            "the Scope column reads Transistors.NMOS from it."
          }
        >
          <input
            className="text row-input mono"
            value={item.variant ?? ""}
            placeholder="NMOS"
            aria-label={`Variant name for ${item.key}`}
            onChange={(e) => update({ variant: e.target.value.trim() || undefined })}
          />
        </Field>

        <Coverage kind={scope.kind} itemKey={item.key} categoryId={scope.categoryId} />
      </div>
    );
  };

  if (error !== null && data === null) return <ErrorBanner message={error} />;
  if (data === null || meta === null) return <Spinner label="Loading checks" />;

  return (
    <div className="page">
      <h1 className="page-title">Checks</h1>
      <p className="muted">
        Every check in the platform, in one table. A category states only what it CHANGES, so a
        row here is something somebody decided. Filter any column — Scope to see what one
        category does differently, Applies when to find the conditional ones, Key to line a check
        up with every override of it. Editing never rewrites a past review: a record keeps the
        list it was checked against.
      </p>

      {error ? <ErrorBanner message={error} /> : null}
      {notice ? (
        <div className="banner-ok" role="status">
          {notice}
        </div>
      ) : null}

      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(r) => r.key}
        rowClass={(r) =>
          r.draft ? "draft-row" : severityOf(r.item) === "ignore" ? "muted" : ""
        }
        // Pinned first whatever the sort — that is what `group` is for.
        group={(r) => (r.draft ? 0 : 1)}
        expand={expand}
        persistKey="checks"
        defaultSort={{ key: "check", dir: "asc" }}
        empty="No checks."
      />

      {problems.length > 0 ? (
        <div className="banner-warn">
          {problems.map((p) => (
            <div key={p}>{p}</div>
          ))}
        </div>
      ) : null}

      <div className="btn-row">
        <input
          className="text row-input"
          value={comment}
          maxLength={300}
          placeholder="What changed (kept in every version this publishes)"
          aria-label="Version comment"
          onChange={(e) => setComment(e.target.value)}
        />
        <button
          type="button"
          className="btn btn-accent"
          disabled={busy || dirtyScopes.length === 0 || problems.length > 0}
          onClick={() => void publish()}
        >
          {busy
            ? "Publishing…"
            : dirtyScopes.length === 0
              ? "Publish"
              : `Publish ${dirtyScopes.length} scope${dirtyScopes.length === 1 ? "" : "s"}`}
        </button>
        <button
          type="button"
          className="btn"
          disabled={busy || dirtyScopes.length === 0}
          onClick={() => setEdits({})}
        >
          Reset
        </button>
        {dirtyScopes.length > 0 ? (
          <span className="rail-hint">
            Changed: {dirtyScopes.map((k) => scopeByKey.get(k)?.label).join(", ")}. A checklist
            version belongs to one scope, so this publishes one per scope.
          </span>
        ) : null}
      </div>
    </div>
  );
}
