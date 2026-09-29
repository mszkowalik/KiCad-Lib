import { useEffect, useState } from "react";
import {
  createSupplier,
  deleteSupplier,
  errorMessage,
  getSuppliers,
  isAbortError,
  setSupplierOrder,
  updateSupplier,
  type Supplier,
} from "../api";
import { useAuth } from "../auth";
import { useDialog } from "./Dialog";
import Field, { FieldRow } from "./Field";
import { ErrorBanner, Spinner } from "./Ui";

/** The supplier register, in LIBRARY ORDER — decision 0055.
 *
 *  The order is the point of this list: a part that sets no order of its own is
 *  priced by the first supplier here that has a price for it. That is why this
 *  is a plain ordered table and not a DataTable — a sortable header would offer
 *  to reorder the list by something other than its meaning (the same exception
 *  the field solver's stackup table takes).
 *
 *  Everybody reads it; only an admin changes it, and the API refuses otherwise
 *  (`tests/auth/test_role_gates.py`). A reorder writes a price-history snapshot
 *  for every priced part, so a production run already priced keeps the order
 *  of its own date. A supplier's name never changes: prices refer to it. */
export default function SuppliersCard() {
  const { isAdmin } = useAuth();
  const dialog = useDialog();
  const [rows, setRows] = useState<Supplier[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [website, setWebsite] = useState("");

  useEffect(() => {
    const ctrl = new AbortController();
    getSuppliers(ctrl.signal)
      .then(setRows)
      .catch((err) => {
        if (!isAbortError(err)) setError(errorMessage(err));
      });
    return () => ctrl.abort();
  }, []);

  const run = (work: () => Promise<Supplier[]>) => {
    setBusy(true);
    setError(null);
    work()
      .then((r) => {
        setRows(r);
        setBusy(false);
      })
      .catch((err) => {
        setError(errorMessage(err));
        setBusy(false);
      });
  };

  const move = (i: number, dir: -1 | 1) => {
    if (rows === null) return;
    const ids = rows.map((s) => s.id);
    const j = i + dir;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    run(() => setSupplierOrder(ids));
  };

  const add = () =>
    run(async () => {
      await createSupplier({ name: name.trim(), website: website.trim() });
      setName("");
      setWebsite("");
      return getSuppliers();
    });

  const edit = async (s: Supplier) => {
    const site = await dialog.prompt(`Website of ${s.name}`, {
      title: "Edit supplier", initial: s.website, placeholder: "https://…",
    });
    if (site === null) return;
    const notes = await dialog.prompt(`Notes on ${s.name} (account number, contact, terms)`, {
      title: "Edit supplier", initial: s.notes,
    });
    if (notes === null) return;
    run(async () => {
      await updateSupplier(s.id, { website: site, notes });
      return getSuppliers();
    });
  };

  const remove = async (s: Supplier) => {
    const ok = await dialog.confirm(`Remove ${s.name} from the register?`, {
      title: "Remove supplier", confirmLabel: "Remove", tone: "danger",
    });
    if (ok)
      run(async () => {
        await deleteSupplier(s.id);
        return getSuppliers();
      });
  };

  return (
    <div className="card pad">
      <h2>Suppliers</h2>
      <p className="muted dim">
        A part that sets no supplier order of its own is priced by the first supplier in this list
        that has a price for it. One supplier gives the whole price ladder. JLCPCB and LCSC are
        refreshed by the platform; every other supplier's prices are typed on the part's page.
      </p>
      {error ? <ErrorBanner message={error} /> : null}
      {rows === null && !error ? <Spinner label="Loading suppliers" /> : null}
      {rows !== null ? (
        <table className="data data-fixed ladder-table supplier-register-table">
          <thead>
            <tr>
              <th className="num">#</th>
              <th>Supplier</th>
              <th>Prices</th>
              <th className="num">Parts</th>
              <th>Notes</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((s, i) => (
              <tr key={s.id}>
                <td className="num mono muted">{i + 1}</td>
                <td title={s.website || undefined}>
                  {s.website ? (
                    <a className="comp-link" href={s.website} target="_blank" rel="noreferrer">{s.name}</a>
                  ) : (
                    s.name
                  )}
                </td>
                <td className="muted">{s.connector ? "refreshed by the platform" : "typed per part"}</td>
                <td className="num mono">{s.linked_components}</td>
                <td className="muted" title={s.notes || undefined}>{s.notes}</td>
                <td className="ctr">
                  {isAdmin ? (
                    <>
                      <button type="button" className="icon-btn" title="Earlier in the library order"
                        disabled={busy || i === 0} onClick={() => move(i, -1)}>↑</button>
                      <button type="button" className="icon-btn" title="Later in the library order"
                        disabled={busy || i === rows.length - 1} onClick={() => move(i, 1)}>↓</button>
                      <button type="button" className="icon-btn" title="Edit website and notes"
                        disabled={busy} onClick={() => void edit(s)}>✎</button>
                      {s.connector ? null : (
                        <button type="button" className="row-del" title={`Remove ${s.name}`}
                          disabled={busy} onClick={() => void remove(s)}>&#x2715;</button>
                      )}
                    </>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {isAdmin && rows !== null ? (
        <>
          <FieldRow>
            <Field label="New supplier" hint="The name cannot change later — prices refer to it.">
              <input className="text" value={name} placeholder="e.g. Farnell"
                onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label="Website" wide>
              <input className="text" value={website} placeholder="https://…"
                onChange={(e) => setWebsite(e.target.value)} />
            </Field>
          </FieldRow>
          <div className="btn-row">
            <button type="button" className="btn btn-sm" disabled={busy || name.trim() === ""} onClick={add}>
              ＋ Add supplier
            </button>
          </div>
        </>
      ) : null}
    </div>
  );
}
