# Currency Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `_check_currency` from flagging `currency="$"` (and other USD aliases) as a `currency_mismatch`, while preserving warns for genuine non-USD invoices.

**Architecture:** Add a private alias table and `_normalize_currency` helper to `backend/app/agents/validate.py`. `_check_currency` normalizes once, compares against `EXPECTED_CURRENCY`, and uses the normalized code in the warn detail. No schema changes, no ingest changes, no frontend changes.

**Tech Stack:** Python 3 / pytest. Project uses a venv at the repo root (`backend/.venv` or root `.venv`; create if missing per CLAUDE.md). Tests live under `backend/tests/`.

**Reference Spec:** `docs/superpowers/specs/2026-05-13-currency-normalization-design.md`

---

## Pre-flight

- [ ] **Step 0: Confirm the venv and test runner**

```bash
cd /Users/mwakichako/repos/invoice-processing/backend
ls .venv 2>/dev/null || ls ../.venv 2>/dev/null || python3 -m venv .venv
source .venv/bin/activate 2>/dev/null || source ../.venv/bin/activate
python -c "import pytest; print(pytest.__version__)"
```

Expected: pytest version prints (any 7.x/8.x). If venv was just created, run `pip install -e .` from `backend/` first.

- [ ] **Step 0b: Baseline-green the existing validator tests**

```bash
cd /Users/mwakichako/repos/invoice-processing/backend
pytest tests/test_validate_agent.py -v
```

Expected: all tests pass. If any fail before we change anything, stop and report — do not proceed.

---

## Task 1: Regression test — `$` must not trigger `currency_mismatch`

**Files:**
- Test: `backend/tests/test_validate_agent.py` (add new test function)

- [ ] **Step 1: Read the existing currency tests for context**

Open `backend/tests/test_validate_agent.py`. Locate the existing tests:

- `test_non_usd_currency_warns` (around line 177)
- `test_usd_currency_does_not_warn` (around line 192)

The new test goes immediately after `test_usd_currency_does_not_warn`. Reuse the same `_seeded`, `_state`, and `_inv` helpers from the top of the file — do not invent new fixtures.

- [ ] **Step 2: Write the failing regression test**

Insert this function right after `test_usd_currency_does_not_warn`:

```python
def test_dollar_symbol_is_treated_as_usd(tmp_path: Path):
    # Regression: ingest extracts currency verbatim, so invoices that print
    # "$1,234.56" produce currency="$". The validator must treat "$" as USD
    # and NOT raise currency_mismatch.
    db = _seeded(tmp_path)
    state = _state(_inv(
        line_items=[LineItem(item="WidgetA", quantity=1, unit_price=250.0)],
        total=250.0, currency="$",
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    kinds = {i.kind for i in out.validation.issues}
    assert "currency_mismatch" not in kinds
```

- [ ] **Step 3: Run the test and verify it fails for the right reason**

```bash
cd /Users/mwakichako/repos/invoice-processing/backend
pytest tests/test_validate_agent.py::test_dollar_symbol_is_treated_as_usd -v
```

Expected: FAIL with an assertion that `"currency_mismatch"` IS in `kinds`. That confirms today's bug. If it fails for any other reason (import error, fixture error), stop and fix the test before proceeding.

- [ ] **Step 4: Do NOT commit yet.** This test stays red until Task 3 lands.

---

## Task 2: Two more regression tests — Euro symbol normalization and unknown-code passthrough

**Files:**
- Test: `backend/tests/test_validate_agent.py` (add two more test functions)

- [ ] **Step 1: Add the Euro-symbol test**

Insert immediately after `test_dollar_symbol_is_treated_as_usd`:

```python
def test_euro_symbol_is_treated_as_eur_and_warns(tmp_path: Path):
    # The "€" symbol must normalize to "EUR" so the warn detail is readable.
    # The warn itself must still fire (pipeline has no FX support).
    db = _seeded(tmp_path)
    state = _state(_inv(
        line_items=[LineItem(item="WidgetA", quantity=4, unit_price=225.0)],
        total=900.0, currency="€",
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    by_kind = {i.kind: i for i in out.validation.issues}
    assert "currency_mismatch" in by_kind
    assert by_kind["currency_mismatch"].severity == "warn"
    assert "EUR" in by_kind["currency_mismatch"].detail
    assert "€" not in by_kind["currency_mismatch"].detail
```

- [ ] **Step 2: Add the unknown-code passthrough test**

Insert immediately after the previous test:

```python
def test_unknown_currency_code_warns_passthrough(tmp_path: Path):
    # Codes not in the alias table must still warn, with the upper-cased
    # original code appearing in the detail (no silent swallowing).
    db = _seeded(tmp_path)
    state = _state(_inv(
        line_items=[LineItem(item="WidgetA", quantity=1, unit_price=250.0)],
        total=250.0, currency="xyz",
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    by_kind = {i.kind: i for i in out.validation.issues}
    assert "currency_mismatch" in by_kind
    assert by_kind["currency_mismatch"].severity == "warn"
    assert "XYZ" in by_kind["currency_mismatch"].detail
```

- [ ] **Step 3: Run both new tests and confirm they fail**

```bash
cd /Users/mwakichako/repos/invoice-processing/backend
pytest tests/test_validate_agent.py::test_euro_symbol_is_treated_as_eur_and_warns \
       tests/test_validate_agent.py::test_unknown_currency_code_warns_passthrough -v
```

Expected:

- `test_euro_symbol_is_treated_as_eur_and_warns` FAILS because the detail today contains `"€"` (the raw symbol), not `"EUR"`. The assertion `"EUR" in detail` fails first.
- `test_unknown_currency_code_warns_passthrough` should PASS even today — `"xyz".upper() == "XYZ"` already lands in the detail via the existing f-string. That's fine; it locks behavior so the alias-table change cannot regress it.

If `test_unknown_currency_code_warns_passthrough` fails today, stop and inspect — that means the current `detail` formatting differs from what we expect.

- [ ] **Step 4: Do NOT commit yet.** Tests will go in alongside the implementation in Task 3's commit.

---

## Task 3: Implement `CURRENCY_ALIASES` + `_normalize_currency` and rewrite `_check_currency`

**Files:**
- Modify: `backend/app/agents/validate.py` (constants block around line 20-22, and `_check_currency` at lines 75-83)

- [ ] **Step 1: Add the alias table and helper**

Open `backend/app/agents/validate.py`. Find this block (around lines 20-22):

```python
PRICE_TOLERANCE = 0.10  # 10%
TOTAL_TOLERANCE = 1.00  # $1
EXPECTED_CURRENCY = "USD"  # payment pipeline assumes USD; flag others for review
```

Replace it with:

```python
PRICE_TOLERANCE = 0.10  # 10%
TOTAL_TOLERANCE = 1.00  # $1
EXPECTED_CURRENCY = "USD"  # payment pipeline assumes USD; flag others for review

# Symbol/alias normalization. Keys are pre-upper-cased so a single
# .strip().upper() lookup is case-insensitive. The LLM extracts currency
# verbatim from the source, so "$" is a legitimate USD marker — not a
# mismatch. Non-USD aliases (€, £, ¥) normalize to ISO codes so the
# warn detail is readable, but they still trigger currency_mismatch.
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

- [ ] **Step 2: Rewrite `_check_currency`**

Find the current implementation (around lines 75-83):

```python
def _check_currency(inv: InvoiceData) -> list[ValidationIssue]:
    if not inv.currency or inv.currency.upper() == EXPECTED_CURRENCY:
        return []
    return [ValidationIssue(
        kind="currency_mismatch",
        detail=f"invoice currency {inv.currency} != expected {EXPECTED_CURRENCY} "
               f"(payment pipeline has no FX support)",
        severity="warn",
    )]
```

Replace it with:

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

- [ ] **Step 3: Run the three new tests and verify they pass**

```bash
cd /Users/mwakichako/repos/invoice-processing/backend
pytest tests/test_validate_agent.py::test_dollar_symbol_is_treated_as_usd \
       tests/test_validate_agent.py::test_euro_symbol_is_treated_as_eur_and_warns \
       tests/test_validate_agent.py::test_unknown_currency_code_warns_passthrough -v
```

Expected: all three PASS.

- [ ] **Step 4: Run the whole validator test file to confirm no regressions**

```bash
cd /Users/mwakichako/repos/invoice-processing/backend
pytest tests/test_validate_agent.py -v
```

Expected: every test passes, including the pre-existing `test_non_usd_currency_warns` and `test_usd_currency_does_not_warn`.

If `test_non_usd_currency_warns` regresses, the most likely cause is a typo in the alias table that maps `"EUR"` somewhere it shouldn't — re-check Step 1.

- [ ] **Step 5: Run the full backend test suite to catch unrelated regressions**

```bash
cd /Users/mwakichako/repos/invoice-processing/backend
pytest -q
```

Expected: full suite passes. No other test should depend on `_check_currency` returning a warn for `"$"`, but run the suite as a guardrail.

- [ ] **Step 6: Commit**

```bash
cd /Users/mwakichako/repos/invoice-processing
git add backend/app/agents/validate.py backend/tests/test_validate_agent.py
git commit -m "$(cat <<'EOF'
fix(validate): normalize currency aliases before mismatch check

The validator was firing currency_mismatch on currency="$" because the
ingest LLM extracts the currency field verbatim from the source. Add a
private CURRENCY_ALIASES table mapping $/US$/USD$ -> USD (and €/£/¥ to
their ISO codes for cleaner warn details). Three regression tests cover
the $ false-positive, € normalization, and unknown-code passthrough.

Spec: docs/superpowers/specs/2026-05-13-currency-normalization-design.md
EOF
)"
```

---

## Task 4: Verification log

**Files:**
- Modify: `tasks/todo.md` (append a review section per CLAUDE.md workflow item 1)

- [ ] **Step 1: Append a review block to `tasks/todo.md`**

Open `tasks/todo.md` and append at the bottom:

```markdown
## Review — currency normalization (2026-05-13)

- Spec: `docs/superpowers/specs/2026-05-13-currency-normalization-design.md`
- Plan: `docs/superpowers/plans/2026-05-13-currency-normalization.md`
- Change: `_check_currency` now normalizes via `CURRENCY_ALIASES` before comparison.
- Tests added:
  - `test_dollar_symbol_is_treated_as_usd` (regression for the reported bug)
  - `test_euro_symbol_is_treated_as_eur_and_warns`
  - `test_unknown_currency_code_warns_passthrough`
- Verified: full `pytest -q` from `backend/` passes locally.
```

- [ ] **Step 2: Commit**

```bash
cd /Users/mwakichako/repos/invoice-processing
git add tasks/todo.md
git commit -m "docs(tasks): log currency normalization fix"
```

---

## Done criteria

- `pytest -q` from `backend/` is green.
- `_check_currency` returns `[]` for `currency in {"$", "US$", "USD$", "usd", "USD", "", None}`.
- `_check_currency` returns a single `currency_mismatch` warn whose `detail` contains the normalized code (not the raw symbol) for `"€"`, `"£"`, `"¥"`, `"EUR"`, etc.
- Two commits on `feature/ui-improvement`: the fix + tests, and the todo log.
- Branch stays as `feature/ui-improvement` per user instruction.
