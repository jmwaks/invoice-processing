import type { InvoiceData } from "../types/state.ts";

export type FieldKey =
  | "vendor"
  | "invoice_number"
  | "date"
  | "due_date"
  | "total"
  | `items.${number}.item`
  | `items.${number}.quantity`
  | `items.${number}.unit_price`;

export interface ValidationResult {
  errors: Partial<Record<FieldKey, string>>;
  warnings: Partial<Record<FieldKey, string>>;
}

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export function validateDraft(draft: InvoiceData): ValidationResult {
  const errors: Partial<Record<FieldKey, string>> = {};
  const warnings: Partial<Record<FieldKey, string>> = {};

  if (!draft.vendor || draft.vendor.trim() === "") errors.vendor = "required";
  if (!draft.invoice_number || draft.invoice_number.trim() === "") errors.invoice_number = "required";

  if (draft.date && !DATE_RE.test(draft.date)) errors.date = "use YYYY-MM-DD";
  if (draft.due_date && !DATE_RE.test(draft.due_date)) errors.due_date = "use YYYY-MM-DD";

  if (draft.total === null || draft.total === undefined || isNaN(draft.total) || draft.total < 0) {
    errors.total = "must be ≥ 0";
  }

  draft.line_items.forEach((it, i) => {
    if (!it.item || it.item.trim() === "") errors[`items.${i}.item`] = "required";
    if (!Number.isInteger(it.quantity) || it.quantity < 1) {
      errors[`items.${i}.quantity`] = "must be a positive integer";
    }
    if (it.unit_price !== null && (isNaN(it.unit_price) || it.unit_price < 0)) {
      errors[`items.${i}.unit_price`] = "must be ≥ 0";
    }
  });

  // Soft warning: total mismatch with sum of line items (within 1¢).
  if (draft.total !== null && !errors.total) {
    const sum = draft.line_items.reduce(
      (acc, it) => acc + (it.unit_price ?? 0) * it.quantity,
      0,
    );
    if (Math.abs(sum - draft.total) > 0.01) {
      warnings.total = "doesn't match item total";
    }
  }

  return { errors, warnings };
}

export function hasErrors(result: ValidationResult): boolean {
  return Object.keys(result.errors).length > 0;
}

export function invoicesEqual(a: InvoiceData, b: InvoiceData): boolean {
  if (a.invoice_number !== b.invoice_number) return false;
  if (a.vendor !== b.vendor) return false;
  if (a.date !== b.date) return false;
  if (a.due_date !== b.due_date) return false;
  if (a.total !== b.total) return false;
  if (a.line_items.length !== b.line_items.length) return false;
  for (let i = 0; i < a.line_items.length; i++) {
    const x = a.line_items[i];
    const y = b.line_items[i];
    if (x.item !== y.item || x.quantity !== y.quantity || x.unit_price !== y.unit_price) {
      return false;
    }
  }
  return true;
}
