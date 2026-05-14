# Extraction UI: Subtotal & Tax Fields Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface `subtotal` and `tax_amount` as editable fields in the Extraction panel, and rewrite frontend validation to match the backend's relationship checks (including null-subtotal fallback and `$1` tolerance).

**Architecture:** Frontend-only change. All logic lives in two files: `frontend/src/lib/invoiceValidation.ts` (parsing helper, tolerance constant, `FieldKey` union, `validateDraft`, `invoicesEqual`) and `frontend/src/components/casefile/ExtractionReceipt.tsx` (UI rows + numeric input parsing). Backend already correct; no API or model changes.

**Tech Stack:** TypeScript, React (Vite + Tailwind). No frontend test runner is configured — verification is `npm run build` (type-check + bundle) plus manual UI inspection per the spec's scenarios.

**Spec:** `docs/superpowers/specs/2026-05-13-extraction-tax-fields-design.md`

---

## File Touch List

- **Modify** `frontend/src/lib/invoiceValidation.ts` — add `TOTAL_TOLERANCE` constant + `parseNumber` helper, extend `FieldKey`, rewrite `validateDraft` (split numeric sanity, three relationship checks), extend `invoicesEqual`.
- **Modify** `frontend/src/components/casefile/ExtractionReceipt.tsx` — add Subtotal/Tax rows wrapped in a `<dl>` with Total, swap inline `parseFloat` calls for `parseNumber`, add `placeholder="0.00"` to numeric inputs.

No other files touched.

---

## Task 1: Add `TOTAL_TOLERANCE` constant and `parseNumber` helper

**Files:**
- Modify: `frontend/src/lib/invoiceValidation.ts` (top of file)

- [ ] **Step 1: Add the constant and helper near the top of the file**

Open `frontend/src/lib/invoiceValidation.ts`. Below the existing `const DATE_RE` line (currently around line 18), add:

```ts
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
```

- [ ] **Step 2: Verify the build still passes**

Run:
```bash
cd frontend && npm run build
```
Expected: build succeeds with no errors. The helper is exported but not yet used by other files — that is fine.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/invoiceValidation.ts
git commit -m "feat(validation): add TOTAL_TOLERANCE constant and parseNumber helper"
```

---

## Task 2: Extend `FieldKey` and rewrite `validateDraft`

**Files:**
- Modify: `frontend/src/lib/invoiceValidation.ts` (the `FieldKey` type and the `validateDraft` function)

- [ ] **Step 1: Extend the `FieldKey` union**

Replace the existing `FieldKey` type (currently lines 3–11) with:

```ts
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
```

- [ ] **Step 2: Replace the `validateDraft` function body**

Replace the entire `validateDraft` function (currently lines 20–56) with the implementation below. This:

- Splits numeric sanity for `total`, `subtotal`, `tax_amount`, and `unit_price` into NaN vs negative branches with distinct messages.
- Removes the old single `sum(line_items)` vs `total` warning.
- Adds the three relationship checks (line items vs subtotal, subtotal+tax vs total, null-subtotal fallback) using `TOTAL_TOLERANCE`.

```ts
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
```

- [ ] **Step 3: Verify the build passes**

Run:
```bash
cd frontend && npm run build
```
Expected: build succeeds. `ExtractionReceipt.tsx` already passes warnings through the generic `FieldKey`-indexed errors/warnings record, so the new `subtotal`/`tax_amount` keys will round-trip even before the UI shows them.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/invoiceValidation.ts
git commit -m "feat(validation): split numeric sanity and add three relationship checks

Matches backend validate.py model: subtotal+tax≈total, with fallback to
sum(line_items)≈total when subtotal is null. Uses \$1 tolerance to
match backend TOTAL_TOLERANCE."
```

---

## Task 3: Extend `invoicesEqual` with `subtotal` and `tax_amount`

**Files:**
- Modify: `frontend/src/lib/invoiceValidation.ts` (the `invoicesEqual` function)

- [ ] **Step 1: Update `invoicesEqual`**

Locate the `invoicesEqual` function (currently around lines 62–77). After the existing `if (a.total !== b.total) return false;` line, add two new comparisons:

```ts
  if (a.subtotal !== b.subtotal) return false;
  if (a.tax_amount !== b.tax_amount) return false;
```

The full function after the edit should read:

```ts
export function invoicesEqual(a: InvoiceData, b: InvoiceData): boolean {
  if (a.invoice_number !== b.invoice_number) return false;
  if (a.vendor !== b.vendor) return false;
  if (a.date !== b.date) return false;
  if (a.due_date !== b.due_date) return false;
  if (a.total !== b.total) return false;
  if (a.subtotal !== b.subtotal) return false;
  if (a.tax_amount !== b.tax_amount) return false;
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
```

Per spec Non-Goals: `currency`, `payment_terms`, and `notes` are deliberately not compared (no UI control mutates them).

- [ ] **Step 2: Verify the build passes**

Run:
```bash
cd frontend && npm run build
```
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/invoiceValidation.ts
git commit -m "fix(validation): include subtotal and tax_amount in invoicesEqual

Ensures the Save & retry dirty check enables when only those fields
change."
```

---

## Task 4: Swap `parseFloat` calls for `parseNumber` in the receipt; add placeholder to Total

**Files:**
- Modify: `frontend/src/components/casefile/ExtractionReceipt.tsx`

- [ ] **Step 1: Add the `parseNumber` import**

At the top of the file, locate the existing import from `../../lib/invoiceValidation.ts` (currently line 4). Change it to also import `parseNumber`:

Old:
```ts
import { hasErrors, invoicesEqual, validateDraft, type FieldKey } from "../../lib/invoiceValidation.ts";
```

New:
```ts
import { hasErrors, invoicesEqual, parseNumber, validateDraft, type FieldKey } from "../../lib/invoiceValidation.ts";
```

- [ ] **Step 2: Replace `unit_price` onChange parsing**

Find the line item `unit_price` input (currently around line 102–108). Replace its `onChange` body:

Old:
```tsx
<FieldInput
  value={it.unit_price === null ? "" : String(it.unit_price)}
  onChange={(v) => setItemField(i, "unit_price", v === "" ? null : parseFloat(v))}
  placeholder="0.00"
  error={errors[`items.${i}.unit_price` as FieldKey]}
  mono
/>
```

New:
```tsx
<FieldInput
  value={it.unit_price === null ? "" : String(it.unit_price)}
  onChange={(v) => setItemField(i, "unit_price", parseNumber(v))}
  placeholder="0.00"
  error={errors[`items.${i}.unit_price` as FieldKey]}
  mono
/>
```

- [ ] **Step 3: Replace `total` onChange parsing and add placeholder**

Find the `total` `Field` (currently around lines 114–121). Replace it:

Old:
```tsx
<Field
  label="Total"
  value={draft.total === null ? "" : String(draft.total)}
  onChange={(v) => setField("total", v === "" ? null : parseFloat(v))}
  error={errors.total}
  warning={warnings.total}
  mono
/>
```

New:
```tsx
<Field
  label="Total"
  value={draft.total === null ? "" : String(draft.total)}
  onChange={(v) => setField("total", parseNumber(v))}
  placeholder="0.00"
  error={errors.total}
  warning={warnings.total}
  mono
/>
```

(The `Field` component already accepts `placeholder` and forwards it to `FieldInput` — no component change needed.)

- [ ] **Step 4: Verify the build passes**

Run:
```bash
cd frontend && npm run build
```
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/casefile/ExtractionReceipt.tsx
git commit -m "fix(extraction-ui): use parseNumber for numeric inputs and add Total placeholder

parseNumber strips thousands-separator commas so '1,250.00' parses
correctly. Placeholder matches the unit_price field."
```

---

## Task 5: Add Subtotal and Tax rows; wrap Subtotal/Tax/Total in a `<dl>`

**Files:**
- Modify: `frontend/src/components/casefile/ExtractionReceipt.tsx`

- [ ] **Step 1: Replace the Total section with a `<dl>` containing Subtotal, Tax, and Total**

Find the block that renders the Total field (currently a `<div className="mt-5">...</div>` wrapper around lines 113–122, after Step-3 edits). Replace the entire wrapper `<div>` with:

Old:
```tsx
<div className="mt-5">
  <Field
    label="Total"
    value={draft.total === null ? "" : String(draft.total)}
    onChange={(v) => setField("total", parseNumber(v))}
    placeholder="0.00"
    error={errors.total}
    warning={warnings.total}
    mono
  />
</div>
```

New:
```tsx
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
```

This:
- Wraps all three numeric rows in a single `<dl>`, fixing the orphan `<dt>`/`<dd>` HTML validity issue.
- Adds Subtotal and Tax rows above Total, using the existing `Field` component.
- Inherits `space-y-3` so vertical spacing matches the top section's `<dl>`.
- Keeps the `mt-5` margin (same as the previous wrapper `<div>`).

- [ ] **Step 2: Verify the build passes**

Run:
```bash
cd frontend && npm run build
```
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/casefile/ExtractionReceipt.tsx
git commit -m "feat(extraction-ui): add editable Subtotal and Tax fields

Wraps Subtotal/Tax/Total in a <dl> to fix orphan <dt>/<dd> children.
Both new fields reuse the existing Field component."
```

---

## Task 6: Manual UI verification

**Files:** No code changes. This task runs the spec's verification scenarios in a live browser.

- [ ] **Step 1: Start the dev server**

The project has a backend that serves the data and a Vite frontend. Start whichever the project uses for full-stack dev. From the project root:

```bash
# Backend (in one terminal)
cd backend && make dev
# OR check the Makefile for the right target:
cat backend/Makefile

# Frontend (in another terminal)
cd frontend && npm run dev
```

Open the URL Vite reports (typically `http://localhost:5173`).

- [ ] **Step 2: Find or create the INV-1004 case file**

Navigate to the runs list. Find the run for `INV-1004` (Precision Parts Ltd., subtotal 1750, tax 140, total 1890). If it doesn't exist, upload the sample invoice or use `POST /api/runs/sample/<filename>` per the existing API.

- [ ] **Step 3: Run the 12 spec verification scenarios**

For each scenario, confirm the expected outcome. If any fails, stop and investigate before continuing.

1. **Happy path:** Subtotal=1750, Tax=140, Total=1890 render. No warnings on any field.
2. **Subtotal mismatch:** Edit WidgetA quantity 3 → 4. Warning on **Subtotal**: "doesn't match item total". Total may or may not warn depending on whether subtotal+tax still tracks total.
3. **Total mismatch:** Reset, then edit Tax 140 → 141. Warning on **Total**: "doesn't match subtotal + tax".
4. **Null subtotal, total set:** Reset, then clear Subtotal. Warning on **Total**: "doesn't match item total" (fallback check fires because 1750 ≠ 1890).
5. **Null tax with subtotal set:** Reset, then clear Tax. Warning on **Total**: "doesn't match subtotal + tax" (tax treated as 0; 1750 ≠ 1890).
6. **Both subtotal and tax null:** Reset, clear both. Warning on **Total**: "doesn't match item total" (fallback runs; 1750 ≠ 1890).
7. **Negative input:** Reset, type `-5` into Subtotal. Error on **Subtotal**: "must be ≥ 0". No relationship warnings on subtotal.
8. **Non-numeric input:** Reset, type `abc` into Tax. Error on **Tax**: "must be a number". No relationship warnings on total.
9. **Comma input:** Reset, type `1,750` into Subtotal. Field accepts; parses as 1750; no warnings (matches line item sum).
10. **Tolerance ($1):** Set Subtotal to `1749.50`. No warning. Change to `1748.50`. Warning fires on Subtotal.
11. **Dirty-state / Save:** Reset to clean state, then edit only Tax (e.g., 140 → 145). "Save & retry" button enables. Click it; verify a new run is created and the navigation goes to `/runs/<new_run_id>`.
12. **HTML validity:** Open browser devtools → Elements. Inspect the Subtotal/Tax/Total section. Confirm it is wrapped in a `<dl class="mt-5 space-y-3">` with three `<dt>`/`<dd>` pairs inside.

- [ ] **Step 4: If any scenario failed, fix and recommit**

Investigate the failure, edit the relevant file(s), re-run the affected scenarios, and commit with a clear message describing the fix. Otherwise no commit needed for this task.

- [ ] **Step 5: Final build check**

```bash
cd frontend && npm run build
```
Expected: success.

---

## Self-Review (already performed by author)

Spec coverage:
- Subtotal/Tax editable rows: Task 5.
- Layout (between line items and total) and `<dl>` wrap: Task 5.
- `TOTAL_TOLERANCE = 1.0` constant: Task 1.
- `parseNumber` helper with comma stripping: Task 1.
- `FieldKey` extension: Task 2.
- Field-level numeric sanity split (`must be a number` vs `must be ≥ 0`) for subtotal/tax/total/unit_price: Task 2.
- Three relationship checks (incl. null-subtotal fallback): Task 2.
- `invoicesEqual` extension (subtotal/tax only): Task 3.
- All four numeric inputs use `parseNumber`: Tasks 4 (total, unit_price) and 5 (subtotal, tax).
- `placeholder="0.00"` on subtotal, tax, total: Tasks 4 and 5.
- Verification scenarios 1–12 from spec: Task 6.

Placeholder scan: none ("TBD", "TODO", "similar to" — all absent).

Type/name consistency: `parseNumber`, `TOTAL_TOLERANCE`, `FieldKey`, `validateDraft`, `invoicesEqual` all spelled consistently across tasks. Field keys (`subtotal`, `tax_amount`) match the `InvoiceData` model exactly. Warning strings (`"doesn't match item total"`, `"doesn't match subtotal + tax"`) and error strings (`"must be a number"`, `"must be ≥ 0"`) are consistent between Task 2 and the Task 6 verification scenarios.
