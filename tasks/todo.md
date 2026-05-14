# Fix: INV-9003 approved despite total mismatch (subtotal+tax ≠ total)

## Investigation Summary

- **Symptom:** INV-9003 (`subtotal=1000`, `tax=50`, `total=1500`) flows through as `approved` and is paid out at `$1500`. Correct total should be `1050`.
- **Expected behavior (per `tests/expected_outcomes.yaml:20`):** `approved` is acceptable, but it MUST be flagged with `total_math_error` so the approver weighs the warning rather than auto-approving.
- **Root cause:** `_check_total_math` in `backend/app/agents/validate.py:60-71` only compares summed line items against the stated `subtotal` (or `total` if subtotal missing). For INV-9003, line items × unit price = 1000 = stated subtotal, so the check passes. The check never verifies the **`subtotal + tax_amount ≈ total`** relationship, which is where the actual error lives.
- **Downstream consequence:** With `validation.issues == []`, the rule engine (`backend/app/rules/engine.py:60-66`) sets `auto_approve=true` (requires `not has_warn`), the approver LLM rubber-stamps with rationale "all gates green", and `pay` node settles `$1500`. Verified against the actual run at `backend/data/batch_results/runs/5a4ba5073ae24819ab917231c4a322c2.json`.

## Plan

- [x] **1. Add failing regression test.** In `backend/tests/test_validate_agent.py`, add `test_total_math_error_detects_subtotal_plus_tax_mismatch` using INV-9003's exact numbers (`subtotal=1000`, `tax_amount=50`, `total=1500`, line items: 4 × $250). Assert `"total_math_error"` is in the resulting issues. Run it first to confirm it fails against the current code.
- [x] **2. Extend `_check_total_math` in `backend/app/agents/validate.py`.** Add a second comparison: when both `subtotal` and `total` are present, verify `abs((subtotal + (tax_amount or 0)) - total) <= TOTAL_TOLERANCE`. On mismatch, emit a `total_math_error` issue with `severity="warn"` and a `detail` string like `f"subtotal {subtotal:.2f} + tax {tax_amount or 0:.2f} = {subtotal + (tax_amount or 0):.2f} vs stated total {total:.2f}"`. Keep the existing line-items-vs-subtotal check.
- [x] **3. Confirm the new test passes** and the existing `test_total_math_error_warns` still passes.
- [x] **4. Run the full validate-agent test file** plus `test_rules_engine.py` and `test_approve_agent.py` — 27/27 pass.
- [x] **5. Verify end-to-end behavior** by running `run_validate` + `evaluate_rules` directly against `data/invoices/invoice_9003.json`.

## Out of scope

- Changing the **outcome** of INV-9003. Spec says `approved` with the flag, not rejected. If the team later wants to reject math-error invoices, that's a rules-engine change (promote `total_math_error` to `block`, or add a rule), not a validator change.
- Refactoring `_check_total_math` into multiple functions. Adding ~5 lines inside the existing helper is the minimum-footprint fix.
- Re-checking historical run files. The fix is forward-looking; existing run records stay as-is.

## Follow-up: INV-9005 split-line attack + INV-9004 currency mismatch

### What changed

**`backend/app/graph/state.py`** — added `"currency_mismatch"` to `ValidationIssue.kind` literal.

**`backend/app/agents/validate.py`**:
- Added `EXPECTED_CURRENCY = "USD"` constant and `_check_currency()` helper. Emits `currency_mismatch` (severity=warn) when `inv.currency` is non-empty and not USD.
- Refactored `_check_line_items_against_inventory` to aggregate positive quantities per item before checking stock. Inventory lookups are now memoized per unique item (one lookup + one emission per item, instead of one per line). `unknown_item`, `out_of_stock`, and `qty_exceeds_stock` emit at most once per item. `price_mismatch` still fires per line so per-line price drift is preserved.

**`backend/tests/test_validate_agent.py`** — added:
- `test_qty_exceeds_stock_aggregates_across_split_lines` (INV-9005 shape: 49 × qty=1 WidgetA).
- `test_non_usd_currency_warns` and `test_usd_currency_does_not_warn`.

### Verification

- Full backend suite: 105 passed, 26 skipped (live LLM smokes).
- E2E:
  - INV-9005 → `[block] qty_exceeds_stock: requested 49 > stock 15` → `hard_blocks=[qty_exceeds_stock]` → approver forced to reject (matches spec).
  - INV-9004 → `[warn] currency_mismatch: invoice currency EUR != expected USD` → `scrutiny=True, auto_approve=False` (matches `needs_review` intent).
  - INV-9003 still produces `total_math_error` after the refactor.

## Review

**Files changed:**
- `backend/app/agents/validate.py` — extended `_check_total_math` with a second comparison (`subtotal + tax_amount ≈ total`). Refactored from a single return into an `issues` list so both checks can fire independently. Net +13 lines.
- `backend/tests/test_validate_agent.py` — added `test_total_math_error_detects_subtotal_plus_tax_mismatch` mirroring INV-9003's exact numbers.

**Verification:**
- TDD: new test failed first (`AssertionError: 'total_math_error' in set()`), then passed after the fix.
- Suite: 27/27 across `test_validate_agent.py`, `test_rules_engine.py`, `test_approve_agent.py`.
- E2E against the real fixture: validation now emits
  `[warn] total_math_error: subtotal 1000.00 + tax 50.00 = 1050.00 vs stated total 1500.00`
  Rule engine flips to `auto_approve=false`, `scrutiny=true`, `summary="validation_warn"`. The approver LLM will now see the warn in context and must weigh it per the `PROPOSE_SYSTEM` prompt instead of rubber-stamping.

**Spec alignment:**
- `tests/expected_outcomes.yaml` says `INV-9003: { outcome: approved, requires: [total_math_error] }`. The fix delivers the missing `total_math_error` flag. Final outcome on a live re-run will depend on the approver LLM's judgement under scrutiny, which is exactly the intended behavior — the math discrepancy is now surfaced rather than hidden.

**Not changed:**
- Severity stays `warn` (not `block`) — promoting to block would force-reject, contradicting the expected_outcomes spec.
- Rules engine and approver agent untouched — they already react correctly once the warn is present.

## Review — currency normalization (2026-05-13)

- Spec: `docs/superpowers/specs/2026-05-13-currency-normalization-design.md`
- Plan: `docs/superpowers/plans/2026-05-13-currency-normalization.md`
- Change: `_check_currency` now normalizes via `_CURRENCY_ALIASES` before comparison; `$`/`US$`/`USD$` resolve to `USD`, common non-USD symbols (`€`, `£`, `¥`) resolve to ISO codes in the warn detail.
- Commits: `556a648` (fix + tests), `cf1fdd2` (underscore-prefix the alias dict per code-quality review).
- Tests added in `backend/tests/test_validate_agent.py`:
  - `test_dollar_symbol_is_treated_as_usd` (regression for the reported `$ != USD` false positive)
  - `test_euro_symbol_is_treated_as_eur_and_warns`
  - `test_unknown_currency_code_warns_passthrough`
- Verified: `pytest tests/test_validate_agent.py` 33/33 green; full backend suite green pre-rename (152 passed, 26 skipped) and tests re-run after rename.

## 2026-05-13 — Grok client resilience

- Added retry + grok-3 fallback + typed exceptions in `GrokClient`
- API layer maps typed exceptions to clean strings (no "graph crashed:" prefix)
- Spec: `docs/superpowers/specs/2026-05-13-grok-resilience-design.md`
- Plan: `docs/superpowers/plans/2026-05-13-grok-resilience.md`
- 9 new unit tests in `test_grok_client.py`, 1 new integration test in `test_api.py`
- Post-review follow-up: `_run_investigate` in `approve.py` bypassed `structured_complete` via direct `run_tool_loop` call; same OpenAI → typed exception mapping added there with 2 new tests. Final suite: 164 passed, 26 skipped.

