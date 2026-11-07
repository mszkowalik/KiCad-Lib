/** A recurring invoice: what a month's draft is written from (decision 0066).
 *
 *  The key and the company are set once, because `generate` finds a month's draft
 *  by them. An edit sends only the fields that differ, so the audit row names the
 *  edit and not the whole form. There is no delete: a retired template is
 *  switched off, and its drafts keep naming it.
 */
import { useState } from "react";

import {
  createSalesTemplate,
  errorMessage,
  updateSalesTemplate,
  type CustomerRow,
  type SalesProductRow,
  type SalesTemplate,
} from "../../api";
import { useAuth } from "../../auth";
import AutoTextarea from "../AutoTextarea";
import Field, { CheckField, FieldGrid } from "../Field";
import { useModal } from "../modal";
import NumberInput from "../NumberInput";
import { ErrorBanner, Spinner } from "../Ui";
import { blankLine, CustomerSelect, draftLineOf, linesBody, linesReady, SalesLinesEditor, type DraftLine } from "./SalesLines";

/** The model's range: every month has these days. */
const DAYS = Array.from({ length: 28 }, (_x, i) => String(i + 1));

interface Form {
  description: string;
  customer: number | "";
  day: string;
  terms: number;
  lines: DraftLine[];
  extra: string;
  active: boolean;
}

const formOf = (t: SalesTemplate | null): Form => ({
  description: t?.description ?? "",
  customer: t?.customer_id ?? "",
  day: t?.day ?? "last",
  terms: t?.payment_terms_days ?? 14,
  lines: t?.lines.length ? t.lines.map(draftLineOf) : [blankLine()],
  extra: (t?.extra_info ?? []).join("\n"),
  active: t?.active ?? true,
});

const bodyOf = (f: Form) => ({
  description: f.description.trim(),
  customer_id: f.customer === "" ? null : f.customer,
  day: f.day,
  payment_terms_days: f.terms,
  lines: linesBody(f.lines),
  extra_info: f.extra.split("\n").map((x) => x.trim()).filter(Boolean),
  active: f.active,
});

/** The fields of `after` that differ from `before`. */
function differing<T extends object>(before: T, after: T): Partial<T> {
  return Object.fromEntries(
    Object.entries(after).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify(before[k as keyof T])),
  ) as Partial<T>;
}

export default function SalesTemplateDialog({ template, customers, products, onClose }: {
  /** `null`: a new one. */
  template: SalesTemplate | null;
  customers: CustomerRow[];
  products: SalesProductRow[];
  onClose: (changed: boolean) => void;
}) {
  const { companies } = useAuth();
  const sellers = companies.filter((c) => c.issues_invoices);
  const modal = useModal(() => onClose(false));
  const [companyId, setCompanyId] = useState<number | "">(template?.company_id ?? sellers[0]?.id ?? "");
  const [key, setKey] = useState(template?.key ?? "");
  const [form, setForm] = useState<Form>(() => formOf(template));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (patch: Partial<Form>) => setForm((f) => ({ ...f, ...patch }));

  const body = bodyOf(form);
  const changes = template ? differing(bodyOf(formOf(template)), body) : body;
  const ready = companyId !== "" && key.trim() !== "" && form.customer !== "" && linesReady(form.lines)
    && Object.keys(changes).length > 0;
  const exempt = form.lines.some((l) => l.vat_rate === "zw");

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      if (template) await updateSalesTemplate(template.id, changes);
      else await createSalesTemplate({ company_id: Number(companyId), key: key.trim(), ...body });
      onClose(true);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" {...modal.backdropProps}>
      <div className="card pad modal-card modal-card-wide" {...modal.cardProps}>
        <h2 className="card-title">{template ? `Edit the template ${template.key}` : "New template"}</h2>
        <p className="muted dim">
          A recurring invoice. Each month's draft takes the buyer and the positions from here, with the next number.
          A draft already written does not change.
        </p>
        {error ? <ErrorBanner message={error} /> : null}
        <FieldGrid>
          {!template && sellers.length > 1 ? (
            <Field label="Seller">
              <select className="text" value={companyId} onChange={(e) => setCompanyId(Number(e.target.value))}>
                {sellers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </Field>
          ) : null}
          <Field label="Key" hint={template ? "It cannot change: each draft names it." : "A short name. It cannot change later."}>
            <input className="text mono" value={key} maxLength={40} disabled={!!template} onChange={(e) => setKey(e.target.value)} />
          </Field>
          <Field label="Day of the month" hint="The issue date and the sale date of the draft.">
            <select className="text" value={form.day} onChange={(e) => set({ day: e.target.value })}>
              <option value="last">Last day</option>
              {form.day !== "last" && !DAYS.includes(form.day) ? <option value={form.day}>{form.day}</option> : null}
              {DAYS.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </Field>
          <Field label="Payment terms (days)">
            <NumberInput className="text num-input" value={form.terms} min={0} step={1}
              onChange={(v) => set({ terms: Math.round(v) })} />
          </Field>
          <Field label="Buyer" wide>
            <CustomerSelect customers={customers} value={form.customer} onChange={(customer) => set({ customer })} />
          </Field>
          <Field label="Description" hint="For this list only. It is not printed." wide>
            <input className="text" value={form.description} maxLength={500} onChange={(e) => set({ description: e.target.value })} />
          </Field>
        </FieldGrid>
        <p className="muted dim">Positions:</p>
        <SalesLinesEditor lines={form.lines} products={products} onChange={(lines) => set({ lines })} />
        <div className="btn-row">
          <button type="button" className="btn btn-sm" onClick={() => set({ lines: [...form.lines, blankLine()] })}>
            Add a position
          </button>
        </div>
        {exempt ? (
          <div className="banner-warn">
            A template has no field for the legal basis of an exemption. Type it on each draft, before you take its
            XML for KSeF.
          </div>
        ) : null}
        <FieldGrid>
          <Field label="Extra lines on the invoice" hint="One per line, e.g. the contract it is issued under." wide>
            <AutoTextarea className="text" rows={2} value={form.extra} onChange={(e) => set({ extra: e.target.value })} />
          </Field>
        </FieldGrid>
        <CheckField checked={form.active} onChange={(active) => set({ active })}>
          Active: a person can write a draft from it
        </CheckField>
        <div className="btn-row modal-actions">
          {busy ? <Spinner /> : null}
          <button type="button" className="btn" onClick={() => onClose(false)}>Cancel</button>
          <button type="button" className="btn btn-primary" disabled={busy || !ready} onClick={() => void save()}>
            {template ? "Save" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}
