/** Param sets: shared placeholder values (WiFi, MQTT host, creds salt,
 *  default SIM PIN), Fernet-encrypted at rest. Values are fetched decrypted
 *  only when the editor opens. */
import { useCallback, useEffect, useState } from "react";
import {
  deleteParamSet,
  errorMessage,
  isAbortError,
  listParamSets,
  type ParamSetRow,
} from "../../api";
import { useDialog } from "../Dialog";
import { ErrorBanner, Spinner } from "../Ui";
import { fmtWhen } from "./common";
import DataTable, { type Column } from "../DataTable";
import ParamSetEditor from "./ParamSetEditor";

/** Which set the editor is open on: an id to edit, or a name to create. */
type Editing = { id: number } | { name: string };

export default function ParamSetsPanel({ projectId }: { projectId: number }) {
  const dialog = useDialog();
  const [sets, setSets] = useState<ParamSetRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Editing | null>(null);

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
    if (ps) {
      setEditing({ id: ps.id });
      return;
    }
    const name = await dialog.prompt('Param set name ("production", "bench"):', {
      title: "New param set",
    });
    if (name) setEditing({ name });
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
        <ParamSetEditor
          projectId={projectId}
          paramSetId={"id" in editing ? editing.id : null}
          newName={"name" in editing ? editing.name : undefined}
          onClose={(saved) => {
            setEditing(null);
            if (saved) reload();
          }}
        />
      ) : null}
    </div>
  );
}
