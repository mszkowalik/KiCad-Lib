/** The files kept with one record: a supplier document's originals, a sales
 *  invoice's printed document, a tax entry's notice from the accountant
 *  (decision 0077). A file opens in the viewer (`viewkind.fileHref`);
 *  "Attach" adds one, and nothing here replaces or removes a file, so the
 *  first scan survives a second one.
 *
 *  The caller passes how to list, upload and address its files, so one
 *  component serves every owner. It renders inline pieces (a fragment): the
 *  caller's row decides the layout.
 */
import { useCallback, useEffect, useState, type ChangeEvent } from "react";
import { errorMessage, isAbortError } from "../api";
import { fileHref } from "../viewkind";
import { useDialog } from "./Dialog";

/** What a file row needs here; every owner's list answers at least this. */
export interface FileItem { id: number; filename: string; size_bytes: number; uploaded_by?: string }

export default function RecordFiles({ list, upload, pathOf, label = "Files", onChange }: {
  list: (signal?: AbortSignal) => Promise<FileItem[]>;
  upload: (file: File) => Promise<unknown>;
  pathOf: (fileId: number) => string;
  label?: string;
  onChange?: () => void;
}) {
  const dialog = useDialog();
  const [files, setFiles] = useState<FileItem[] | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback((signal?: AbortSignal) => {
    list(signal).then(setFiles).catch((err) => {
      if (!isAbortError(err)) setFiles([]);
    });
  }, [list]);

  useEffect(() => {
    const ac = new AbortController();
    load(ac.signal);
    return () => ac.abort();
  }, [load]);

  const pick = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setBusy(true);
    try {
      await upload(file);
      load();
      onChange?.();
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "Upload failed" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <span className="muted">{label}:</span>
      {files === null ? (
        <span className="dim">…</span>
      ) : files.length === 0 ? (
        <span className="dim">none filed</span>
      ) : (
        files.map((f) => (
          <a key={f.id} className="comp-link" href={fileHref(pathOf(f.id), f.filename)} target="_blank" rel="noreferrer"
             title={`${f.filename} · ${Math.round(f.size_bytes / 1024)} kB${f.uploaded_by ? ` · ${f.uploaded_by}` : ""}`}>
            {f.filename}
          </a>
        ))
      )}
      <label className="btn btn-sm">
        {busy ? "Uploading…" : "Attach"}
        <input type="file" hidden onChange={pick} disabled={busy} />
      </label>
    </>
  );
}
