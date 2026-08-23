import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createChecklist,
  deleteChecklist,
  errorMessage,
  getCategories,
  getChecklist,
  getChecklistMeta,
  getChecklistVersion,
  isAbortError,
  listChecklists,
  resolveChecklist,
  saveChecklist,
  type ChecklistDetail,
  type ChecklistMeta,
  type ChecklistSummary,
  type ResolvedChecklist,
  type ReviewKind,
} from "../api";
import { flattenCats } from "../components/editing";
import { useDialog } from "../components/Dialog";
import { ErrorBanner, Spinner } from "../components/Ui";

/**
 * The checklist editor — what every verification is measured against.
 *
 * A checklist is versioned like everything else here: saving publishes a new
 * version and the old ones stay readable. Editing one does NOT rewrite the past,
 * because each review record snapshots the resolved list it was checked against
 * (`ReviewRecord.checklist_items`).
 *
 * Two things this screen has to be honest about, or it quietly breaks reviews:
 *
 * 1. **`machine` is not a wish.** A machine item is answered by
 *    `services/validator.py` on publish, and only for the keys that module
 *    implements. Marking any other key `machine` creates an item nobody can ever
 *    answer, holding every subject at "partial" for ever. The flag is disabled
 *    for unknown keys here and refused by the API.
 * 2. **A category checklist is a MERGE, not a replacement.** What a part is
 *    measured against is the base list plus every category-scoped list on its
 *    category path, most specific winning a key collision. Editing one list in
 *    isolation tells you nothing, so the preview panel resolves the real thing.
 */
type Item = ChecklistDetail["items"][number];

const KIND_PREFIX: Record<string, string> = {
  component: "cmp",
  symbol: "sym",
  footprint: "fp",
};

const KIND_LABEL: Record<string, string> = {
  component: "Components",
  symbol: "Symbols",
  footprint: "Footprints",
};

function slugKey(kind: ReviewKind, text: string, taken: Set<string>): string {
  const slug =
    text
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .slice(0, 32) || "check";
  let key = `${KIND_PREFIX[kind] ?? "chk"}.${slug}`;
  for (let n = 2; taken.has(key); n += 1) key = `${KIND_PREFIX[kind] ?? "chk"}.${slug}_${n}`;
  return key;
}

export default function Checklists() {
  const [list, setList] = useState<ChecklistSummary[] | null>(null);
  const [meta, setMeta] = useState<ChecklistMeta | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<ChecklistDetail | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [description, setDescription] = useState("");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const dialog = useDialog();

  const loadList = useCallback(
    (signal?: AbortSignal) =>
      listChecklists(signal)
        .then((rows) => {
          setList(rows);
          setSelectedId((cur) => cur ?? rows[0]?.id ?? null);
        })
        .catch((err) => {
          if (!isAbortError(err)) setListError(errorMessage(err));
        }),
    [],
  );

  useEffect(() => {
    const ctrl = new AbortController();
    void loadList(ctrl.signal);
    getChecklistMeta(ctrl.signal)
      .then(setMeta)
      .catch(() => {
        /* the editor still works; the machine flag just stays locked */
      });
    return () => ctrl.abort();
  }, [loadList]);

  useEffect(() => {
    if (selectedId === null || creating) return;
    const ctrl = new AbortController();
    setDetail(null);
    setError(null);
    setNotice(null);
    getChecklist(selectedId, ctrl.signal)
      .then((d) => {
        setDetail(d);
        setItems(d.items.map((i) => ({ ...i })));
        setDescription(d.description);
        setComment("");
      })
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, [selectedId, creating]);

  const machineKeys = useMemo(
    () => new Set(detail ? (meta?.machine_keys[detail.subject_kind] ?? []) : []),
    [meta, detail],
  );

  const problems = useMemo(() => {
    const out: string[] = [];
    const seen = new Set<string>();
    for (const i of items) {
      if (!i.key.trim() || !i.text.trim()) out.push("every item needs a key and a text");
      if (seen.has(i.key)) out.push(`duplicate key ${i.key}`);
      seen.add(i.key);
      if (i.machine && !machineKeys.has(i.key))
        out.push(`${i.key}: the validator does not answer this key, so it cannot be automatic`);
    }
    return [...new Set(out)];
  }, [items, machineKeys]);

  const dirty =
    detail !== null &&
    (description !== detail.description ||
      JSON.stringify(items) !== JSON.stringify(detail.items));

  const patch = (idx: number, next: Partial<Item>) =>
    setItems((prev) => prev.map((it, n) => (n === idx ? { ...it, ...next } : it)));

  const move = (idx: number, by: number) =>
    setItems((prev) => {
      const to = idx + by;
      if (to < 0 || to >= prev.length) return prev;
      const next = [...prev];
      [next[idx], next[to]] = [next[to], next[idx]];
      return next;
    });

  const addItem = () =>
    setItems((prev) => [...prev, { key: "", text: "" }]);

  const save = async () => {
    if (detail === null || problems.length > 0) return;
    setBusy(true);
    setError(null);
    try {
      const next = await saveChecklist(detail.id, items, comment.trim() || undefined, description);
      setDetail(next);
      setItems(next.items.map((i) => ({ ...i })));
      setComment("");
      setNotice(`Published v${next.version_no} — ${next.items.length} item(s).`);
      void loadList();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const loadVersion = async (versionNo: number) => {
    if (detail === null) return;
    try {
      const v = await getChecklistVersion(detail.id, versionNo);
      setItems(v.items.map((i) => ({ ...i })));
      setComment(`Restored v${versionNo}`);
      setNotice(
        `Loaded v${versionNo} into the editor — nothing is saved until you publish it as a new version.`,
      );
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const remove = async () => {
    if (detail === null) return;
    const ok = await dialog.confirm(
      `Delete the checklist "${detail.name}"? Verifications already recorded keep the list they were checked against.`,
      { title: "Delete checklist", confirmLabel: "Delete", tone: "danger" },
    );
    if (!ok) return;
    setBusy(true);
    try {
      await deleteChecklist(detail.id);
      setSelectedId(null);
      setDetail(null);
      await loadList();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const grouped = useMemo(() => {
    const by: Record<string, ChecklistSummary[]> = {};
    for (const c of list ?? []) (by[c.subject_kind] ??= []).push(c);
    return by;
  }, [list]);

  return (
    <div className="skills-layout">
      <aside className="skills-list">
        {listError ? <ErrorBanner message={`Checklists failed to load: ${listError}`} /> : null}
        {list === null && listError === null ? (
          <div className="sidebar-loading">
            <Spinner label="Loading checklists" />
          </div>
        ) : null}
        {(["component", "symbol", "footprint"] as ReviewKind[]).map((kind) =>
          grouped[kind]?.length ? (
            <div key={kind}>
              <div className="skill-meta" style={{ padding: "8px 10px 2px" }}>
                {KIND_LABEL[kind]}
              </div>
              {grouped[kind].map((c) => (
                <button
                  key={c.id}
                  type="button"
                  className={"skill-item" + (c.id === selectedId && !creating ? " selected" : "")}
                  onClick={() => {
                    setCreating(false);
                    setSelectedId(c.id);
                  }}
                >
                  <span className="skill-name">{c.name}</span>
                  <span className="skill-meta">
                    {c.category_path ?? "base — every " + kind} · {c.item_count} items · v
                    {c.version_no ?? "?"}
                  </span>
                </button>
              ))}
            </div>
          ) : null,
        )}
        <div className="skills-list-footer">
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => {
              setCreating(true);
              setDetail(null);
            }}
          >
            New checklist
          </button>
        </div>
      </aside>

      <main className="skill-editor">
        {creating ? (
          <NewChecklist
            onCancel={() => setCreating(false)}
            onCreated={async (id) => {
              setCreating(false);
              await loadList();
              setSelectedId(id);
            }}
          />
        ) : detail === null ? (
          error ? (
            <ErrorBanner message={error} />
          ) : (
            <Spinner label="Loading checklist" />
          )
        ) : (
          <>
            <div className="skill-head">
              <h1 className="skill-title">{detail.name}</h1>
              <span className="pill info">{detail.subject_kind}</span>
              {detail.category_id === null ? (
                <span className="pill neutral" title="Applies to every subject of this kind">
                  base
                </span>
              ) : null}
              <span className="muted">v{detail.version_no ?? "?"}</span>
            </div>

            <p className="muted">
              Saving publishes a new version. Verifications already recorded keep the list they
              were checked against, so editing this never rewrites a past review.
            </p>

            {error ? <ErrorBanner message={error} /> : null}
            {notice ? (
              <div className="banner-ok" role="status">
                {notice}
              </div>
            ) : null}

            <div className="skill-desc">
              <input
                className="text"
                value={description}
                maxLength={300}
                placeholder="What this checklist is for"
                aria-label="Checklist description"
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>

            <table className="data data-fixed checklist-table">
              <thead>
                <tr>
                  <th>Key</th>
                  <th>What to check</th>
                  <th>Hint</th>
                  <th className="ctr">Auto</th>
                  <th className="ctr">Order</th>
                </tr>
              </thead>
              <tbody>
                {items.map((it, idx) => {
                  const canBeMachine = machineKeys.has(it.key);
                  return (
                    <tr key={idx}>
                      <td>
                        <input
                          className="text row-input mono"
                          value={it.key}
                          placeholder="cmp.something"
                          onChange={(e) => patch(idx, { key: e.target.value.trim() })}
                        />
                      </td>
                      <td>
                        <input
                          className="text row-input"
                          value={it.text}
                          placeholder="What a reviewer must confirm"
                          onChange={(e) => {
                            const text = e.target.value;
                            if (!it.key.trim() && detail)
                              patch(idx, {
                                text,
                                key: slugKey(
                                  detail.subject_kind,
                                  text,
                                  new Set(items.map((x) => x.key)),
                                ),
                              });
                            else patch(idx, { text });
                          }}
                        />
                      </td>
                      <td>
                        <input
                          className="text row-input"
                          value={it.hint ?? ""}
                          placeholder="Optional — where to look"
                          onChange={(e) => patch(idx, { hint: e.target.value || undefined })}
                        />
                      </td>
                      <td className="ctr">
                        <input
                          type="checkbox"
                          checked={!!it.machine}
                          disabled={!canBeMachine}
                          title={
                            canBeMachine
                              ? "Answered by the validator on every publish"
                              : "The validator does not implement this key, so nothing would ever answer it"
                          }
                          onChange={(e) => patch(idx, { machine: e.target.checked || undefined })}
                        />
                      </td>
                      <td className="ctr">
                        <button
                          type="button"
                          className="btn btn-sm"
                          disabled={idx === 0}
                          onClick={() => move(idx, -1)}
                        >
                          ↑
                        </button>{" "}
                        <button
                          type="button"
                          className="btn btn-sm"
                          disabled={idx === items.length - 1}
                          onClick={() => move(idx, 1)}
                        >
                          ↓
                        </button>{" "}
                        <button
                          type="button"
                          className="btn btn-sm btn-danger"
                          onClick={() => setItems((prev) => prev.filter((_, n) => n !== idx))}
                        >
                          ✕
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            <div className="btn-row">
              <button type="button" className="btn btn-sm" onClick={addItem}>
                Add item
              </button>
            </div>

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
                placeholder="What changed (kept in the version history)"
                aria-label="Version comment"
                onChange={(e) => setComment(e.target.value)}
              />
              <button
                type="button"
                className="btn btn-accent"
                disabled={busy || !dirty || problems.length > 0}
                onClick={() => void save()}
              >
                {busy ? "Publishing…" : "Publish version"}
              </button>
              <button
                type="button"
                className="btn"
                disabled={busy || !dirty}
                onClick={() => {
                  setItems(detail.items.map((i) => ({ ...i })));
                  setDescription(detail.description);
                  setComment("");
                }}
              >
                Reset
              </button>
              {detail.category_id !== null ? (
                <button
                  type="button"
                  className="btn btn-danger"
                  disabled={busy}
                  onClick={() => void remove()}
                >
                  Delete checklist
                </button>
              ) : null}
            </div>

            {detail.history.length > 1 ? (
              <section className="card pad">
                <h2 className="card-title">History</h2>
                <ul className="notes-list">
                  {detail.history.map((h) => (
                    <li key={h.version_no} className="note">
                      <div className="note-head">
                        <span className="mono">v{h.version_no}</span>{" "}
                        <span className="muted">
                          {new Date(h.created_at).toLocaleString()} · {h.created_by} ·{" "}
                          {h.item_count} items
                        </span>{" "}
                        {h.version_no !== detail.version_no ? (
                          <button
                            type="button"
                            className="btn btn-sm"
                            onClick={() => void loadVersion(h.version_no)}
                          >
                            Load into editor
                          </button>
                        ) : (
                          <span className="pill ok">current</span>
                        )}
                      </div>
                      {h.comment ? <p className="muted">{h.comment}</p> : null}
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            <ResolvedPreview kind={detail.subject_kind} />
          </>
        )}
      </main>
    </div>
  );
}

/** What a real subject is measured against: base + every category-scoped list
 *  on its path. Editing one list in isolation cannot show this. */
function ResolvedPreview({ kind }: { kind: ReviewKind }) {
  const [cats, setCats] = useState<{ id: number; label: string }[] | null>(null);
  const [categoryId, setCategoryId] = useState<number | "">("");
  const [resolved, setResolved] = useState<ResolvedChecklist | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (kind !== "component") return;
    const ctrl = new AbortController();
    getCategories(ctrl.signal)
      .then((tree) => setCats(flattenCats(tree)))
      .catch(() => setCats([]));
    return () => ctrl.abort();
  }, [kind]);

  useEffect(() => {
    const ctrl = new AbortController();
    setError(null);
    resolveChecklist(kind, categoryId === "" ? null : categoryId, ctrl.signal)
      .then(setResolved)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, [kind, categoryId]);

  return (
    <section className="card pad">
      <h2 className="card-title">What a {kind} is actually measured against</h2>
      {kind === "component" ? (
        <div className="btn-row">
          <select
            className="sel"
            value={categoryId === "" ? "" : String(categoryId)}
            onChange={(e) => setCategoryId(e.target.value === "" ? "" : Number(e.target.value))}
          >
            <option value="">no category (base only)</option>
            {(cats ?? []).map((c) => (
              <option key={c.id} value={String(c.id)}>
                {c.label}
              </option>
            ))}
          </select>
          <span className="rail-hint">
            Category-scoped lists merge on top of the base one; the most specific wins a shared
            key.
          </span>
        </div>
      ) : (
        <p className="muted">
          Symbols and footprints have no category, so the base list is the whole answer.
        </p>
      )}
      {error ? <ErrorBanner message={error} /> : null}
      {resolved === null ? (
        <Spinner label="Resolving" />
      ) : (
        <ul className="notes-list">
          {resolved.items.map((i) => (
            <li key={i.key} className="note">
              <div className="note-head">
                <span>{i.text}</span> <span className="mono muted">{i.key}</span>{" "}
                {i.machine ? <span className="badge">auto</span> : null}
                <span className="muted">· {i.from}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Create a list.
 *
 * Only ever a CATEGORY-SCOPED component list. `checklists.resolve` reads one
 * base list per kind and merges category-scoped ones on top, and symbols and
 * footprints carry no category — so anything else would be created, listed,
 * edited, and never reach a single verification. The API refuses those too;
 * this form just does not offer them. */
function NewChecklist({
  onCancel,
  onCreated,
}: {
  onCancel: () => void;
  onCreated: (id: number) => void | Promise<void>;
}) {
  const [name, setName] = useState("");
  const [categoryId, setCategoryId] = useState<number | "">("");
  const [description, setDescription] = useState("");
  const [cats, setCats] = useState<{ id: number; label: string }[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    getCategories(ctrl.signal)
      .then((tree) => setCats(flattenCats(tree)))
      .catch(() => setCats([]));
    return () => ctrl.abort();
  }, []);

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      const made = await createChecklist({
        name: name.trim(),
        subject_kind: "component",
        category_id: categoryId === "" ? null : categoryId,
        description: description.trim(),
        items: [],
      });
      await onCreated(made.id);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="skill-head">
        <h1 className="skill-title">New checklist</h1>
      </div>
      <p className="muted">
        A new list is always a COMPONENT list scoped to a category, and it MERGES on top of the
        base one rather than replacing it — use it for what one family needs beyond the standard
        checks. Symbols and footprints have no category and therefore one list each: add those
        items to the base symbol or footprint checklist.
      </p>
      {error ? <ErrorBanner message={error} /> : null}
      <div className="skill-desc">
        <input
          className="text"
          value={name}
          maxLength={120}
          placeholder="Name, e.g. Electrolytic capacitor extras"
          aria-label="Checklist name"
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      <div className="btn-row">
        <select
          className="sel"
          value={categoryId === "" ? "" : String(categoryId)}
          onChange={(e) => setCategoryId(e.target.value === "" ? "" : Number(e.target.value))}
        >
          <option value="">— choose the category it applies to —</option>
          {(cats ?? []).map((c) => (
            <option key={c.id} value={String(c.id)}>
              {c.label}
            </option>
          ))}
        </select>
      </div>
      <div className="skill-desc">
        <input
          className="text"
          value={description}
          maxLength={300}
          placeholder="What this checklist is for"
          aria-label="Checklist description"
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      <div className="btn-row">
        <button
          type="button"
          className="btn btn-accent"
          disabled={busy || !name.trim() || categoryId === ""}
          onClick={() => void create()}
        >
          {busy ? "Creating…" : "Create"}
        </button>
        <button type="button" className="btn" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
        <span className="rail-hint">Items are added in the editor once it exists.</span>
      </div>
    </>
  );
}
