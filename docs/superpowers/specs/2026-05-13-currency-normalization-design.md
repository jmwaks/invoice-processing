# Currency Normalization in `_check_currency`

**Status:** Approved, ready for implementation plan
**Date:** 2026-05-13
**Branch:** `feature/ui-improvement` (keep as-is per user instruction)

## Problem

`_check_currency` in `backend/app/agents/validate.py:75-83` emits false-positive
`currency_mismatch` warnings whenever an invoice's `currency` field is a symbol
rather than an ISO code. The check is a strict equality:

```python
if not inv.currency or inv.currency.upper() == EXPECTED_CURRENCY:  # "USD"
    return []
```

The ingest LLM is instructed to extract values verbatim from the source
(`backend/app/agents/ingest.py:28`, "Extract values verbatim from the source").
Invoices that print prices as `$1,234.56` produce `currency: "$"`, which the
validator then flags as a USD mismatch even though `$` *is* USD on those
invoices.

Evidence from `backend/data/batch_results/runs/`: many real runs store
`"currency": "$"` and `"currency": ""` alongside the expected `"USD"`/`"EUR"`.
EUR is a real mismatch; `$` and blank are not.

## Goal

`$`, `US$`, `USD$` (and blank) must not trigger `currency_mismatch`. Common
non-USD symbols (`€`, `£`, `¥`) and their aliases should normalize to their
ISO codes so the warn message reads cleanly. Unknown codes still warn,
passed through upper-cased.

## Non-Goals

- Backfilling stored runs in `backend/data/batch_results/runs/`.
- Modifying the ingest prompt or LLM output (we check currency
  deterministically, consistent with the existing
  [[llm_grok3_constraints]] / deterministic-claims pattern from commit
  `d114f9b`).
- Adding multi-currency payment support — the pipeline remains USD-only
  and warns on any genuinely non-USD invoice.
- Touching frontend currency display — the UI hardcodes USD formatting
  and does not read `inv.currency`.

## Behavior

| Input `inv.currency`            | Today                   | After fix                              |
| ------------------------------- | ----------------------- | -------------------------------------- |
| `"USD"`, `"usd"`, `None`, `""`  | no warn                 | no warn (unchanged)                    |
| `"$"`, `"US$"`, `"USD$"`        | warn (false positive)   | **no warn**                            |
| `"EUR"`, `"€"`, `"EUR€"`        | warn (with raw symbol)  | warn, detail uses normalized `EUR`     |
| `"GBP"`, `"£"`, `"JPY"`, `"¥"`  | warn (with raw symbol)  | warn, detail uses normalized code      |
| Any other (e.g. `"XYZ"`)        | warn                    | warn, detail uses upper-cased original |

## Design

Single file changed: `backend/app/agents/validate.py`.

Add a module-level alias table alongside the existing tolerances and a
private helper:

```python
EXPECTED_CURRENCY = "USD"
CURRENCY_ALIASES: dict[str, str] = {
    "$": "USD", "US$": "USD", "USD$": "USD",
    "€": "EUR", "EUR€": "EUR",
    "£": "GBP", "GBP£": "GBP",
    "¥": "JPY", "JPY¥": "JPY",
}

def _normalize_currency(raw: str) -> str:
    code = raw.strip().upper()
    return CURRENCY_ALIASES.get(code, code)
```

Rewrite `_check_currency` to call the helper once and use the normalized
code in the warn detail:

```python
def _check_currency(inv: InvoiceData) -> list[ValidationIssue]:
    if not inv.currency:
        return []
    normalized = _normalize_currency(inv.currency)
    if normalized == EXPECTED_CURRENCY:
        return []
    return [ValidationIssue(
        kind="currency_mismatch",
        detail=f"invoice currency {normalized} != expected {EXPECTED_CURRENCY} "
               f"(payment pipeline has no FX support)",
        severity="warn",
    )]
```

Notes:

- Alias keys are stored pre-upper-cased so `.strip().upper()` followed by
  a single dict lookup gives case-insensitive matching without a second
  pass.
- Helper is private (`_`-prefixed); no public API change.
- No change to `InvoiceData.currency`, no change to ingest, no change to
  the prompt. The fix lives where the symptom lives.

## Why Approach A (validator-only) over alternatives

- **Normalize at ingest boundary** (alternative B): would mutate
  LLM-extracted "verbatim" data and put currency rules in two places
  (ingest + validator) with no consumer benefit — nothing else reads
  `inv.currency`.
- **Tighten the prompt** (alternative C): currency would become a
  judgment claim by the LLM, which we have already chosen to check
  deterministically (cf. `llm_grok3_constraints` memory, commit
  `d114f9b`). Also does not fix any already-stored run.

## Tests

Three new tests added to `backend/tests/test_validate_agent.py`,
alongside existing `test_non_usd_currency_warns` and
`test_usd_currency_does_not_warn`:

1. **`test_dollar_symbol_is_treated_as_usd`** — `currency="$"`; assert
   `currency_mismatch` NOT in issue kinds. Regression test for the
   reported bug.
2. **`test_euro_symbol_is_treated_as_eur_and_warns`** — `currency="€"`;
   assert `currency_mismatch` is present, severity `"warn"`, and the
   `detail` string contains `"EUR"` (and does not contain the raw `€`).
   Locks normalize-then-warn behavior.
3. **`test_unknown_currency_code_warns_passthrough`** —
   `currency="XYZ"`; assert warn with `"XYZ"` in detail. Confirms
   unknown codes are not silently swallowed by the alias table.

Existing two currency tests remain unchanged and must still pass.

## Risk & Rollout

Minimal risk: one private function in one file, behind clear tests. No
schema migration, no API contract change, no frontend change. The
existing test suite must pass; the three new tests cover the changed
behavior.
