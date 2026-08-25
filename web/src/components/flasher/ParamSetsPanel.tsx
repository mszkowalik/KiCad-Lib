/** Param sets: shared placeholder values (WiFi, MQTT host, creds salt,
 *  default SIM PIN), Fernet-encrypted at rest. Values are fetched decrypted
 *  only when the editor opens. */
import { useCallback, useEffect, useState } from "react";
import {
  deleteParamSet,
  errorMessage,
  getParamSetValues,
  isAbortError,
  listParamSets,
  putParamSet,
  type ParamSetRow,
} from "../../api";
import { useDialog } from "../Dialog";
import { ErrorBanner, Spinner } from "../Ui";
import { fmtWhen } from "./common";
import DataTable, { type Column } from "../DataTable";

interface Editing {
  name: string;
  rows: { key: string; value: string }[];
}

export default function ParamSetsPanel({ projectId }: { projectId: number }) {
  const dialog = useDialog();
  const [sets, setSets] = useState<ParamSetRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(() => {
    const ac = new AbortController();
    listParamSets(projectId, ac.signal)
      .then(setSets)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [projectId]);

  useEffect(() => {
    setSets(null);
    return reload();
  }, [reload]);

  const openEditor = async (ps: ParamSetRow | null) => {
    if (!ps) {
      const name = await dialog.prompt('Param set name ("production", "bench"):', {
        title: "New param set",
      });
      if (!name) return;
      setEditing({
        name,
        rows: [
          { key: "SSId1", value: "" },
          { key: "Password1", value: "" },
          { key: "MqttHost", value: "" },
          { key: "MqttPort", value: "8883" },
          { key: "creds_salt", value: "" },
          { key: "sim_pin", value: "" },
        ],
      });
      return;
    }
    try {
      const detail = await getParamSetValues(ps.id);
      setEditing({
        name: detail.name,
        rows: Object.entries(detail.values).map(([key, value]) => ({ key, value: String(value) })),
      });
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const save = async () => {
    if (!editing) return;
    const values: Record<string, string> = {};
    for (const r of editing.rows) {
      if (r.key.trim()) values[r.key.trim()] = r.value;
    }
    setBusy(true);
    setError(null);
    try {
      await putParamSet(projectId, editing.name, values);
      setEditing(null);
      reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (ps: ParamSetRow) => {
    if (!(await dialog.confirm(`Delete param set "${ps.name}"?`, {
      title: "Delete param set", tone: "danger", confirmLabel: "Delete",
    }))) return;
    try {
      await deleteParamSet(ps.id);
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const cols: Column<ParamSetRow>[] = [
    { key: "name", label: "Name", width: 26, className: "mono", get: (ps) => ps.name },
    {
      key: "keys",
      label: "Keys",
      width: 44,
      className: "dim",
      get: (ps) => ps.keys.join(", ") || "—",
    },
    {
      key: "updated",
      label: "Updated",
      width: 18,
      className: "muted",
      get: (ps) => ps.updated_at ?? "",
      render: (ps) => <>{fmtWhen(ps.updated_at)}</>,
    },
    {
      key: "actions",
      label: "",
      width: 12,
      interactive: false,
      className: "ctr",
      get: () => "",
      render: (ps) => (
        <span className="btn-row">
          <button type="button" className="btn btn-sm" onClick={() => openEditor(ps)}>
            Edit
          </button>
          <button type="button" className="btn btn-sm row-del" onClick={() => remove(ps)}>
            ×
          </button>
        </span>
      ),
    },
  ];

  return (
    <div className="card pad">
      <div className="toolbar">
        <h2 className="card-title">Param sets</h2>
        <button type="button" className="btn btn-sm" onClick={() => openEditor(null)}>
          New param set
        </button>
      </div>
      <p className="card-subtitle">
        Shared values a script interpolates as {"{placeholders}"} — WiFi credentials, MQTT host,
        creds salt, default SIM PIN. Encrypted at rest; never part of a script version, snapshotted
        (masked) on every run.
      </p>
      {error ? <ErrorBanner message={error} /> : null}
      {sets === null ? (
        <Spinner label="Loading param sets…" />
      ) : sets.length === 0 ? (
        <p className="muted">No param sets yet.</p>
      ) : (
        <div className="table-wrap">
          <DataTable
            columns={cols}
            rows={sets}
            rowKey={(ps) => ps.id}
            persistKey="flasher-param-sets"
            empty="No param sets yet."
          />
        </div>
      )}

      {editing ? (
        <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && setEditing(null)}>
          <div className="card pad modal-card" onMouseDown={(e) => e.stopPropagation()}>
            <h2 className="card-title">Param set “{editing.name}”</h2>
            {editing.rows.map((r, i) => (
              <div key={i} className="btn-row">
                <input
                  className="row-input mono"
                  placeholder="key"
                  value={r.key}
                  onChange={(e) =>
                    setEditing({
                      ...editing,
                      rows: editing.rows.map((x, j) => (j === i ? { ...x, key: e.target.value } : x)),
                    })
                  }
                />
                <input
                  className="row-input mono"
                  placeholder="value"
                  value={r.value}
                  onChange={(e) =>
                    setEditing({
                      ...editing,
                      rows: editing.rows.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)),
                    })
                  }
                />
                <button
                  type="button"
                  className="btn btn-sm row-del"
                  onClick={() =>
                    setEditing({ ...editing, rows: editing.rows.filter((_, j) => j !== i) })
                  }
                >
                  ×
                </button>
              </div>
            ))}
            <div className="btn-row modal-actions">
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => setEditing({ ...editing, rows: [...editing.rows, { key: "", value: "" }] })}
              >
                Add row
              </button>
              <button type="button" className="btn" onClick={() => setEditing(null)} disabled={busy}>
                Cancel
              </button>
              <button type="button" className="btn btn-primary" onClick={save} disabled={busy}>
                {busy ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
