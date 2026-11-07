import { useState } from "react";
import {
  errorMessage,
  getFxRates,
  refreshFxRates,
  setFxRate,
  type FxRate,
} from "../api";
import { useAuth } from "../auth";
import DataTable, { type Column } from "./DataTable";
import { useDialog } from "./Dialog";
import { ErrorBanner, Spinner } from "./Ui";
import { localDate } from "../format";
import { useLoad } from "./useLoad";

/* Was a hand-rolled `<table className="data">` — the same header font as every
   other table, but no sort control and no filter row, so it read as a different
   kind of table. 29 currencies is a list, and a list is sorted and filtered
   (2026-09-12). `override` is passed in because the action column calls it; a
   null one DROPS that column rather than drawing a dead button, and the width
   it frees goes back to Updated — the widths are `<col>` percentages and have
   to sum to 100 either way. Editing a rate is admin-only (decision 0045). */
function fxCols(override: ((r: FxRate) => void) | null): Column<FxRate>[] {
  return [
    { key: "currency", label: "Currency", width: 16, className: "mono", get: (r) => r.currency },
    { key: "rate", label: "Rate USD", width: 22, numeric: true, className: "mono", get: (r) => r.rate_usd },
    {
      key: "source",
      label: "Source",
      width: 20,
      get: (r) => r.source,
      render: (r) => (
        <span className={`pill ${r.source === "manual" ? "warn" : "neutral"}`}>{r.source}</span>
      ),
    },
    {
      key: "updated",
      label: "Updated",
      width: override ? 24 : 42,
      className: "muted dim",
      get: (r) => r.updated_at ?? "",
      title: (r) => r.updated_at ?? undefined,
      render: (r) => <>{r.updated_at ? localDate(r.updated_at) : "—"}</>,
    },
    ...(override
      ? [
          {
            key: "override",
            label: "",
            width: 18,
            interactive: false,
            get: () => "",
            render: (r: FxRate) => (
              <button
                type="button"
                className="btn btn-sm"
                onClick={(e) => {
                  e.stopPropagation();
                  override(r);
                }}
              >
                Override
              </button>
            ),
          } satisfies Column<FxRate>,
        ]
      : []),
  ];
}

export default function FxRatesCard() {
  // Every document in the register converts through these, so a hand-typed
  // rate moves every batch cost and every order margin at once — admin-only
  // on the API (decision 0045). The TABLE stays readable by anybody, because
  // "no exchange rate for HUF" is a warning a non-admin meets on the order and
  // run pages and has to be able to look up before asking for it.
  const { isAdmin } = useAuth();
  const dialog = useDialog();
  const { data: rates, error, setError, reload: load } = useLoad(getFxRates, []);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  async function refresh() {
    setBusy(true);
    setNote("");
    try {
      const r = await refreshFxRates();
      setNote(`Updated ${r.updated} rate(s) across ${r.currencies} currencies.`);
      load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function override(row: FxRate) {
    const v = await dialog.prompt(
      `New rate_usd value for ${row.currency} (currently ${row.rate_usd}):`,
      { title: "Override exchange rate" },
    );
    if (v === null) return;
    const num = Number(v);
    if (!Number.isFinite(num) || num <= 0) {
      await dialog.alert(`"${v}" is not a positive number.`, { title: "Bad rate" });
      return;
    }
    try {
      await setFxRate(row.currency, num);
      load();
    } catch (err) {
      await dialog.alert(errorMessage(err), { title: "Could not save the rate" });
    }
  }

  return (
    <div className="card pad">
      <h2 className="card-title">Exchange rates</h2>
      <p className="muted">
        The register converts every document to USD with these rates. An "unknown FX rate"
        warning anywhere in the app means a currency is missing here.
      </p>
      <ErrorBanner message={error} />
      {note ? <div className="banner-ok">{note}</div> : null}
      {isAdmin ? (
        <div className="btn-row">
          <button type="button" className="btn" disabled={busy} onClick={refresh}>
            Refresh rates
          </button>
        </div>
      ) : null}
      {rates === null ? (
        <Spinner label="loading rates" />
      ) : rates.length === 0 ? (
        <p className="muted">
          {isAdmin
            ? "No rates stored yet — press Refresh rates."
            : "No rates stored yet — an administrator has to fetch them."}
        </p>
      ) : (
        <div className="table-wrap">
          <DataTable
            columns={fxCols(isAdmin ? override : null)}
            rows={rates}
            rowKey={(r) => r.currency}
            persistKey="fx-rates"
            empty="No exchange rates yet."
          />
        </div>
      )}
    </div>
  );
}
