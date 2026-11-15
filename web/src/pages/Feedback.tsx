import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  errorMessage,
  getFeedback,
  reportFeedback,
  triageFeedback,
  type FeedbackReport,
} from "../api";
import { useAuth } from "../auth";
import AutoTextarea from "../components/AutoTextarea";
import DataTable, { type Column } from "../components/DataTable";
import Field, { FieldRow } from "../components/Field";
import PageShell from "../components/PageShell";
import { ErrorBanner, Spinner, StatusPill } from "../components/Ui";
import { useLoad } from "../components/useLoad";
import { localDate } from "../format";

/** User menu → Feedback: report a bug or ask for a feature, and read what
 *  everyone else filed. An agent files the same reports with `report_feedback`. */
export default function Feedback() {
  const [params] = useSearchParams();
  const { data: reports, error, setError, reload } = useLoad(getFeedback, []);
  const [kind, setKind] = useState<"bug" | "feature">("bug");
  const [title, setTitle] = useState("");
  const [page, setPage] = useState(params.get("from") ?? "");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState("");

  async function send() {
    setBusy(true);
    setError("");
    setSent("");
    try {
      const r = await reportFeedback({ kind, title, body, page });
      setTitle("");
      setBody("");
      setSent(`Report #${r.id} filed.`);
      reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const cols: Column<FeedbackReport>[] = [
    { key: "id", label: "#", width: 6, numeric: true, get: (r) => r.id },
    { key: "kind", label: "Kind", width: 10, get: (r) => r.kind },
    { key: "title", label: "Title", width: 44, get: (r) => r.title },
    {
      key: "status",
      label: "Status",
      width: 12,
      get: (r) => r.status,
      render: (r) => <StatusPill status={r.status} />,
    },
    {
      key: "by",
      label: "Filed by",
      width: 16,
      get: (r) => (r.client === "mcp" ? `${r.created_by} 🤖` : r.created_by),
    },
    { key: "date", label: "Filed", width: 12, get: (r) => (r.created_at ? localDate(r.created_at) : "") },
  ];

  return (
    <PageShell>
      <div className="card pad">
        <h2 className="card-title">Report a bug or ask for a feature</h2>
        <p className="muted dim">
          Everyone who signs in sees these reports. Your agent can file one too, with the
          report_feedback tool.
        </p>
        <ErrorBanner message={error} />
        {sent ? <div className="banner-ok">{sent}</div> : null}
        <FieldRow>
          <Field label="Kind">
            <select
              className="text"
              value={kind}
              onChange={(e) => setKind(e.target.value as "bug" | "feature")}
            >
              <option value="bug">Bug</option>
              <option value="feature">Feature request</option>
            </select>
          </Field>
          <Field label="Title">
            <input className="text" value={title} onChange={(e) => setTitle(e.target.value)} />
          </Field>
          <Field label="Where (page or tool)">
            <input className="text" value={page} onChange={(e) => setPage(e.target.value)} />
          </Field>
        </FieldRow>
        <Field label={kind === "bug" ? "What you did, what happened, what you expected" : "What you need, and why"}>
          <AutoTextarea className="text" rows={4} value={body} onChange={(e) => setBody(e.target.value)} />
        </Field>
        <div className="btn-row">
          <button
            className="btn btn-primary"
            disabled={busy || title.trim().length < 3}
            onClick={() => void send()}
          >
            File it
          </button>
        </div>
      </div>

      <div className="card pad">
        <h2 className="card-title">Reports</h2>
        {reports === null ? (
          <Spinner label="Loading reports…" />
        ) : (
          <div className="table-wrap">
            <DataTable
              columns={cols}
              rows={reports}
              rowKey={(r) => r.id}
              persistKey="feedback"
              expand={(r) => <ReportDetail report={r} onChanged={reload} />}
              empty="No reports yet."
            />
          </div>
        )}
      </div>
    </PageShell>
  );
}

function ReportDetail({ report, onChanged }: { report: FeedbackReport; onChanged: () => void }) {
  const { isAdmin } = useAuth();
  const [status, setStatus] = useState(report.status);
  const [response, setResponse] = useState(report.response);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    setError("");
    try {
      await triageFeedback(report.id, { status, response });
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="user-detail">
      <ErrorBanner message={error} />
      {report.page ? <p className="muted">Where: {report.page}</p> : null}
      <p className="cell-wrap">{report.body || <span className="muted dim">No description.</span>}</p>
      {!isAdmin && report.response ? <p className="cell-wrap">Answer: {report.response}</p> : null}
      {isAdmin ? (
        <>
          <FieldRow>
            <Field label="Status">
              <select
                className="text"
                value={status}
                onChange={(e) => setStatus(e.target.value as FeedbackReport["status"])}
              >
                <option value="open">open</option>
                <option value="planned">planned</option>
                <option value="done">done</option>
                <option value="declined">declined</option>
              </select>
            </Field>
          </FieldRow>
          <Field label="Answer">
            <AutoTextarea className="text" value={response} onChange={(e) => setResponse(e.target.value)} />
          </Field>
          <div className="btn-row">
            <button
              className="btn btn-sm"
              disabled={busy || (status === report.status && response === report.response)}
              onClick={() => void save()}
            >
              Save
            </button>
          </div>
        </>
      ) : null}
    </div>
  );
}
