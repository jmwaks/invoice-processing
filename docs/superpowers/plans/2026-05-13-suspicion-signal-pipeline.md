# Suspicion Signal Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reassign suspicion signal kinds so objective claims (future-dated invoices, round-number heuristic) leave the LLM emission path and live where they can be verified — `validate.py` for derivable claims, removed entirely where redundant. Enforce the new contract in the pydantic schema so prompt drift cannot silently reintroduce the bug surfaced by INV-1006.

**Architecture:** Two-pipeline split preserved (`ValidationIssue` deterministic / `SuspicionSignal` LLM textual), with kind-by-kind ownership rebalanced. New `future_date` ValidationIssue, computed against an injected `today` for testability. `SuspicionSignal.kind` Literal narrowed to remove `impossible_date` and `round_number` — pydantic rejects any LLM response that emits them. Ingest prompt updated to match.

**Tech Stack:** Python 3, pydantic v2, pytest, langgraph, OpenAI SDK (Grok-3 backend via x.ai endpoint).

**Spec:** `docs/superpowers/specs/2026-05-13-suspicion-signal-pipeline-design.md`

---

## File Structure

**Modified:**
- `backend/app/graph/state.py` — `SuspicionSignal.kind` Literal narrowed; `ValidationIssue.kind` Literal gains `"future_date"`.
- `backend/app/agents/validate.py` — new `_check_future_date` helper; `run_validate` gains a `today` kwarg.
- `backend/app/agents/ingest.py` — `SYSTEM_PROMPT` updated to remove banned-kind bullets and add deterministic-claims guardrail.

**Test files modified/added:**
- `backend/tests/test_state_models.py` — schema-enforcement tests for banned/added kinds.
- `backend/tests/test_validate_agent.py` — `future_date` positive + negative tests with injected `today`.
- `backend/tests/test_ingest_agent.py` — prompt-drift defense test (SDK-level stub).
- `backend/tests/test_rules_engine.py` — regression test for the INV-1006 cascade (past date + round total → no scrutiny).

**Untouched (verify in Task 8):**
- `backend/app/agents/approve.py`, `backend/app/rules/engine.py`, `backend/app/rules/rules.yaml`, `backend/app/graph/builder.py`. The new `future_date` kind rides existing severity machinery.

---

## Task 1: Add schema-enforcement tests (failing) and lock the new SuspicionSignal Literal

This task lands the schema change. Tests assert the final shape; the implementation is the Literal edit in `state.py`.

**Files:**
- Modify: `backend/app/graph/state.py:30-42` (`SuspicionSignal.kind` Literal)
- Modify: `backend/app/graph/state.py:45-63` (`ValidationIssue.kind` Literal)
- Test: `backend/tests/test_state_models.py`

- [ ] **Step 1: Inspect existing `test_state_models.py` to find a good insertion point and confirm no existing tests rely on the kinds we're about to remove.**

Run:
```bash
grep -nE "impossible_date|round_number|future_date" /Users/mwakichako/repos/invoice-processing/backend/tests/test_state_models.py
```
Expected: no matches. If any match, list them — they need to be revised in this task before adding new tests.

- [ ] **Step 2: Write failing tests in `backend/tests/test_state_models.py`.**

Append at the end of the file:

```python
import pytest
from pydantic import ValidationError

from app.graph.state import SuspicionSignal, ValidationIssue


def test_suspicion_signal_rejects_impossible_date_kind():
    """Banned kind: impossible_date is now owned by validate.py as `future_date`."""
    with pytest.raises(ValidationError):
        SuspicionSignal(kind="impossible_date", detail="x", severity="high")


def test_suspicion_signal_rejects_round_number_kind():
    """Banned kind: round_number is dropped; total_math_error covers the real risk."""
    with pytest.raises(ValidationError):
        SuspicionSignal(kind="round_number", detail="x", severity="medium")


def test_suspicion_signal_still_accepts_textual_kinds():
    """Remaining LLM-emitted kinds must still construct cleanly."""
    for kind in (
        "urgent_language",
        "unknown_vendor_pattern",
        "wire_transfer_demand",
        "homoglyph_corruption",
        "other",
    ):
        SuspicionSignal(kind=kind, detail="x", severity="low")  # must not raise


def test_validation_issue_accepts_future_date_kind():
    """New kind: future_date — owned by validate.py."""
    ValidationIssue(kind="future_date", detail="x", severity="warn")  # must not raise
```

Note: `pytest` and `ValidationError` may already be imported at the top of the file. If so, do **not** duplicate the imports — move them to the existing import block.

- [ ] **Step 3: Run the new tests and confirm they fail.**

Run:
```bash
cd /Users/mwakichako/repos/invoice-processing/backend && pytest tests/test_state_models.py -v -k "suspicion_signal or validation_issue_accepts_future"
```
Expected: 4 failures. The two `rejects_*` tests fail because the kinds are still accepted; `accepts_future_date_kind` fails because `future_date` is not yet a valid kind.

- [ ] **Step 4: Modify `state.py` — narrow `SuspicionSignal.kind` and add `future_date` to `ValidationIssue.kind`.**

In `backend/app/graph/state.py`, find the `SuspicionSignal` class around line 30:

```python
class SuspicionSignal(BaseModel):
    kind: Literal[
        "urgent_language",
        "impossible_date",
        "round_number",
        "unknown_vendor_pattern",
        "wire_transfer_demand",
        "homoglyph_corruption",
        "other",
    ]
```

Replace the Literal with:

```python
class SuspicionSignal(BaseModel):
    kind: Literal[
        "urgent_language",
        "unknown_vendor_pattern",
        "wire_transfer_demand",
        "homoglyph_corruption",
        "other",
    ]
```

In the `ValidationIssue` class around line 45, find:

```python
class ValidationIssue(BaseModel):
    kind: Literal[
        "unknown_item",
        "out_of_stock",
        "qty_exceeds_stock",
        "price_mismatch",
        "unknown_vendor",
        "negative_qty",
        "missing_vendor",
        "missing_total",
        "no_line_items",
        "total_math_error",
        "past_due_date",
        "currency_mismatch",
        "duplicate_invoice",
    ]
```

Add `"future_date"` to the Literal (placed next to `past_due_date` for grouping):

```python
class ValidationIssue(BaseModel):
    kind: Literal[
        "unknown_item",
        "out_of_stock",
        "qty_exceeds_stock",
        "price_mismatch",
        "unknown_vendor",
        "negative_qty",
        "missing_vendor",
        "missing_total",
        "no_line_items",
        "total_math_error",
        "past_due_date",
        "future_date",
        "currency_mismatch",
        "duplicate_invoice",
    ]
```

- [ ] **Step 5: Run the new tests and confirm they pass.**

Run:
```bash
cd /Users/mwakichako/repos/invoice-processing/backend && pytest tests/test_state_models.py -v -k "suspicion_signal or validation_issue_accepts_future"
```
Expected: 4 passed.

- [ ] **Step 6: Run the full test suite to catch any callers that constructed the now-banned kinds.**

Run:
```bash
cd /Users/mwakichako/repos/invoice-processing/backend && pytest -v
```
Expected: all tests pass. If any test fails with a `ValidationError` for `impossible_date` or `round_number`, it's a test that asserted the LLM emitted one of those kinds. Such a test was asserting LLM-stub behavior — rewrite it to use one of the remaining allowed kinds (e.g., swap `impossible_date` → `other`) since the test's actual concern is signal-handling plumbing, not the specific kind. Document any such edits in the commit message.

- [ ] **Step 7: Commit.**

```bash
cd /Users/mwakichako/repos/invoice-processing && git add backend/app/graph/state.py backend/tests/test_state_models.py
git commit -m "feat(state): narrow SuspicionSignal kind; add ValidationIssue future_date"
```

---

## Task 2: Add `_check_future_date` helper to `validate.py`

Pure unit-level helper. Takes `inv` and `today`, returns `[ValidationIssue]`. No DB, no emitter. TDD'd in isolation.

**Files:**
- Modify: `backend/app/agents/validate.py` (add private helper)
- Test: `backend/tests/test_validate_agent.py`

- [ ] **Step 1: Write failing tests in `backend/tests/test_validate_agent.py`.**

Append at the end of the file:

```python
import datetime as dt

from app.agents.validate import _check_future_date


def test_check_future_date_empty_when_date_none():
    inv = _inv(date=None)
    assert _check_future_date(inv, dt.date(2026, 5, 13)) == []


def test_check_future_date_empty_when_date_equals_today():
    inv = _inv(date=dt.date(2026, 5, 13))
    assert _check_future_date(inv, dt.date(2026, 5, 13)) == []


def test_check_future_date_empty_when_date_in_past():
    """The INV-1006 case: invoice date is in the past relative to today."""
    inv = _inv(date=dt.date(2026, 1, 25))
    assert _check_future_date(inv, dt.date(2026, 5, 13)) == []


def test_check_future_date_emits_warn_when_date_in_future():
    inv = _inv(date=dt.date(2026, 5, 23))
    issues = _check_future_date(inv, dt.date(2026, 5, 13))
    assert len(issues) == 1
    issue = issues[0]
    assert issue.kind == "future_date"
    assert issue.severity == "warn"
    assert "2026-05-23" in issue.detail
    assert "2026-05-13" in issue.detail
    assert "10" in issue.detail  # day count
```

Note: `_inv` is the existing fixture helper at the top of `test_validate_agent.py`. `dt` may already be imported — if so, don't duplicate.

- [ ] **Step 2: Run the new tests and confirm they fail.**

Run:
```bash
cd /Users/mwakichako/repos/invoice-processing/backend && pytest tests/test_validate_agent.py -v -k "check_future_date"
```
Expected: 4 failures with `ImportError` or `AttributeError` because `_check_future_date` does not yet exist.

- [ ] **Step 3: Implement `_check_future_date` in `backend/app/agents/validate.py`.**

Find the existing `_check_dates` helper around line 55. Add the new helper directly after it:

```python
def _check_future_date(inv: InvoiceData, today: dt.date) -> list[ValidationIssue]:
    if inv.date is None or inv.date <= today:
        return []
    days = (inv.date - today).days
    return [ValidationIssue(
        kind="future_date",
        detail=f"invoice date {inv.date} is {days} day(s) in the future (today is {today})",
        severity="warn",
    )]
```

Do **not** wire it into `run_validate` yet — Task 3 does that.

- [ ] **Step 4: Run the tests and confirm they pass.**

Run:
```bash
cd /Users/mwakichako/repos/invoice-processing/backend && pytest tests/test_validate_agent.py -v -k "check_future_date"
```
Expected: 4 passed.

- [ ] **Step 5: Commit.**

```bash
cd /Users/mwakichako/repos/invoice-processing && git add backend/app/agents/validate.py backend/tests/test_validate_agent.py
git commit -m "feat(validate): add deterministic _check_future_date helper"
```

---

## Task 3: Wire `today` through `run_validate` and call `_check_future_date`

Add `today` kwarg to `run_validate`, pass it into the new helper, default to `dt.date.today()` at the top of the function (single point of wall-clock contact).

**Files:**
- Modify: `backend/app/agents/validate.py:244` (`run_validate` signature) and around line 256 (where `_check_dates` is called).
- Test: `backend/tests/test_validate_agent.py`

- [ ] **Step 1: Write failing integration tests in `backend/tests/test_validate_agent.py`.**

Append at the end of the file:

```python
def test_run_validate_emits_future_date_issue_when_date_after_today(tmp_path: Path):
    """Positive: invoice date 10 days in the future surfaces as a warn-level ValidationIssue."""
    db = _seeded(tmp_path)
    state = _state(_inv(
        date=dt.date(2026, 5, 23),
        line_items=[LineItem(item="WidgetA", quantity=1, unit_price=250.0)],
        total=250.0,
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter, today=dt.date(2026, 5, 13))
    future_date_issues = [i for i in out.validation.issues if i.kind == "future_date"]
    assert len(future_date_issues) == 1
    assert future_date_issues[0].severity == "warn"


def test_run_validate_no_future_date_issue_when_date_in_past(tmp_path: Path):
    """Regression for INV-1006: a past invoice date must NOT trigger a future_date issue."""
    db = _seeded(tmp_path)
    state = _state(_inv(
        invoice_number="INV-1006",
        vendor="Acme Industrial Supplies",
        date=dt.date(2026, 1, 25),
        line_items=[
            LineItem(item="WidgetA", quantity=5, unit_price=250.0),
            LineItem(item="WidgetB", quantity=3, unit_price=500.0),
        ],
        subtotal=2750.0, tax_amount=0.0, total=2750.0,
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter, today=dt.date(2026, 5, 13))
    assert not any(i.kind == "future_date" for i in out.validation.issues)
```

- [ ] **Step 2: Run the new tests and confirm they fail.**

Run:
```bash
cd /Users/mwakichako/repos/invoice-processing/backend && pytest tests/test_validate_agent.py -v -k "run_validate_emits_future_date or run_validate_no_future_date"
```
Expected: failures. The first fails because `run_validate` doesn't accept `today` yet (TypeError) AND because the helper isn't wired in. The second also fails on the unknown kwarg.

- [ ] **Step 3: Modify `run_validate` to accept `today` and call `_check_future_date`.**

In `backend/app/agents/validate.py`, find the `run_validate` function signature around line 244:

```python
def run_validate(state: InvoiceState, *, db_path: Path, emitter: EventEmitter) -> InvoiceState:
```

Replace with:

```python
def run_validate(
    state: InvoiceState,
    *,
    db_path: Path,
    emitter: EventEmitter,
    today: dt.date | None = None,
) -> InvoiceState:
```

Just below the `emitter.emit("node.start", ...)` line at the top of the body, add a single line that resolves `today`:

```python
    emitter.emit("node.start", node="validate")
    if today is None:
        today = dt.date.today()
    inv = state.invoice
```

Then, in the issues-collection block (currently around lines 252-264), insert a call to `_check_future_date` right after `_check_dates`:

```python
    issues: list[ValidationIssue] = []
    issues.extend(_check_required_fields(inv))
    issues.extend(_check_negative_quantities(inv))
    issues.extend(_check_dates(inv))
    issues.extend(_check_future_date(inv, today))
    issues.extend(_check_total_math(inv))
    issues.extend(_check_currency(inv))
    issues.extend(_check_duplicate_invoice(
        inv, db_path, state_run_id=state.run_id, emitter=emitter,
    ))
    inv_issues, lookups = _check_line_items_against_inventory(inv, db_path, emitter)
    issues.extend(inv_issues)
    vendor_issues, vendor_result = _check_vendor(inv, db_path, emitter)
    issues.extend(vendor_issues)
```

- [ ] **Step 4: Run the new tests and confirm they pass.**

Run:
```bash
cd /Users/mwakichako/repos/invoice-processing/backend && pytest tests/test_validate_agent.py -v -k "run_validate_emits_future_date or run_validate_no_future_date"
```
Expected: 2 passed.

- [ ] **Step 5: Run the full `test_validate_agent.py` suite to confirm no regressions.**

Run:
```bash
cd /Users/mwakichako/repos/invoice-processing/backend && pytest tests/test_validate_agent.py -v
```
Expected: all passed.

- [ ] **Step 6: Commit.**

```bash
cd /Users/mwakichako/repos/invoice-processing && git add backend/app/agents/validate.py backend/tests/test_validate_agent.py
git commit -m "feat(validate): wire _check_future_date with injectable today"
```

---

## Task 4: Update the ingest `SYSTEM_PROMPT`

Strip the now-forbidden suspicion bullets, repair the orphaned "yesterday → note as signal" instruction, and add an explicit guardrail. No tests in this task — the schema enforces the contract, and Task 5 adds the prompt-drift defense test.

**Files:**
- Modify: `backend/app/agents/ingest.py:23-59` (the `SYSTEM_PROMPT` constant)

- [ ] **Step 1: Locate the current prompt.**

Read `backend/app/agents/ingest.py` lines 23-59 to confirm the prompt's current text matches what's reproduced below before editing.

- [ ] **Step 2: Replace `SYSTEM_PROMPT` with the updated version.**

Find:

```python
SYSTEM_PROMPT = """You are an invoice extractor.
Convert the provided invoice text into a structured JSON object.

Rules:
- Extract values verbatim from the source. Do not invent values.
- If a field is missing or unreadable, return null. Do not guess.
- Dates use YYYY-MM-DD. If the source says "yesterday" or another relative term,
  return null and note it as a suspicion signal.
- Quantities are integers; preserve negative values as written.
- Flag suspicion signals for any of:
  * urgent / threatening language ("URGENT", "pay immediately", "wire transfer")
  * dates in the past or expressed as "yesterday"
  * round-number totals on otherwise odd line items
  * generic or alarming vendor names
  * unknown / made-up looking item names
  * homoglyph corruption: invoice numbers or dates where letters substitute
    for digits (O<->0, l<->1, I<->1, B<->8, S<->5, Z<->2), or the literal
    word "INVOICE" mangled (e.g. "INV0ICE"). Emit kind='homoglyph_corruption'
    with text_match set to the exact corrupted token from the source.
- For each suspicion signal, when possible, set `text_match` to the EXACT verbatim
  phrase from the source that triggered the signal (e.g. "wire transfer required
  within 24 hours"). The phrase must appear in the source character-for-character.
  Omit `text_match` (return null) only when no single phrase captures the signal.
- Confidence is your self-assessment: 1.0 = perfect, 0.5 = needs human re-check, <0.3 = unreadable.

Return JSON matching this schema exactly:
{
  "invoice": {
    invoice_number, vendor, date, due_date,
    line_items:[{item, quantity, unit_price, notes}],
    subtotal, tax_amount, total, currency, payment_terms, raw_text
  },
  "suspicion_signals": [{ kind, detail, severity, text_match }],
  "extraction_confidence": number
}
The raw_text field should echo the input text exactly.
"""
```

Replace with:

```python
SYSTEM_PROMPT = """You are an invoice extractor.
Convert the provided invoice text into a structured JSON object.

Rules:
- Extract values verbatim from the source. Do not invent values.
- If a field is missing or unreadable, return null. Do not guess.
- Dates use YYYY-MM-DD. If the source says "yesterday" or another relative term,
  return null. (A null date is itself visible downstream — no signal needed.)
- Quantities are integers; preserve negative values as written.
- Flag suspicion signals for any of:
  * urgent / threatening language ("URGENT", "pay immediately", "wire transfer")
  * generic or alarming vendor names
  * unknown / made-up looking item names
  * homoglyph corruption: invoice numbers or dates where letters substitute
    for digits (O<->0, l<->1, I<->1, B<->8, S<->5, Z<->2), or the literal
    word "INVOICE" mangled (e.g. "INV0ICE"). Emit kind='homoglyph_corruption'
    with text_match set to the exact corrupted token from the source.
- Do NOT emit signals about dates, totals, arithmetic, or other claims
  derivable from the extracted fields — these are checked deterministically
  after extraction. Emit only signals about the wording, naming, or visual
  integrity of the source text. Valid kinds are: urgent_language,
  unknown_vendor_pattern, wire_transfer_demand, homoglyph_corruption, other.
- For each suspicion signal, when possible, set `text_match` to the EXACT verbatim
  phrase from the source that triggered the signal (e.g. "wire transfer required
  within 24 hours"). The phrase must appear in the source character-for-character.
  Omit `text_match` (return null) only when no single phrase captures the signal.
- Confidence is your self-assessment: 1.0 = perfect, 0.5 = needs human re-check, <0.3 = unreadable.

Return JSON matching this schema exactly:
{
  "invoice": {
    invoice_number, vendor, date, due_date,
    line_items:[{item, quantity, unit_price, notes}],
    subtotal, tax_amount, total, currency, payment_terms, raw_text
  },
  "suspicion_signals": [{ kind, detail, severity, text_match }],
  "extraction_confidence": number
}
The raw_text field should echo the input text exactly.
"""
```

- [ ] **Step 3: Run the ingest tests to confirm no regressions.**

Run:
```bash
cd /Users/mwakichako/repos/invoice-processing/backend && pytest tests/test_ingest_agent.py -v
```
Expected: all passed. The existing tests stub the LLM directly, so prompt content doesn't affect them.

- [ ] **Step 4: Commit.**

```bash
cd /Users/mwakichako/repos/invoice-processing && git add backend/app/agents/ingest.py
git commit -m "feat(ingest): drop banned suspicion-signal bullets; add deterministic-claims guardrail"
```

---

## Task 5: Add the prompt-drift defense test

If the prompt regresses and the LLM emits a banned kind, the pydantic schema rejects it and `run_ingest` must set `state.error`. This test pins that contract by stubbing the SDK (one layer below `structured_complete`) so the real pydantic validation runs.

**Files:**
- Test: `backend/tests/test_ingest_agent.py`

- [ ] **Step 1: Add the test at the end of `backend/tests/test_ingest_agent.py`.**

```python
import json

from app.llm.grok_client import GrokClient


def _make_sdk_returning(content: str) -> MagicMock:
    """Build a MagicMock that mimics the OpenAI SDK shape `structured_complete` consumes."""
    sdk = MagicMock()
    sdk.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=content))],
        usage=MagicMock(prompt_tokens=10, completion_tokens=5),
    )
    return sdk


def test_ingest_rejects_llm_response_with_banned_suspicion_kind(tmp_path: Path):
    """If the LLM emits a banned kind (e.g., impossible_date), pydantic must reject
    the response and run_ingest must mark the state as unprocessable.
    Regression guard for the INV-1006 cascade if the prompt drifts."""
    inv_file = tmp_path / "inv.txt"
    inv_file.write_text("INVOICE\nVendor: Widgets Inc.\nTotal: $1000\n")

    bad_response = json.dumps({
        "invoice": {
            "invoice_number": "INV-1", "vendor": "Widgets Inc.",
            "date": "2026-01-25", "due_date": None, "line_items": [],
            "subtotal": 1000.0, "tax_amount": 0.0, "total": 1000.0,
            "currency": "USD", "payment_terms": None, "raw_text": "...",
        },
        "suspicion_signals": [
            {"kind": "impossible_date", "detail": "Date is in the future",
             "severity": "high", "text_match": None},
        ],
        "extraction_confidence": 0.9,
    })

    sdk = _make_sdk_returning(bad_response)
    # max_retries=0 so we don't waste two stubbed responses on the same failure.
    llm = GrokClient(sdk=sdk, model="grok-3-test")

    state = _mk_state(str(inv_file))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_ingest(state, llm=llm, emitter=emitter)

    assert out.error is not None
    assert out.error.startswith("unprocessable: extraction failed")
    # The SDK was called at least once (structured_complete may retry).
    assert sdk.chat.completions.create.call_count >= 1
```

Note: `MagicMock`, `EventEmitter`, and `_mk_state` are already imported at the top of `test_ingest_agent.py`.

- [ ] **Step 2: Run the new test.**

Run:
```bash
cd /Users/mwakichako/repos/invoice-processing/backend && pytest tests/test_ingest_agent.py::test_ingest_rejects_llm_response_with_banned_suspicion_kind -v
```
Expected: PASS. (`structured_complete` will retry once per its `max_retries=1` default, both attempts fail pydantic validation against the now-narrowed Literal, the final `ValidationError` propagates, `run_ingest` catches it and sets `state.error`.)

- [ ] **Step 3: If the test fails because `structured_complete` retries and eventually succeeds (it shouldn't — the stub always returns the same bad response), confirm by checking the call count.**

If the test fails for any reason other than the assertions, read the stack trace before changing anything. The most likely failure modes:

- `state.error` is None: the LLM stub returned valid data on retry — but the stub doesn't change behavior across calls, so this would indicate that pydantic *accepted* `impossible_date`, which means Task 1 wasn't completed correctly. Re-verify `state.py:31-39`.
- `AttributeError` on `sdk.chat.completions.create.call_count`: the stub structure is wrong. Re-check `_make_sdk_returning`.

- [ ] **Step 4: Commit.**

```bash
cd /Users/mwakichako/repos/invoice-processing && git add backend/tests/test_ingest_agent.py
git commit -m "test(ingest): prompt-drift defense — schema rejects banned suspicion kinds"
```

---

## Task 6: End-to-end INV-1006 regression test through the rules engine

The bug's cascade went: LLM emits bogus signals → max_sev gates flip → `auto_approve=False`, scrutiny triggered. This test reconstructs INV-1006's invoice data (with the LLM stubbed to return clean signals — i.e., no bogus claims) and asserts the rules engine returns `auto_approve=True`.

**Files:**
- Test: `backend/tests/test_rules_engine.py`

- [ ] **Step 1: Inspect `test_rules_engine.py` to find the import block and helper conventions.**

Run:
```bash
head -40 /Users/mwakichako/repos/invoice-processing/backend/tests/test_rules_engine.py
```
Note the existing imports and any `_state` / `_inv` helpers — reuse them. If the test file constructs `InvoiceState` directly, match that style.

- [ ] **Step 2: Add the regression test at the end of `test_rules_engine.py`.**

```python
import datetime as dt
from pathlib import Path

from app.agents.validate import run_validate
from app.db.init_db import init_db
from app.graph.state import (
    InvoiceData, InvoiceState, LineItem,
)
from app.logging_.event_emitter import EventEmitter
from app.rules.engine import evaluate_rules

SEED = Path(__file__).resolve().parents[1] / "app" / "db" / "seed.yaml"


def test_inv_1006_regression_past_date_round_total_clean_signals(tmp_path: Path):
    """INV-1006 cascade regression: an invoice with a past date and round line
    items must reach auto_approve=True when the LLM emits no suspicion signals
    (i.e., when the prompt no longer asks the LLM to make claims it can't verify)."""
    db = tmp_path / "t.db"
    init_db(db, seed_path=SEED, reset=True)

    invoice = InvoiceData(
        invoice_number="INV-1006",
        vendor="Acme Industrial Supplies",
        date=dt.date(2026, 1, 25),
        due_date=dt.date(2026, 2, 10),
        line_items=[
            LineItem(item="WidgetA", quantity=5, unit_price=250.0),
            LineItem(item="WidgetB", quantity=3, unit_price=500.0),
        ],
        subtotal=2750.0,
        tax_amount=0.0,
        total=2750.0,
        currency="USD",
        payment_terms="Net 15",
        raw_text="...",
    )
    state = InvoiceState(
        run_id="r", source_path="x", file_format="txt", invoice=invoice,
    )
    # Simulate a well-behaved LLM: no suspicion signals emitted.
    state.suspicion_signals = []
    state.extraction_confidence = 0.9

    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(
        state, db_path=db, emitter=emitter, today=dt.date(2026, 5, 13),
    )

    # No future_date issue (the date is in the past).
    assert not any(i.kind == "future_date" for i in out.validation.issues)
    # No deterministic blockers or warnings should fire for this clean invoice.
    assert not any(i.severity in ("block", "warn") for i in out.validation.issues), \
        f"unexpected issues: {[i.model_dump() for i in out.validation.issues]}"

    evaluation = evaluate_rules(out)
    assert evaluation.auto_approve is True, (
        f"INV-1006 should auto-approve under the new pipeline; "
        f"evaluation={evaluation}"
    )
    assert evaluation.scrutiny is False
    assert evaluation.hard_blocks == []
```

Note: if `test_rules_engine.py` already has any of these imports (`dt`, `Path`, `InvoiceData`, `InvoiceState`, `LineItem`, `EventEmitter`, `evaluate_rules`, `init_db`), merge them into the existing import block instead of duplicating.

- [ ] **Step 3: Run the new test.**

Run:
```bash
cd /Users/mwakichako/repos/invoice-processing/backend && pytest tests/test_rules_engine.py::test_inv_1006_regression_past_date_round_total_clean_signals -v
```
Expected: PASS. If it fails on `auto_approve is True`, inspect the evaluation dataclass — the failure message includes the full state so the cause is visible.

- [ ] **Step 4: Commit.**

```bash
cd /Users/mwakichako/repos/invoice-processing && git add backend/tests/test_rules_engine.py
git commit -m "test(rules): regression for INV-1006 past-date + round-total cascade"
```

---

## Task 7: Audit fixtures and outcome files for orphaned references to the banned kinds

The spec calls out that any test asserting `impossible_date` or `round_number` signal emission needs to be rewritten or deleted. Task 1 caught test-code references via the full suite run; this task catches non-test references (fixtures, YAML, JSON snapshots) the test runner won't surface.

**Files:**
- Audit: any file under `backend/tests/` that may mention the banned kinds.
- Audit: `backend/tests/expected_outcomes.yaml`.

- [ ] **Step 1: Grep all of `backend/tests/` for banned kinds.**

Run:
```bash
grep -rn "impossible_date\|round_number" /Users/mwakichako/repos/invoice-processing/backend/tests/
```
Expected output: only the new schema-enforcement tests from Task 1 (`test_state_models.py`). If anything else matches — particularly in `expected_outcomes.yaml`, `fixture_helpers.py`, or any snapshot JSON — open the file and decide:

- If the reference is an *expectation* that a signal of that kind was emitted, the expectation is no longer reachable. Update it to expect either no such signal, or an analogous signal under the new taxonomy (e.g., a fixture that paired "future-dated invoice" with `impossible_date` should now expect a `future_date` validation issue).
- If the reference is purely descriptive (e.g., a comment), leave it but add a note pointing at the spec.

- [ ] **Step 2: Grep all of `backend/data/` for banned kinds.**

Run:
```bash
grep -rln "impossible_date\|round_number" /Users/mwakichako/repos/invoice-processing/backend/data/ 2>/dev/null
```
Expected: matches in `backend/data/batch_results/runs/*.json` (historical batch artifacts including the INV-1006 run). **Do not edit historical artifacts** — they're frozen records of past behavior. Note them in the commit message for traceability.

- [ ] **Step 3: If Step 1 surfaced anything in `tests/`, fix it; otherwise skip to Step 4.**

For each match, apply the rule from Step 1. Re-run the full test suite after each fix:

```bash
cd /Users/mwakichako/repos/invoice-processing/backend && pytest -v
```

- [ ] **Step 4: Commit (only if Step 3 made changes; otherwise skip).**

```bash
cd /Users/mwakichako/repos/invoice-processing && git add backend/tests/
git commit -m "test: update fixtures referencing dropped suspicion kinds"
```

---

## Task 8: Verify end-to-end and replay historical runs

Verification, not new code. Run the full test suite, then replay at least one historical batch run through the new pipeline and diff the signals.

**Files:** none (no code changes).

- [ ] **Step 1: Run the full backend test suite one final time.**

Run:
```bash
cd /Users/mwakichako/repos/invoice-processing/backend && pytest -v
```
Expected: all passed.

- [ ] **Step 2: Confirm `mypy` / type checking passes (if the project uses it).**

Run:
```bash
cd /Users/mwakichako/repos/invoice-processing/backend && (mypy app/ 2>/dev/null || echo "mypy not configured — skip")
```
If `mypy` runs, expected: no new errors introduced by these changes. If errors exist that pre-date this work, leave them.

- [ ] **Step 3: Locate the replay tooling.**

Run:
```bash
ls /Users/mwakichako/repos/invoice-processing/backend/app/tools/replay.py /Users/mwakichako/repos/invoice-processing/backend/scripts/ 2>/dev/null
```
Read `replay.py` and any related script to determine the exact replay invocation. The script likely takes a run-id or a path to a `runs/<id>.json` artifact.

- [ ] **Step 4: Replay the INV-1006 batch run and capture the new signals.**

Identify the INV-1006 run artifact:
```bash
grep -l "INV-1006" /Users/mwakichako/repos/invoice-processing/backend/data/batch_results/runs/*.json
```
Expected: `/Users/mwakichako/repos/invoice-processing/backend/data/batch_results/runs/3f86ba97d7144ba7bcaa8e4f4d717758.json` (or similar).

Run the replay against that artifact using the invocation discovered in Step 3. Output the new `suspicion_signals` and `validation.issues` for INV-1006.

Assertions (manual inspection):

- INV-1006's new `validation.issues` does NOT contain `future_date`.
- INV-1006's new `suspicion_signals` does NOT contain `impossible_date` or `round_number`.
- The rules engine evaluation for INV-1006 reports `auto_approve=True` (or at minimum, scrutiny is no longer triggered by signals that were the original false positives).

If the replay tool does not exist or is not invokable in this environment, write the verification step as a notes block in the final commit message instead — flag this as a follow-up requiring real-environment verification.

- [ ] **Step 5: Spot-check a second historical run for regressions.**

Pick any other `runs/*.json` artifact and replay it. Compare its `validation.issues` and `suspicion_signals` before vs. after:

- Any invoice that had a *genuinely* future date should now show a `future_date` validation issue (warn) instead of an `impossible_date` suspicion signal (high). The downstream `auto_approve` / `scrutiny` outcome should be similar — the warn-level validation issue triggers scrutiny via `has_warn` just as a medium-or-higher suspicion did before.
- No invoice that was previously clean should now newly fail.

Document findings in the final commit message.

- [ ] **Step 6: Commit the verification notes (no code).**

If Steps 4–5 produced no code changes, commit a notes file or extend the spec with a "Verification log" section. Suggested location: a new `docs/superpowers/specs/2026-05-13-suspicion-signal-pipeline-verification.md` with the replay output snippets, or a paragraph appended to the existing spec under a `## Verification` heading.

```bash
cd /Users/mwakichako/repos/invoice-processing && git add docs/superpowers/specs/
git commit -m "docs(spec): verification log for suspicion signal pipeline rollout"
```

If no replay was possible (no tooling, no env), commit a notes block to the spec marking verification as a follow-up and including any new flags you'd want to watch in production logs (e.g., `pydantic ValidationError` rate from `ingest.py`).

---

## Self-Review

Checked against the spec sections:

- **Principle / taxonomy** — Task 1 (schema), Task 4 (prompt). Covered.
- **Kind-by-kind mapping** — Task 1 removes `impossible_date` / `round_number` from `SuspicionSignal`; Task 1 adds `future_date` to `ValidationIssue`. Covered.
- **Schema changes** — Task 1. Covered.
- **Validation check** (`_check_future_date`, `today` kwarg) — Tasks 2 and 3. Covered.
- **Ingest prompt** — Task 4. Includes the orphaned "yesterday → note as signal" fix flagged in the spec self-review. Covered.
- **Approve agent / rules engine** (no changes) — Confirmed in Task 8 Step 1 (full suite passes without touching them). Covered.
- **Tests: regression, positive, schema-enforcement, prompt-drift defense, existing test audit** — Tasks 1, 2, 3, 5, 6, 7. Covered.
- **Rollout: schema first, then validation, then prompt, then replay** — Task ordering matches. Covered.

No placeholders. No TODOs. Types and signatures are consistent between tasks: `_check_future_date(inv: InvoiceData, today: dt.date) -> list[ValidationIssue]` referenced identically in Tasks 2 and 3.
