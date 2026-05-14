import type { InvoiceData } from "../types/state.ts";

export type FieldKey =
  | "vendor"
  | "invoice_number"
  | "date"
  | "due_date"
  | "subtotal"
  | "tax_amount"
  | "total"
  | `items.${number}.item`
  | `items.${number}.quantity`
  | `items.${number}.unit_price`;

export interface ValidationResult {
  errors: Partial<Record<FieldKey, string>>;
  warnings: Partial<Record<FieldKey, string>>;
}

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

// Tolerance for money comparisons, in dollars.
// Matches backend TOTAL_TOLERANCE in backend/app/agents/validate.py.
const TOTAL_TOLERANCE = 1.0;

/**
 * Parse a string from a numeric input field.
 * - "" → null (blank input)
 * - Strips thousands-separator commas: "1,250.00" → 1250
 * - Unparseable input → NaN (validation surfaces this as "must be a number")
 */
export function parseNumber(v: string): number | null {
  if (v === "") return null;
  return parseFloat(v.replace(/,/g, ""));
}

export function validateDraft(draft: InvoiceData): ValidationResult {
  const errors: Partial<Record<FieldKey, string>> = {};
  const warnings: Partial<Record<FieldKey, string>> = {};

  if (!draft.vendor || draft.vendor.trim() === "") errors.vendor = "required";
  if (!draft.invoice_number || draft.invoice_number.trim() === "") errors.invoice_number = "required";

  if (draft.date && !DATE_RE.test(draft.date)) errors.date = "use YYYY-MM-DD";
  if (draft.due_date && !DATE_RE.test(draft.due_date)) errors.due_date = "use YYYY-MM-DD";

  // Total is required.
  if (draft.total === null || draft.total === undefined) {
    errors.total = "must be ≥ 0";
  } else if (isNaN(draft.total)) {
    errors.total = "must be a number";
  } else if (draft.total < 0) {
    errors.total = "must be ≥ 0";
  }

  // Subtotal is optional; if present, must be a non-negative number.
  if (draft.subtotal !== null && draft.subtotal !== undefined) {
    if (isNaN(draft.subtotal)) {
      errors.subtotal = "must be a number";
    } else if (draft.subtotal < 0) {
      errors.subtotal = "must be ≥ 0";
    }
  }

  // Tax is optional; if present, must be a non-negative number.
  if (draft.tax_amount !== null && draft.tax_amount !== undefined) {
    if (isNaN(draft.tax_amount)) {
      errors.tax_amount = "must be a number";
    } else if (draft.tax_amount < 0) {
      errors.tax_amount = "must be ≥ 0";
    }
  }

  draft.line_items.forEach((it, i) => {
    if (!it.item || it.item.trim() === "") errors[`items.${i}.item`] = "required";
    if (!Number.isInteger(it.quantity) || it.quantity < 1) {
      errors[`items.${i}.quantity`] = "must be a positive integer";
    }
    if (it.unit_price !== null && it.unit_price !== undefined) {
      if (isNaN(it.unit_price)) {
        errors[`items.${i}.unit_price`] = "must be a number";
      } else if (it.unit_price < 0) {
        errors[`items.${i}.unit_price`] = "must be ≥ 0";
      }
    }
  });

  const lineItemSum = draft.line_items.reduce(
    (acc, it) => acc + (it.unit_price ?? 0) * it.quantity,
    0,
  );

  // Relationship check #1: line items vs subtotal.
  if (draft.subtotal !== null && draft.subtotal !== undefined && !errors.subtotal) {
    if (Math.abs(lineItemSum - draft.subtotal) > TOTAL_TOLERANCE) {
      warnings.subtotal = "doesn't match item total";
    }
  }

  // Relationship check #2: subtotal + tax vs total.
  if (
    draft.subtotal !== null && draft.subtotal !== undefined &&
    draft.total !== null && draft.total !== undefined &&
    !errors.subtotal && !errors.total
  ) {
    const expected = draft.subtotal + (draft.tax_amount ?? 0);
    if (Math.abs(expected - draft.total) > TOTAL_TOLERANCE) {
      warnings.total = "doesn't match subtotal + tax";
    }
  }

  // Relationship check #3 (fallback): line items vs total when subtotal is null.
  // Mirrors backend validate.py:151.
  if (
    (draft.subtotal === null || draft.subtotal === undefined) &&
    draft.total !== null && draft.total !== undefined &&
    !errors.total &&
    draft.line_items.length > 0
  ) {
    if (Math.abs(lineItemSum - draft.total) > TOTAL_TOLERANCE) {
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
