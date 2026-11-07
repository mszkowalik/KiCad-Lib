/** Stock → JLCPCB: three repair jobs on JLC data that is already staged or imported.
 *  Each one is archive-wide, so the page offers them to an admin only.
 *
 *  The two with a dry run go through `DryRunDialog`. The fee refresh has none, but it
 *  only stores evidence, so it asks first and says so.
 */
import { useState } from "react";
import {
  ApiError,
  backfillJlcFees,
  errorMessage,
  jlcAdjustmentsToDraws,
  refreshJlcFees,
  type JlcFeeBackfillResult,
  type JlcToDrawsResult,
} from "../../api";
import { useAuth } from "../../auth";
import { plain } from "../../format";
import { useDialog } from "../Dialog";
import Field, { CheckField } from "../Field";
import FoldSection from "../FoldSection";
import { DryRunDialog } from "../process/StageDialogs";
import { ErrorBanner } from "../Ui";

/** A refusal names its orders in `detail.problems`, beside a sentence that does not. */
function withProblems(err: unknown): unknown {
  if (!(err instanceof ApiError)) return err;
  const detail = err.detail as { problems?: { smt_order_code: string; why: string }[] } | undefined;
  if (!detail?.problems?.length) return err;
  return new Error(`${err.message}: ${detail.problems.map((p) => `${p.smt_order_code} (${p.why})`).join("; ")}`);
}

function statusWords(byStatus: Record<string, number>): string {
  return Object.entries(byStatus).map(([word, n]) => `${n} ${word.replace(/_/g, " ")}`).join(", ");
}

export default function JlcJobsPanel({ onDone }: { onDone?: () => void }) {
  const { isAdmin } = useAuth();
  const dialog = useDialog();
  const [force, setForce] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [splitting, setSplitting] = useState(false);
  const [externalId, setExternalId] = useState("");
  const [migrating, setMigrating] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  if (!isAdmin) return null;

  const refresh = async () => {
    if (!(await dialog.confirm(
      (force
        ? "Read JLC's fee breakdown again for every staged batch?"
        : "Read JLC's fee breakdown for each staged batch that has none?") +
        " It stores the breakdown as evidence. No money moves. There is no dry run.",
      { title: "Fetch fee breakdowns", confirmLabel: "Fetch" },
    ))) return;
    setRefreshing(true);
    setError("");
    setNotice("");
    try {
      const r = await refreshJlcFees(force);
      setNotice(`Fee breakdowns: ${r.fetched} fetched, ${r.skipped} skipped, ${r.failed} failed.`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <FoldSection title="JLC repair jobs" count={3} limit={0} foldKey="jlc-repair-jobs">
      <ErrorBanner message={error} />
      {notice ? <div className="banner-ok">{notice}</div> : null}

      <h3>Fetch fee breakdowns</h3>
      <p className="muted dim">
        Reads JLC&rsquo;s fee breakdown for each staged batch that has none. It stores evidence only. No money moves.
        The split job below reads this evidence. It needs a live JLC session.
      </p>
      <div className="btn-row">
        <button type="button" className="btn btn-sm" disabled={refreshing} onClick={() => void refresh()}>
          {refreshing ? "Fetching…" : "Fetch…"}
        </button>
        <CheckField checked={force} onChange={setForce}
          title="JLC changes the tolls of a batch that it settles again.">
          Read again for every batch
        </CheckField>
      </div>

      <h3>Split imported batches by fee</h3>
      <p className="muted dim">
        Adds JLC&rsquo;s fee items as child lines under the lines of a batch document that is imported. The parent line
        keeps its printed figure, and each child keeps its parent&rsquo;s destination, so no money changes owner.
      </p>
      <div className="btn-row">
        <button type="button" className="btn btn-sm" onClick={() => setSplitting(true)}>Split by fee…</button>
      </div>

      <h3>Turn old external adjustments into draws</h3>
      <p className="muted dim">
        Before decision 0034, a stock movement of a project this platform does not track was an adjustment. This job
        writes those rows as draws charged to nobody. The quantities do not move. It refuses every row if one order
        does not match its plan.
      </p>
      <div className="btn-row">
        <button type="button" className="btn btn-sm" onClick={() => setMigrating(true)}>Turn into draws…</button>
      </div>

      {splitting ? (
        <DryRunDialog<JlcFeeBackfillResult>
          title="Split imported batches by fee"
          intro={
            "Each document is one reversible batch on the write log. A line with hand-made children is skipped and " +
            "reported. An excluded line stays as it is. A second run adds nothing. Preview writes nothing."
          }
          fields={
            <Field label="One batch" hint="Optional. A staged JLC batch number. Empty means every batch.">
              <input className="text mono" value={externalId} placeholder="W2024…" spellCheck={false}
                onChange={(e) => setExternalId(e.target.value)} />
            </Field>
          }
          run={async (dry) => {
            const r = await backfillJlcFees(externalId.trim(), dry);
            if (!dry) {
              setNotice(`Fee split: ${r.summary.applied} document(s) split, ${r.summary.children_created} child line(s) added.`);
              onDone?.();
            }
            return r;
          }}
          describe={(r) => {
            const will = r.documents.filter((d) => d.status === "dry_run").map((d) => d.external_id);
            const refused = r.documents.filter((d) => d.status === "refused");
            return (
              <>
                {r.summary.documents_seen} document(s) checked: {statusWords(r.summary.by_status) || "none"}. This adds{" "}
                {r.summary.children_created} child line(s) worth {plain(r.summary.value_split_usd)} USD.
                {will.length ? ` It splits ${will.join(", ")}.` : ""}
                {refused.length ? ` Refused: ${refused.map((d) => `${d.external_id} (${d.error})`).join("; ")}.` : ""}
              </>
            );
          }}
          canApply={(r) => r.summary.children_created > 0}
          applyLabel={(r) => (r.summary.by_status.dry_run ? `Split ${r.summary.by_status.dry_run} document(s)` : "Apply")}
          onClose={() => setSplitting(false)}
        />
      ) : null}

      {migrating ? (
        <DryRunDialog<JlcToDrawsResult>
          title="Turn old external adjustments into draws"
          intro={
            "This reads each adjustment against its order plan. If all of them match, Apply deletes the adjustments and " +
            "writes the draws as one reversible batch on the write log. Preview writes nothing."
          }
          fields={null}
          run={async (dry) => {
            try {
              const r = await jlcAdjustmentsToDraws(dry);
              if (!dry) {
                setNotice(`Adjustments: ${r.adjustments_removed ?? 0} rewritten as draws.`);
                onDone?.();
              }
              return r;
            } catch (err) {
              throw withProblems(err);
            }
          }}
          describe={(r) => (r.status === "nothing_to_migrate"
            ? <>Nothing to rewrite. No old external adjustment is left.</>
            : (
              <>
                Rewrites {r.adjustments ?? 0} adjustment(s) of {r.orders?.length ?? 0} order(s), worth{" "}
                {plain((r.orders ?? []).reduce((sum, o) => sum + (o.value_usd ?? 0), 0))} USD:{" "}
                {(r.orders ?? []).map((o) => o.smt_order_code).join(", ")}.
              </>
            ))}
          canApply={(r) => r.status === "dry_run"}
          applyLabel={(r) => (r.status === "dry_run" ? `Rewrite ${r.adjustments ?? 0}` : "Apply")}
          onClose={() => setMigrating(false)}
        />
      ) : null}
    </FoldSection>
  );
}
