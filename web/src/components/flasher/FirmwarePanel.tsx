/** Firmware images: upload on the left, the pool on the right.
 *
 *  Content-addressed by sha256, so the same build uploaded twice is one row.
 *  The CHIP is read out of the image header rather than trusted from a
 *  dropdown (a mislabelled chip is how a build reaches the wrong part), and
 *  the flash offset shown per row is the recommended one for that chip+kind
 *  from the project's partition map — the composer pre-fills it.
 *
 *  A row opens to the procedure versions that use the image. The delete confirm
 *  names them too, from the same route, and still sends the DELETE: the server's
 *  refusal is the guard, and the confirm only says it first.
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  deleteFirmware,
  errorMessage,
  firmwareBinPath,
  getFirmwareUsage,
  isAbortError,
  listFirmware,
  patchFirmware,
  uploadFirmware,
  type FirmwareAssetRow,
  type FirmwareUsageRow,
  type FlasherMeta,
} from "../../api";
import { useDialog } from "../Dialog";
import DataTable, { type Column } from "../DataTable";
import Field, { FieldGrid } from "../Field";
import FilePick from "../FilePick";
import { ErrorBanner, Spinner } from "../Ui";
import { fmtBytes, shortSha } from "./common";
import { localWhen, plural } from "../../format";
import { useModal } from "../modal";

const FALLBACK_CHIPS = ["esp32", "esp32c6"];
const FALLBACK_KINDS = ["factory", "app", "filesystem", "safeboot"];

/** How many versions a confirm names. The row's expansion lists all of them. */
const CONFIRM_NAMES = 12;

const versionName = (u: FirmwareUsageRow) =>
  `${u.deployment} v${u.version_no}${u.status === "published" ? "" : ` (${u.status})`}`;

/** The procedure versions that use one image, under its row. */
function FirmwareUsage({ assetId }: { assetId: number }) {
  const [versions, setVersions] = useState<FirmwareUsageRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const ac = new AbortController();
    getFirmwareUsage(assetId, ac.signal)
      .then((u) => setVersions(u.versions))
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ac.abort();
  }, [assetId]);
  if (error) return <ErrorBanner message={error} />;
  if (!versions) return <Spinner label="Reading which versions use it…" />;
  if (!versions.length) return <p className="muted">No procedure version uses this image.</p>;
  return (
    <p className="muted">
      Used by{" "}
      {versions.map((u, i) => (
        <span key={u.version_id}>
          {i ? ", " : ""}
          <Link className="val-link" to={`/production/procedures?version=${u.version_id}`}>
            {u.deployment} v{u.version_no}
          </Link>
          {u.status === "published" ? "" : ` (${u.status})`}
        </span>
      ))}
    </p>
  );
}

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
  const [gitCommit, setGitCommit] = useState("");
  const [picked, setPicked] = useState<File | null>(null);
  const [editing, setEditing] = useState<FirmwareAssetRow | null>(null);
  const modal = useModal(() => setEditing(null), { active: !!editing });

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
        kind, chip, build_label: buildLabel, notes, git_commit: gitCommit,
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
      setPicked(null);
      setBuildLabel("");
      setNotes("");
      setGitCommit("");
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
        build_label: editing.build_label, notes: editing.notes, git_commit: editing.git_commit,
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
    // Read now: `used_by` is as old as the list. If the read fails, the count
    // still says what the server will answer.
    const versions = await getFirmwareUsage(a.id).then((u) => u.versions).catch(() => null);
    const used = versions?.length ?? a.used_by ?? 0;
    const names = (versions ?? []).slice(0, CONFIRM_NAMES).map(versionName).join(", ");
    const more = used > CONFIRM_NAMES && versions ? ` and ${used - CONFIRM_NAMES} more` : "";
    if (!(await dialog.confirm(
      used
        ? `${a.filename} is used by ${used} procedure version(s)${names ? `: ${names}${more}` : ""}. ` +
            "The platform refuses to delete it, because a programming run records what it flashed. Try anyway?"
        : `Delete ${a.filename}? No procedure version uses it.`,
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
      width: 24,
      className: "mono",
      get: (a) => a.filename,
      title: (a) =>
        `${a.filename}\nsha256 ${a.sha256}\n${a.build_label || "no build label"}` +
        `\n${a.git_commit ? `commit ${a.git_commit}` : "no git commit recorded"}` +
        (a.notes ? `\n${a.notes}` : "") +
        `\nuploaded ${localWhen(a.uploaded_at)}`,
      render: (a) => (
        <>
          {a.flashable === false ? (
            <span className="pill err" title="not a writable ESP image">
              ✗
            </span>
          ) : null}{" "}
          <a className="comp-link" href={firmwareBinPath(a.id)} onClick={(e) => e.stopPropagation()}>
            {a.filename}
          </a>
        </>
      ),
    },
    { key: "kind", label: "Kind", width: 11, get: (a) => a.kind },
    { key: "chip", label: "Chip", width: 12, className: "mono", get: (a) => a.chip || "—" },
    {
      key: "offset",
      label: "Offset",
      width: 10,
      className: "mono dim",
      get: (a) => a.default_address || "—",
    },
    {
      key: "size",
      label: "Size",
      width: 13,
      numeric: true,
      get: (a) => a.size_bytes,
      render: (a) => <>{fmtBytes(a.size_bytes)}</>,
    },
    {
      key: "used_by",
      label: "Used by",
      width: 14,
      get: (a) => (a.used_by ? `${plural(a.used_by, "version")}` : "unused"),
    },
    {
      key: "actions",
      label: "",
      width: 16,
      interactive: false,
      className: "ctr",
      get: () => "",
      render: (a) => (
        <>
          <button
            type="button"
            className="btn btn-sm"
            onClick={(e) => {
              e.stopPropagation();
              setEditing({ ...a });
            }}
          >
            Edit
          </button>{" "}
          <button
            type="button"
            className="btn btn-sm row-del"
            title={a.used_by ? "used by a version — will be refused" : "delete"}
            onClick={(e) => {
              e.stopPropagation();
              void remove(a);
            }}
          >
            ×
          </button>
        </>
      ),
    },
  ];

  return (
    <div className="fw-layout">
      {/* ---------------- upload ---------------- */}
      <div className="card pad">
        <h2 className="card-title">Add firmware</h2>
        <p className="muted dim">
          Content-addressed: the same bytes uploaded twice stay one row. The chip comes from the
          image header — the selector below is only a fallback for headerless images.
        </p>
        {error ? <ErrorBanner message={error} /> : null}
        {note ? <p className="banner-ok">{note}</p> : null}

        <FieldGrid>
          <Field group label="Image file">
            <FilePick accept=".bin" onPick={(files) => setPicked(files[0] ?? null)}>Choose a file…</FilePick>
          </Field>

          <Field label="Kind">
            <select className="text" value={kind} onChange={(e) => setKind(e.target.value)}>
              {kinds.map((k) => (
                <option key={k} value={k}>{k}</option>
              ))}
            </select>
          </Field>

          <Field label="Chip (fallback)">
            <select className="text" value={chip} onChange={(e) => setChip(e.target.value)}>
              {chips.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </Field>

          <Field label="Flash offset">
            <input
              className="text mono"
              value={offsetFor(chip, kind) || "set per procedure"}
              readOnly
              title="The recommended offset for this chip and kind, from the project's partition map. The composer pre-fills it; a version can still override."
            />
          </Field>

          <Field label="Build label" wide>
            <input
              className="text"
              placeholder="e.g. 15.5.0(tasmota)-3.3.8 2026-07-22"
              value={buildLabel}
              onChange={(e) => setBuildLabel(e.target.value)}
            />
          </Field>

          <Field label="Git commit" wide>
            <input
              className="text mono"
              placeholder="the pushed commit it was built from, e.g. ec3f070f9"
              value={gitCommit}
              onChange={(e) => setGitCommit(e.target.value)}
            />
          </Field>

          <Field label="Notes" wide>
            <input
              className="text"
              placeholder="where it came from, why it exists"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </Field>
        </FieldGrid>

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
              expand={(a) => <FirmwareUsage key={a.id} assetId={a.id} />}
              empty="Nothing uploaded yet."
            />
          </div>
        )}
        <p className="muted dim">
          Open a row to see which procedure versions use the image. Hover an image for its sha256,
          build label and notes. A red ✗ means the bytes are not a writable ESP image, so no version
          may pin it.
        </p>
      </div>

      {editing ? (
        <div className="modal-backdrop" {...modal.backdropProps}>
          <div className="card pad modal-card" {...modal.cardProps}>
            <h2 className="card-title mono">{editing.filename}</h2>
            <p className="muted dim">
              Metadata only — the bytes are the identity and never change. sha256{" "}
              <span className="mono">{shortSha(editing.sha256)}</span>
            </p>
            <FieldGrid>
              <Field label="Kind">
                <select
                  className="text"
                  value={editing.kind}
                  onChange={(e) => setEditing({ ...editing, kind: e.target.value })}
                >
                  {kinds.map((k) => (
                    <option key={k} value={k}>{k}</option>
                  ))}
                </select>
              </Field>
              <Field label="Chip">
                <select
                  className="text"
                  value={editing.chip}
                  onChange={(e) => setEditing({ ...editing, chip: e.target.value })}
                >
                  {chips.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </Field>
              <Field label="Flash offset">
                <input
                  className="text mono"
                  value={offsetFor(editing.chip, editing.kind) || "set per procedure"}
                  readOnly
                />
              </Field>
              <Field label="Build label" wide>
                <input
                  className="text"
                  value={editing.build_label}
                  onChange={(e) => setEditing({ ...editing, build_label: e.target.value })}
                />
              </Field>
              <Field label="Git commit" wide>
                <input
                  className="text mono"
                  value={editing.git_commit}
                  onChange={(e) => setEditing({ ...editing, git_commit: e.target.value })}
                />
              </Field>
              <Field label="Notes" wide>
                <input
                  className="text"
                  value={editing.notes}
                  onChange={(e) => setEditing({ ...editing, notes: e.target.value })}
                />
              </Field>
            </FieldGrid>
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
