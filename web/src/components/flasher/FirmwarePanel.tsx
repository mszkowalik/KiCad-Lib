/** Firmware assets: the uploaded .bin files, content-addressed by sha256.
 *  A release version picks these and gives each a flash offset. */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  errorMessage,
  isAbortError,
  listFirmware,
  uploadFirmware,
  type FirmwareAssetRow,
  type FlasherMeta,
} from "../../api";
import { ErrorBanner, Spinner } from "../Ui";
import { fmtBytes, fmtWhen, shortSha } from "./common";

export default function FirmwarePanel({ projectId, meta }: { projectId: number; meta: FlasherMeta | null }) {
  const [rows, setRows] = useState<FirmwareAssetRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [kind, setKind] = useState("factory");
  const [chip, setChip] = useState("");
  const [buildLabel, setBuildLabel] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

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
    return reload();
  }, [reload]);

  const upload = async () => {
    const file = fileRef.current?.files?.[0];
    if (!file) {
      setError("Pick a .bin file first.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await uploadFirmware(projectId, file, { kind, chip, build_label: buildLabel });
      if (res.existing) setError(`Identical content already stored as "${res.filename}" — reused.`);
      if (fileRef.current) fileRef.current.value = "";
      setBuildLabel("");
      reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card pad">
      <h2 className="card-title">Firmware binaries</h2>
      <p className="card-subtitle">
        Content-addressed: the same build uploaded twice is one row. A release version maps these
        to flash offsets.
      </p>
      {error ? <ErrorBanner message={error} /> : null}
      <div className="btn-row">
        <input ref={fileRef} type="file" accept=".bin" />
        <select className="row-input" value={kind} onChange={(e) => setKind(e.target.value)}>
          {(meta?.firmware_kinds ?? ["factory", "app", "filesystem", "safeboot"]).map((k) => (
            <option key={k} value={k}>{k}</option>
          ))}
        </select>
        <input
          className="row-input"
          placeholder="chip (esp32c6)"
          value={chip}
          onChange={(e) => setChip(e.target.value)}
        />
        <input
          className="row-input"
          placeholder="build label"
          value={buildLabel}
          onChange={(e) => setBuildLabel(e.target.value)}
        />
        <button type="button" className="btn btn-primary btn-sm" onClick={upload} disabled={busy}>
          {busy ? "Uploading…" : "Upload"}
        </button>
      </div>
      {rows === null ? (
        <Spinner label="Loading firmware…" />
      ) : rows.length === 0 ? (
        <p className="muted">No firmware uploaded yet.</p>
      ) : (
        <div className="table-wrap">
          <table className="data data-fixed firmware-table">
            <thead>
              <tr>
                <th>File</th>
                <th>Kind</th>
                <th>Chip</th>
                <th className="num">Size</th>
                <th>sha256</th>
                <th>Build</th>
                <th>Uploaded</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((a) => (
                <tr key={a.id}>
                  <td className="mono" title={a.filename}>{a.filename}</td>
                  <td>{a.kind}</td>
                  <td className="mono">{a.chip || "—"}</td>
                  <td className="num">{fmtBytes(a.size_bytes)}</td>
                  <td className="mono dim" title={a.sha256}>{shortSha(a.sha256)}</td>
                  <td title={a.build_label}>{a.build_label || "—"}</td>
                  <td className="muted">{fmtWhen(a.uploaded_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
