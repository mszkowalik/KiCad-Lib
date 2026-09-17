/** ONE button that opens the browser's file selector.
 *
 *  There were seven hand-rolled `<input type="file">` markups in the app
 *  before this (firmware, bundles, run attachments, invoices, the simulator,
 *  component attachments, production documents), each with its own way of
 *  hiding the input and resetting it. This is the shared one, for the same
 *  reason `Field` and `SiInput` exist: every input in the web UI is a shared
 *  component (web/CLAUDE.md).
 *
 *  The input is reset after every pick, so picking the SAME file twice fires
 *  twice — an upload that replaces a file is exactly that case.
 */
import { useRef, type ReactNode } from "react";

export default function FilePick({
  onPick,
  accept,
  multiple = false,
  directory = false,
  disabled = false,
  className = "btn btn-sm",
  title,
  children,
}: {
  onPick: (files: File[]) => void;
  /** e.g. ".lbrn2,.lbrn" — the browser filters the dialog, the server still decides */
  accept?: string;
  multiple?: boolean;
  /** pick a whole folder (Chromium's webkitdirectory) */
  directory?: boolean;
  disabled?: boolean;
  /** the button's classes — `btn btn-sm` by default, `btn btn-primary` for a primary action */
  className?: string;
  title?: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLInputElement>(null);
  return (
    <label className={`${className}${disabled ? " disabled" : ""}`} title={title} aria-disabled={disabled}>
      {children}
      <input
        ref={ref}
        type="file"
        className="hidden-input"
        accept={accept}
        multiple={multiple || directory}
        disabled={disabled}
        // @ts-expect-error — non-standard but supported in Chromium
        webkitdirectory={directory ? "" : undefined}
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          if (ref.current) ref.current.value = "";
          if (files.length) onPick(files);
        }}
      />
    </label>
  );
}
