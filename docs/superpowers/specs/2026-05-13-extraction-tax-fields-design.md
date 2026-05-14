# Extraction UI: Subtotal & Tax Fields

**Date:** 2026-05-13
**Status:** Approved (pending implementation plan)
**Scope:** Frontend only

## Problem

The Extraction panel (`frontend/src/components/casefile/ExtractionReceipt.tsx`) does not display or allow editing of `subtotal` or `tax_amount`, even though both fields exist on `InvoiceData` (frontend and backend models).

The current validation in `frontend/src/lib/invoiceValidation.ts:44-53` compares `sum(line_items)` directly to `total`, ignoring tax. For any invoice with non-zero tax, this produces a false "doesn't match item total" warning. Example from the screenshot (INV-1004): line items sum to 1750, tax is 140, total is 1890 — the UI flags the total as wrong, but the math is correct.

The backend (`backend/app/agents/validate.py:146-169`) already validates `subtotal + tax_amount ≈ total` correctly, with a fallback to comparing `sum(line_items)` against `total` when `subtotal` is null. This is a frontend-only gap.

## Goals

- Make `subtotal` and `tax_amount` visible and editable in the Extraction panel.
- Replace the false warning with accurate, independent validation checks that match the backend's model (including the null-subtotal fallback).
- Allow users to correct any of subtotal/tax/total when extraction is wrong, before retrying.
- Fix two pre-existing input bugs on adjacent numeric fields (`total`, `unit_price`) while the file is open: comma-bearing input (e.g., `"1,250.00"`) and the misleading "must be ≥ 0" error for non-numeric input.

## Non-Goals

- No changes to backend API, models, or validation logic — already correct.
- No changes to other casefile components, routes, or the retry flow.
- No auto-computation between fields. All three (subtotal, tax_amount, total) remain independently editable; validation surfaces inconsistencies as warnings, not corrections.
- No `currency` editor. Out of scope; if currency mismatches become a recurring issue, that's a separate ticket.
- `invoicesEqual` is not extended to non-editable fields (`currency`, `payment_terms`, line item `notes`). A field with no UI control can't diverge between draft and prop; YAGNI.

## Design

### UI changes — `ExtractionReceipt.tsx`

Add two new editable rows between **Line items** and **Total**, reusing the existing `Field` component. Layout:

```
LINE ITEMS
  WidgetA   3   250
  WidgetB   2   500
SUBTOTAL    [ 1750.00 ]
TAX         [  140.00 ]
TOTAL       [ 1890.00 ]
```

- The three numeric rows (Subtotal, Tax, Total) are wrapped in a new `<dl className="space-y-3">`. The current code renders the `Field` component (which emits `<dt>`/`<dd>`) inside a plain `<div>` for Total — orphan description-list children outside a `<dl>` is invalid HTML. Wrapping all three in their own `<dl>` fixes this while keeping the visual layout identical.
- Both new fields use mono font, same width and styling as `total`.
- Field labels: `Subtotal`, `Tax` (matches existing label casing — Title Case displayed via uppercase tracking-wide CSS).
- All three numeric inputs (`subtotal`, `tax_amount`, `total`) get `placeholder="0.00"`, matching the existing `unit_price` field.
- No new components. Reuse `Field` and `FieldInput` already defined in the file.
- The `setField` helper already handles `subtotal` and `tax_amount` via the generic `keyof InvoiceData` signature — no new state plumbing.

### Input parsing — `parseNumber` helper

Add a small helper in `invoiceValidation.ts` and export it:

```ts
// Returns null for empty input, NaN for non-numeric, finite number otherwise.
// Strips thousands-separator commas so "1,250.00" parses correctly.
export function parseNumber(v: string): number | null {
  if (v === "") return null;
  return parseFloat(v.replace(/,/g, ""));
}
```

Used by `ExtractionReceipt.tsx` for all four numeric inputs in the receipt:
- `subtotal` (new), `tax_amount` (new), `total` (existing), and `unit_price` (existing in line items).

Replaces the inline `v === "" ? null : parseFloat(v)` and `parseFloat(v)` calls in those onChange handlers. The helper deliberately returns `NaN` (not `null`) for unparseable input so validation can produce a clear "must be a number" error rather than silently coercing.

### Validation changes — `invoiceValidation.ts`

**Tolerance constant:**

```ts
const TOTAL_TOLERANCE = 1.0; // match backend validate.py:21 ($1)
```

Aligns with backend so the UI and backend can't disagree on what's "close enough". (Old frontend used `0.01`.)

**Extend `FieldKey`:**

```ts
export type FieldKey =
  | "vendor"
  | "invoice_number"
  | "date"
  | "due_date"
  | "subtotal"      // new
  | "tax_amount"    // new
  | "total"
  | `items.${number}.item`
  | `items.${number}.quantity`
  | `items.${number}.unit_price`;
```

**Field-level numeric sanity:**

For each of `subtotal`, `tax_amount`, `total`, and each line item's `unit_price`:

- If `isNaN(value)` → error `"must be a number"`.
- Else if `value < 0` → error `"must be ≥ 0"`.
- `null` is allowed for `subtotal`, `tax_amount`, and `unit_price` (all `float | None` in the model). `total` remains required (existing behavior: null/undefined → `"must be ≥ 0"` for back-compat; not changing this to keep the warning-vs-error UX stable).

This splits the existing combined check on `total` and `unit_price` into two clearer messages, matching the new fields.

**Relationship checks** (replace the existing single `sum(line_items) vs total` comparison):

1. **Line items vs subtotal** (warning on `subtotal`):
   - Only runs when `subtotal !== null` and there is no field-level error on `subtotal`.
   - If `|sum(line_items) − subtotal| > TOTAL_TOLERANCE`, set `warnings.subtotal = "doesn't match item total"`.

2. **Subtotal + tax vs total** (warning on `total`):
   - Only runs when `subtotal !== null`, `total !== null`, and neither has a field-level error.
   - Treats `tax_amount` as `0` when null (matches backend `validate.py:159`: `inv.subtotal + (inv.tax_amount or 0.0)`).
   - If `|subtotal + (tax_amount ?? 0) − total| > TOTAL_TOLERANCE`, set `warnings.total = "doesn't match subtotal + tax"`.

3. **Fallback: line items vs total when subtotal is null** (warning on `total`):
   - Only runs when `subtotal === null`, `total !== null`, line items exist, and `total` has no field-level error.
   - If `|sum(line_items) − total| > TOTAL_TOLERANCE`, set `warnings.total = "doesn't match item total"`.
   - Mirrors backend `validate.py:151` fallback. Without this, an invoice with missing subtotal would silently pass the UI while the backend flags it on retry.

**Null handling summary:**

| `subtotal` | `tax_amount` | `total` | Checks that run |
|---|---|---|---|
| null | any | null | None |
| null | any | set | #3 (line items vs total) |
| set | null | null | #1 (line items vs subtotal) |
| set | null | set | #1, #2 (tax treated as 0) |
| set | set | null | #1 |
| set | set | set | #1, #2 |

**`invoicesEqual` update:**

Extend to compare `subtotal` and `tax_amount`. Do not add comparisons for `currency`, `payment_terms`, or line item `notes` — none of them have UI controls, so they can't diverge between draft and prop.

### Data flow / retry payload

No change. `ExtractionReceipt` already sends the full `InvoiceData` (including untouched `subtotal`/`tax_amount`) to `POST /api/runs/{run_id}/retry`. With these fields now editable, the payload shape is identical; the backend's `InvoiceData` Pydantic model already accepts both. No backend changes required.

## Verification

The frontend has no test runner configured (`package.json` only defines `dev` and `build`). Verification is via type-checking + manual UI inspection.

**Type-check / build:**

- `cd frontend && npm run build` must pass (catches `FieldKey` type errors, the new `parseNumber` import, and any wiring mistakes).

**Manual UI checks:**

Using the INV-1004 case file from the screenshot (subtotal=1750, tax=140, total=1890):

1. **Happy path:** Open the run. Confirm Subtotal=1750, Tax=140, Total=1890 render with no warnings. The previously-incorrect "doesn't match item total" warning is gone.
2. **Subtotal mismatch:** Edit a line item quantity (WidgetA 3 → 4). Expect warning on **Subtotal**: "doesn't match item total". Total stays clean unless `subtotal + tax` also drifts > $1 from total.
3. **Total mismatch:** Edit tax from 140 → 141. Expect warning on **Total**: "doesn't match subtotal + tax".
4. **Null subtotal, total set:** Clear Subtotal. Expect fallback check #3 to run: if `sum(line_items) ≈ total` within $1 (it won't be, since tax=140), expect "doesn't match item total" on **Total**.
5. **Null tax with subtotal set:** Clear Tax. Expect check #2 to treat tax as 0 — Total warns "doesn't match subtotal + tax" because 1750 ≠ 1890.
6. **Both subtotal and tax null:** Clear both. Expect only check #3 (line items vs total). If their sum is within $1 of total, no warning; otherwise warns on Total.
7. **Negative input:** Type `-5` into Subtotal. Expect error "must be ≥ 0" on Subtotal; relationship checks skipped.
8. **Non-numeric input:** Type `abc` into Tax. Expect error "must be a number" on Tax; relationship checks skipped.
9. **Comma input:** Type `1,750` into Subtotal. Expect it parses as `1750` and no errors fire (warning depends on rest of the math).
10. **Tolerance ($1):** Set Subtotal to `1749.50` (50¢ below line item sum of 1750). Expect no warning. Set to `1748.50` (1.50 off). Expect warning.
11. **Dirty-state / Save:** Edit Tax only. Expect "Save & retry" button to enable (proves `invoicesEqual` extended). Save and confirm the retry succeeds.
12. **HTML validity (spot check):** Open browser devtools, inspect the Subtotal/Tax/Total section, confirm it's wrapped in a `<dl>` with the three `<dt>`/`<dd>` pairs as children.

## Risks & Tradeoffs

- **Warning relocation:** The "doesn't match item total" warning now lives on `subtotal` when subtotal is present, and on `total` only when subtotal is null (fallback path). Visible behavior change from the current single-warning-on-total model. Justified because the new placement points at the actual source of the mismatch.
- **Three-way inconsistency:** With all three fields independently editable, users can produce internally-inconsistent invoices. By design — warnings surface the issue without blocking. The retry endpoint accepts whatever the user submits; the backend's own validation flags it again on the new run, which is the intended audit trail behavior.
- **Empty-tax convention:** Treating `tax_amount = null` as `0` for check #2 matches the backend exactly. A tax-free invoice with `tax_amount = null` and a slightly off `total` will still warn correctly.
- **Tolerance bump (0.01 → 1.00):** Slightly less strict, but eliminates the risk of UI warnings that the backend ignores. Penny-rounding noise is now silenced both places consistently.
- **Scope creep on existing fields:** `total` and `unit_price` get the new `parseNumber` helper and the split "must be a number" error. Same-file, surgical, and removes a UX inconsistency that would otherwise be created by fixing only the new fields. Not adding any unrelated logic.

## File touch list

- `frontend/src/lib/invoiceValidation.ts` — add `TOTAL_TOLERANCE`, add `parseNumber`, extend `FieldKey`, split numeric sanity into NaN/negative branches, replace single comparison with three relationship checks, extend `invoicesEqual`.
- `frontend/src/components/casefile/ExtractionReceipt.tsx` — add two `Field` rows for Subtotal and Tax, wrap Subtotal/Tax/Total in a `<dl>`, swap inline parse calls for `parseNumber`, add `placeholder="0.00"` to numeric fields.

No other files touched.
