import { useEffect, useState } from "react";

import { errorMessage, isAbortError } from "../api";
import { ErrorBanner, Spinner } from "./Ui";

/** A PDF in the browser's own viewer, framed from a BLOB rather than its URL.
 *
 *  `<iframe src="/api/datasheets/30/file">` is the obvious way to do this and
 *  it is dead on this deployment: the shared nginx in front of the platform
 *  sends `X-Frame-Options: DENY` for every route it serves, and DENY forbids
 *  framing even by the same origin. Every PDF preview in the app rendered as
 *  the browser's broken-document icon — the review workbench's datasheet pane
 *  above all, where comparing the part against its documentation IS the task
 *  (reported 2026-08-25).
 *
 *  Fetching the bytes and framing a `blob:` URL fixes it without touching that
 *  shared config: a blob the page created carries no HTTP headers, so there is
 *  no `X-Frame-Options` to honour, and the browser's PDF viewer renders it as
 *  usual. Same-origin credentials still apply to the fetch, so the file stays
 *  behind the auth gate.
 *
 *  Do not "simplify" this back to a plain `src` — it works on a bare dev
 *  server, which is exactly why the breakage only ever showed up in
 *  production. */
export default function PdfFrame({
  src,
  title,
  className,
}: {
  src: string;
  title: string;
  className?: string;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let objectUrl: string | null = null;
    const ctrl = new AbortController();
    setUrl(null);
    setError(null);

    (async () => {
      try {
        const res = await fetch(src, { credentials: "include", signal: ctrl.signal });
        if (!res.ok) {
          setError(`Could not load the document (HTTP ${res.status})`);
          return;
        }
        const blob = await res.blob();
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      } catch (err) {
        if (!isAbortError(err)) setError(errorMessage(err));
      }
    })();

    return () => {
      ctrl.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [src]);

  if (error !== null) return <ErrorBanner message={error} />;
  if (url === null) return <Spinner label="Loading document…" />;
  return <iframe className={className} src={url} title={title} />;
}
