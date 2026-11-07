import type { ReactNode } from "react";
import { ErrorBanner, Spinner } from "./Ui";

/** The two wrappers of a page: `.main-solo` scrolls and `.page` holds the column.
 *  `className` adds a modifier to `.page`. */
export default function PageShell({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className="main-solo">
      <div className={className ? `page ${className}` : "page"}>{children}</div>
    </div>
  );
}

/** The early return of a page with nothing to show yet: the banner when `error` holds
 *  a message, and the spinner when it does not. */
export function PageLoading({ error, label }: { error?: string | null; label: string }) {
  return <PageShell>{error ? <ErrorBanner message={error} /> : <Spinner label={label} />}</PageShell>;
}
