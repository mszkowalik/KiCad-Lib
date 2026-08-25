/** Firmware images: upload on the left, the pool on the right.
 *
 *  Content-addressed by sha256, so the same build uploaded twice is one row.
 *  The CHIP is read out of the image header rather than trusted from a
 *  dropdown (a mislabelled chip is how a build reaches the wrong part), and
 *  the flash offset shown per row is the recommended one for that chip+kind
 *  from the project's partition map — the composer pre-fills it.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  deleteFirmware,
  errorMessage,
  firmwareBinPath,
  isAbortError,
  listFirmware,
  patchFirmware,
  uploadFirmware,
  type FirmwareAssetRow,
  type FlasherMeta,
} from "../../api";
import { useDialog } from "../Dialog";
import DataTable, { type Column } from "../DataTable";
import { ErrorBanner, Spinner } from "../Ui";
import { fmtBytes, fmtWhen, shortSha } from "./common";

const FALLBACK_CHIPS = ["esp32", "esp32c6"];
const FALLBACK_KINDS = ["factory", "app", "filesystem", "safeboot"];

export default function FirmwarePanel({
  projectId, meta,
}: {
  projectId: number;
  meta: FlasherMeta | null;
}) {
  const dialog = useDialog();
  const [rows, setRows] = useState<FirmwareAssetRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [kind, setKind] = useState("factory");
  const [chip, setChip] = useState("esp32c6");
  const [buildLabel, setBuildLabel] = useState("");
  const [notes, setNotes] = useState("");
  const [picked, setPicked] = useState<File | null>(null);
  const [editing, setEditing] = useState<FirmwareAssetRow | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const chips = meta?.chips ?? FALLBACK_CHIPS;
  const kinds = meta?.firmware_kinds ?? FALLBACK_KINDS;
  const offsetFor = (c: string, k: string) => meta?.default_offsets?.[c]?.[k] ?? "";

  const reload = useCallback(() => {
    const ac = new AbortController();
    listFirmware(projectId, ac.signal)
      .then(setRows)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [projectId]);

  useEffect(() => {
    setRows(null);
    setNote(null);
    return reload();
  }, [reload]);

  const upload = async () => {
    if (!picked) {
      setError("Pick a .bin file first.");
      return;
    }
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const res = await uploadFirmware(projectId, picked, {
        kind, chip, build_label: buildLabel, notes,
      });
      const detected = res.chip_detected
        ? `chip ${res.chip_detected} read from the image header`
        : "no ESP header found — the chip is as you selected";
      setNote(
        res.existing
          ? `Identical bytes already stored as "${res.filename}" — reused, nothing added. (${detected})`
          : `Uploaded ${res.filename} · ${detected}` +
            (res.flashable === false ? " · WARNING: not a writable ESP image" : ""),
      );
      if (fileRef.current) fileRef.current.value = "";
      setPicked(null);
      setBuildLabel("");
      setNotes("");
      reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const saveEdit = async () => {
    if (!editing) return;
    setBusy(true);
    try {
      await patchFirmware(editing.id, {
        chip: editing.chip, kind: editing.kind,
        build_label: editing.build_label, notes: editing.notes,
      });
      setEditing(null);
      reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (a: FirmwareAssetRow) => {
    const used = a.used_by ?? 0;
    if (!(await dialog.confirm(
      used
        ? `${a.filename} is pinned by ${used} deployment version(s) — the platform will refuse. Try anyway?`
        : `Delete ${a.filename}? The stored bytes go with it.`,
      { title: "Delete firmware", tone: "danger", confirmLabel: "Delete" },
    ))) return;
    try {
      await deleteFirmware(a.id);
      setNote(`Deleted ${a.filename}.`);
      reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const cols: Column<FirmwareAssetRow>[] = [
    {
      key: "filename",
      label: "Image",
      width: 30,
      className: "mono",
      get: (a) => a.filename,
      title: (a) =>
        `${a.filename}\nsha256 ${a.sha256}\n${a.build_label || "no build label"}` +
        (a.notes ? `\n${a.notes}` : "") +
        `\nuploaded ${fmtWhen(a.uploaded_at)}`,
      render: (a) => (
        <>
          {a.flashable === false ? (
            <span className="pill err" title="not a writable ESP image">
              ✗
            </span>
          ) : null}{" "}
          <a className="comp-link" href={firmwareBinPath(a.id)}>
            {a.filename}
          </a>
        </>
      ),
    },
    { key: "kind", label: "Kind", width: 12, get: (a) => a.kind },
    { key: "chip", label: "Chip", width: 10, className: "mono", get: (a) => a.chip || "—" },
    {
      key: "offset",
      label: "Offset",
      width: 11,
      className: "mono dim",
      get: (a) => a.default_address || "—",
    },
    {
      key: "size",
      label: "Size",
      width: 9,
      numeric: true,
      get: (a) => a.size_bytes,
      render: (a) => <>{fmtBytes(a.size_bytes)}</>,
    },
    {
      key: "used_by",
      label: "Used by",
      width: 14,
      get: (a) => (a.used_by ? `${a.used_by} version${a.used_by === 1 ? "" : "s"}` : "unused"),
    },
    {
      key: "actions",
      label: "",
      width: 14,
      interactive: false,
      className: "ctr",
      get: () => "",
      render: (a) => (
        <span className="btn-row">
          <button type="button" className="btn btn-sm" onClick={() => setEditing({ ...a })}>
            Edit
          </button>
          <button
            type="button"
            className="btn btn-sm row-del"
            title={a.used_by ? "pinned by a version — will be refused" : "delete"}
            onClick={() => remove(a)}
          >
            ×
          </button>
        </span>
      ),
    },
  ];

  return (
    <div className="fw-layout">
      {/* ---------------- upload ---------------- */}
      <div className="card pad">
        <h2 className="card-title">Add firmware</h2>
        <p className="card-subtitle">
          Content-addressed: the same bytes uploaded twice stay one row. The chip comes from the
          image header — the selector below is only a fallback for headerless images.
        </p>
        {error ? <ErrorBanner message={error} /> : null}
        {note ? <p className="banner-ok">{note}</p> : null}

        <div className="fw-form">
          <label className="fw-field">
            <span className="fw-label">Image file</span>
            <input
              ref={fileRef}
              type="file"
              accept=".bin"
              onChange={(e) => setPicked(e.target.files?.[0] ?? null)}
            />
          </label>

          <label className="fw-field">
            <span className="fw-label">Kind</span>
            <select className="row-input" value={kind} onChange={(e) => setKind(e.target.value)}>
              {kinds.map((k) => (
                <option key={k} value={k}>{k}</option>
              ))}
            </select>
          </label>

          <label className="fw-field">
            <span className="fw-label">Chip (fallback)</span>
            <select className="row-input" value={chip} onChange={(e) => setChip(e.target.value)}>
              {chips.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </label>

          <label className="fw-field">
            <span className="fw-label">Flash offset</span>
            <input
              className="row-input mono"
              value={offsetFor(chip, kind) || "set per deployment"}
              readOnly
              title="The recommended offset for this chip and kind, from the project's partition map. The composer pre-fills it; a version can still override."
            />
          </label>

          <label className="fw-field fw-wide">
            <span className="fw-label">Build label</span>
            <input
              className="row-input"
              placeholder="e.g. 15.5.0(tasmota)-3.3.8 2026-07-22"
              value={buildLabel}
              onChange={(e) => setBuildLabel(e.target.value)}
            />
          </label>

          <label className="fw-field fw-wide">
            <span className="fw-label">Notes</span>
            <input
              className="row-input"
              placeholder="where it came from, why it exists"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </label>
        </div>

        <div className="btn-row">
          <button type="button" className="btn btn-primary" onClick={upload} disabled={busy || !picked}>
            {busy ? "Uploading…" : "Upload"}
          </button>
          {picked ? (
            <span className="muted">
              {picked.name} · {fmtBytes(picked.size)}
            </span>
          ) : null}
        </div>
      </div>

      {/* ---------------- the pool ---------------- */}
      <div className="card pad">
        <div className="toolbar">
          <h2 className="card-title">Firmware pool</h2>
          <span className="muted">{rows ? `${rows.length} images` : ""}</span>
        </div>
        {rows === null ? (
          <Spinner label="Loading firmware…" />
        ) : rows.length === 0 ? (
          <p className="muted">Nothing uploaded yet.</p>
        ) : (
          <div className="table-wrap">
            <DataTable
              columns={cols}
              rows={rows}
              rowKey={(a) => a.id}
              persistKey="flasher-firmware"
              rowClass={(a) => (a.flashable === false ? "dim" : "")}
              empty="Nothing uploaded yet."
            />
          </div>
        )}
        <p className="muted dim">
          Hover an image for its sha256, build label and notes. A red ✗ means the bytes are not a
          writable ESP image, so no version may pin it.
        </p>
      </div>

      {editing ? (
        <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && setEditing(null)}>
          <div className="card pad modal-card" onMouseDown={(e) => e.stopPropagation()}>
            <h2 className="card-title mono">{editing.filename}</h2>
            <p className="card-subtitle">
              Metadata only — the bytes are the identity and never change. sha256{" "}
              <span className="mono">{shortSha(editing.sha256)}</span>
            </p>
            <div className="fw-form">
              <label className="fw-field">
                <span className="fw-label">Kind</span>
                <select
                  className="row-input"
                  value={editing.kind}
                  onChange={(e) => setEditing({ ...editing, kind: e.target.value })}
                >
                  {kinds.map((k) => (
                    <option key={k} value={k}>{k}</option>
                  ))}
                </select>
              </label>
              <label className="fw-field">
                <span className="fw-label">Chip</span>
                <select
                  className="row-input"
                  value={editing.chip}
                  onChange={(e) => setEditing({ ...editing, chip: e.target.value })}
                >
                  {chips.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </label>
              <label className="fw-field">
                <span className="fw-label">Flash offset</span>
                <input
                  className="row-input mono"
                  value={offsetFor(editing.chip, editing.kind) || "set per deployment"}
                  readOnly
                />
              </label>
              <label className="fw-field fw-wide">
                <span className="fw-label">Build label</span>
                <input
                  className="row-input"
                  value={editing.build_label}
                  onChange={(e) => setEditing({ ...editing, build_label: e.target.value })}
                />
              </label>
              <label className="fw-field fw-wide">
                <span className="fw-label">Notes</span>
                <input
                  className="row-input"
                  value={editing.notes}
                  onChange={(e) => setEditing({ ...editing, notes: e.target.value })}
                />
              </label>
            </div>
            <div className="btn-row modal-actions">
              <button type="button" className="btn" onClick={() => setEditing(null)} disabled={busy}>
                Cancel
              </button>
              <button type="button" className="btn btn-primary" onClick={saveEdit} disabled={busy}>
                Save
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
