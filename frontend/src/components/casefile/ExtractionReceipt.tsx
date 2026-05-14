import { useEffect, useState } from "react";
import { useLocation } from "wouter";
import { retryRun } from "../../api/client.ts";
import { hasErrors, invoicesEqual, parseNumber, validateDraft, type FieldKey } from "../../lib/invoiceValidation.ts";
import type { InvoiceData } from "../../types/state.ts";
import { RotateCcw } from "../common/Icons.tsx";

export function ExtractionReceipt({
  runId,
  invoice,
}: {
  runId: string;
  invoice: InvoiceData;
}) {
  const [, setLocation] = useLocation();
  const [draft, setDraft] = useState<InvoiceData>(invoice);
  const [pending, setPending] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Reset draft when the upstream invoice prop changes (e.g., navigating to a different run).
  useEffect(() => setDraft(invoice), [invoice]);

  const { errors, warnings } = validateDraft(draft);
  const dirty = !invoicesEqual(draft, invoice);
  const canSave = dirty && !hasErrors({ errors, warnings });

  const onSave = async () => {
    setPending(true);
    setErr(null);
    try {
      const { run_id } = await retryRun(runId, draft);
      setLocation(`/runs/${run_id}`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "retry failed");
    } finally {
      setPending(false);
    }
  };

  const setField = <K extends keyof InvoiceData>(key: K, value: InvoiceData[K]) =>
    setDraft({ ...draft, [key]: value });

  const setItemField = (i: number, key: keyof InvoiceData["line_items"][0], value: any) => {
    const items = [...draft.line_items];
    items[i] = { ...items[i], [key]: value };
    setDraft({ ...draft, line_items: items });
  };

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-6">
      <h3 className="text-base font-semibold mb-4">Extraction</h3>
      <dl className="space-y-3">
        <Field
          label="Vendor"
          value={draft.vendor ?? ""}
          onChange={(v) => setField("vendor", v || null)}
          error={errors.vendor}
        />
        <Field
          label="Invoice #"
          value={draft.invoice_number ?? ""}
          onChange={(v) => setField("invoice_number", v || null)}
          error={errors.invoice_number}
          mono
        />
        <Field
          label="Date"
          value={draft.date ?? ""}
          onChange={(v) => setField("date", v || null)}
          placeholder="YYYY-MM-DD"
          error={errors.date}
          mono
        />
        <Field
          label="Due date"
          value={draft.due_date ?? ""}
          onChange={(v) => setField("due_date", v || null)}
          placeholder="YYYY-MM-DD"
          error={errors.due_date}
          mono
        />
      </dl>
      <div className="mt-5">
        <div className="text-xs font-medium uppercase tracking-wide text-slate-500 mb-2">
          Line items
        </div>
        <div className="space-y-2">
          {draft.line_items.map((it, i) => (
            <div key={i} className="grid grid-cols-[1fr_64px_88px] gap-2">
              <FieldInput
                value={it.item}
                onChange={(v) => setItemField(i, "item", v)}
                error={errors[`items.${i}.item` as FieldKey]}
                mono
              />
              <FieldInput
                value={String(it.quantity)}
                onChange={(v) => setItemField(i, "quantity", parseInt(v, 10) || 0)}
                error={errors[`items.${i}.quantity` as FieldKey]}
                mono
              />
              <FieldInput
                value={it.unit_price === null ? "" : String(it.unit_price)}
                onChange={(v) => setItemField(i, "unit_price", parseNumber(v))}
                placeholder="0.00"
                error={errors[`items.${i}.unit_price` as FieldKey]}
                mono
              />
            </div>
          ))}
        </div>
      </div>
      <dl className="mt-5 space-y-3">
        <Field
          label="Subtotal"
          value={draft.subtotal === null ? "" : String(draft.subtotal)}
          onChange={(v) => setField("subtotal", parseNumber(v))}
          placeholder="0.00"
          error={errors.subtotal}
          warning={warnings.subtotal}
          mono
        />
        <Field
          label="Tax"
          value={draft.tax_amount === null ? "" : String(draft.tax_amount)}
          onChange={(v) => setField("tax_amount", parseNumber(v))}
          placeholder="0.00"
          error={errors.tax_amount}
          warning={warnings.tax_amount}
          mono
        />
        <Field
          label="Total"
          value={draft.total === null ? "" : String(draft.total)}
          onChange={(v) => setField("total", parseNumber(v))}
          placeholder="0.00"
          error={errors.total}
          warning={warnings.total}
          mono
        />
      </dl>
      <div className="mt-6 flex items-center gap-3">
        <button
          type="button"
          onClick={onSave}
          disabled={!canSave || pending}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <RotateCcw size={14} /> {pending ? "Retrying…" : "Save & retry"}
        </button>
        {err && <span className="text-xs text-rose-600">{err}</span>}
      </div>
      <p className="text-xs text-slate-500 mt-2">
        Editing creates a new run. The original stays in the audit trail.
      </p>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  error,
  warning,
  mono,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  error?: string;
  warning?: string;
  mono?: boolean;
}) {
  return (
    <div className="grid grid-cols-[140px_1fr] items-baseline gap-3">
      <dt className="text-xs uppercase tracking-wide text-slate-500">{label}</dt>
      <dd>
        <FieldInput
          value={value}
          onChange={onChange}
          placeholder={placeholder}
          error={error}
          warning={warning}
          mono={mono}
        />
      </dd>
    </div>
  );
}

function FieldInput({
  value,
  onChange,
  placeholder,
  error,
  warning,
  mono,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  error?: string;
  warning?: string;
  mono?: boolean;
}) {
  const borderCls = error
    ? "border-rose-400"
    : warning
      ? "border-amber-400"
      : "border-slate-200";
  return (
    <div>
      <input
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className={`w-full px-2 py-1 text-sm rounded border ${borderCls} focus:outline-none focus:ring-1 focus:ring-indigo-500 ${mono ? "font-mono" : ""}`}
      />
      {error && <p className="text-xs text-rose-600 mt-0.5">{error}</p>}
      {!error && warning && <p className="text-xs text-amber-600 mt-0.5">{warning}</p>}
    </div>
  );
}
