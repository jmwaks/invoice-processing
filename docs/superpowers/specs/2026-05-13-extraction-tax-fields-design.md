# Extraction UI: Subtotal & Tax Fields

**Date:** 2026-05-13
**Status:** Approved (pending implementation plan)
**Scope:** Frontend only

## Problem

The Extraction panel (`frontend/src/components/casefile/ExtractionReceipt.tsx`) does not display or allow editing of `subtotal` or `tax_amount`, even though both fields exist on `InvoiceData` (frontend and backend models).

The current validation in `frontend/src/lib/invoiceValidation.ts:44-53` compares `sum(line_items)` directly to `total`, ignoring tax. For any invoice with non-zero tax, this produces a false "doesn't match item total" warning. Example from the screenshot (INV-1004): line items sum to 1750, tax is 140, total is 1890 — the UI flags the total as wrong, but the math is correct.

The backend (`backend/app/agents/validate.py:158-168`) already validates `subtotal + tax_amount ≈ total` correctly. This is a frontend-only gap.

## Goals

- Make `subtotal` and `tax_amount` visible and editable in the Extraction panel.
- Replace the false warning with accurate, independent validation checks that match the backend's model.
- Allow users to correct any of subtotal/tax/total when extraction is wrong, before retrying.

## Non-Goals

- No changes to backend API, models, or validation logic — already correct.
- No changes to other casefile components, routes, or the retry flow.
- No auto-computation between fields. All three (subtotal, tax_amount, total) remain independently editable; validation surfaces inconsistencies as warnings, not corrections.

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

- Both new fields use mono font, same width and styling as `total`.
- Blank input → `null` (same coercion as `total`: `v === "" ? null : parseFloat(v)`).
- Field labels: `Subtotal`, `Tax` (matches existing label casing — Title Case displayed via uppercase tracking-wide CSS).
- No new components. Reuse `Field` and `FieldInput` already defined in the file.
- The `setField` helper already handles `subtotal` and `tax_amount` via the generic `keyof InvoiceData` signature — no new state plumbing.

### Validation changes — `invoiceValidation.ts`

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

**Field-level numeric sanity** (mirrors existing `total` rules):

- `subtotal`: if non-null, must not be NaN and must be ≥ 0 — else `errors.subtotal = "must be ≥ 0"`.
- `tax_amount`: if non-null, must not be NaN and must be ≥ 0 — else `errors.tax_amount = "must be ≥ 0"`.
- Blank/null is allowed for both (matches backend, which models them as `float | None`).

**Relationship checks** (replace the existing single `sum(line_items) vs total` comparison):

1. **Line items vs subtotal** (warning on `subtotal`):
   - Only runs when `subtotal !== null` and there are no field-level errors on `subtotal`.
   - If `|sum(line_items) − subtotal| > 0.01`, set `warnings.subtotal = "doesn't match item total"`.
   - This moves the existing warning text from `total` to `subtotal`, where the mismatch actually lives.

2. **Subtotal + tax vs total** (warning on `total`):
   - Only runs when `subtotal !== null`, `total !== null`, and neither has a field-level error.
   - Treats `tax_amount` as `0` when null (matches backend behavior in `validate.py:159`: `inv.subtotal + (inv.tax_amount or 0.0)`).
   - If `|subtotal + (tax_amount ?? 0) − total| > 0.01`, set `warnings.total = "doesn't match subtotal + tax"`.

**Null handling summary:**

| `subtotal` | `tax_amount` | `total` | Behavior |
|---|---|---|---|
| null | any | any | Skip both relationship checks |
| set | null | set | Check #1 runs; check #2 runs with tax treated as 0 |
| set | set | null | Check #1 runs; check #2 skipped |
| set | set | set | Both checks run |

**`invoicesEqual` update:**

Extend the function to compare `subtotal` and `tax_amount`, so the dirty check in `ExtractionReceipt.tsx` correctly enables "Save & retry" when only those fields change.

### Data flow / retry payload

No change. `ExtractionReceipt` already sends the full `InvoiceData` (including untouched `subtotal`/`tax_amount`) to `POST /api/runs/{run_id}/retry`. With these fields now editable, the payload shape is identical; the backend's `InvoiceData` Pydantic model already accepts both. No backend changes required.

## Verification

The frontend has no test runner configured (`package.json` only defines `dev` and `build`). Verification is via type-checking + manual UI inspection.

**Type-check / build:**

- `cd frontend && npm run build` must pass (catches `FieldKey` type errors and any wiring mistakes).

**Manual UI checks:**

Using the INV-1004 case file from the screenshot (subtotal=1750, tax=140, total=1890):

1. **Happy path:** Open the run. Confirm Subtotal=1750, Tax=140, Total=1890 render with no warnings. The previously-incorrect "doesn't match item total" warning is gone.
2. **Subtotal mismatch:** Edit a line item quantity (e.g., WidgetA 3 → 4). Expect warning on **Subtotal**: "doesn't match item total". Total remains warning-free until subtotal+tax stops matching it.
3. **Total mismatch:** Edit tax from 140 → 141. Expect warning on **Total**: "doesn't match subtotal + tax".
4. **Null subtotal:** Clear the Subtotal field. Expect no relationship warnings on subtotal or total.
5. **Null tax with subtotal set:** Clear Tax. Expect check #2 to treat tax as 0 — if subtotal=total it stays clean; otherwise warns on Total.
6. **Field-level error:** Type `-5` into Subtotal. Expect error "must be ≥ 0" on Subtotal; check #1 is skipped because of the error.
7. **Dirty-state / Save:** Edit Tax only. Expect "Save & retry" button to enable (proves `invoicesEqual` updated). Save and confirm the retry succeeds.

## Risks & Tradeoffs

- **Warning relocation:** Moving "doesn't match item total" from the `total` field to the `subtotal` field is a visible behavior change. Acceptable because subtotal is where that specific mismatch actually lives; previous placement was misleading.
- **Three-way inconsistency:** With all three fields independently editable, a user can produce internally-inconsistent invoices (e.g., subtotal+tax ≠ total). This is by design per the chosen approach — warnings surface the issue without blocking. The retry endpoint will accept whatever the user submits; the backend's own validation will flag it again on the new run, which is the intended audit trail behavior.
- **Empty-tax convention:** Treating `tax_amount = null` as `0` for the check matches the backend exactly but means a tax-free invoice with `tax_amount = null` and a slightly off `total` will still warn correctly. No surprise here, but worth noting.

## File touch list

- `frontend/src/lib/invoiceValidation.ts` — extend `FieldKey`, rewrite the relationship checks, extend `invoicesEqual`.
- `frontend/src/components/casefile/ExtractionReceipt.tsx` — add two `Field` rows for Subtotal and Tax between line items and Total.

No other files touched.
