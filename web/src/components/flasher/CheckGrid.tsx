/** The green/red grid: what a device (or one run) is proven to do.
 *
 *  A cell is green only when a run measured the functionality and it passed.
 *  Grey is not a soft failure — it means "never measured", which for the
 *  imported V2 history is the honest answer for anything the old reports did
 *  not record. Hover a cell for the evidence sentence.
 */
import { Link } from "react-router-dom";
import type { RunCheckRow } from "../../api";
import { fmtWhen } from "./common";

const CATEGORY_LABEL: Record<string, string> = {
  identity: "Identity",
  firmware: "Firmware",
  connectivity: "Connectivity",
  berryware: "Berryware",
  hardware: "Hardware",
  other: "Other",
};

const TONE: Record<string, string> = { pass: "ok", fail: "err", unknown: "unknown" };

export default function CheckGrid({
  checks,
  showRun = false,
}: {
  checks: RunCheckRow[];
  showRun?: boolean;
}) {
  if (!checks.length) {
    return (
      <p className="muted">
        Nothing measured. A procedure names what it proves with a step's <em>Proves</em> field, and
        imported runs yield checks only where the old report kept the evidence.
      </p>
    );
  }

  const groups: [string, RunCheckRow[]][] = [];
  checks.forEach((c) => {
    const last = groups[groups.length - 1];
    if (last && last[0] === c.category) last[1].push(c);
    else groups.push([c.category, [c]]);
  });

  const tally = checks.reduce<Record<string, number>>((acc, c) => {
    acc[c.status] = (acc[c.status] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <>
      <p className="card-subtitle">
        {tally.pass ?? 0} passed · {tally.fail ?? 0} failed
        {tally.unknown ? ` · ${tally.unknown} never measured` : ""}
      </p>
      {groups.map(([category, rows]) => (
        <div key={category} className="check-group">
          <span className="fw-label">{CATEGORY_LABEL[category] ?? category}</span>
          <div className="check-cells">
            {rows.map((c) => {
              const repeats = c.attempts
                ? Object.entries(c.attempts).map(([s, n]) => `${n}× ${s}`).join(", ")
                : "";
              const title = [c.detail, repeats && `attempts: ${repeats}`, c.at && fmtWhen(c.at)]
                .filter(Boolean)
                .join(" — ");
              const body = (
                <>
                  <span className="check-dot" aria-hidden="true" />
                  <span className="check-name">{c.label}</span>
                </>
              );
              return showRun && c.run_id ? (
                <Link key={c.name} className={`check-cell check-${TONE[c.status] ?? "unknown"}`}
                      to={`/production/flash-runs/${c.run_id}`} title={title}>
                  {body}
                </Link>
              ) : (
                <span key={c.name} className={`check-cell check-${TONE[c.status] ?? "unknown"}`}
                      title={title}>
                  {body}
                </span>
              );
            })}
          </div>
        </div>
      ))}
    </>
  );
}

/** The list-view version: three numbers, no names. */
export function CheckBar({ checks }: { checks: { pass: number; fail: number; unknown: number } }) {
  const total = checks.pass + checks.fail + checks.unknown;
  if (!total) return <span className="muted dim">—</span>;
  return (
    <span className="check-bar" title={`${checks.pass} passed, ${checks.fail} failed, ${checks.unknown} never measured`}>
      {checks.fail ? <span className="pill err">{checks.fail} failed</span> : null}
      <span className={`pill ${checks.fail ? "neutral" : "ok"}`}>{checks.pass}/{total}</span>
    </span>
  );
}
