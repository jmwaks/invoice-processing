# Suspicion Signal Pipeline: Deterministic Ownership of Objective Claims

**Date:** 2026-05-13
**Status:** Approved (pending implementation plan)
**Scope:** Backend only (signal taxonomy, validation, ingest prompt, tests)

## Problem

The ingest LLM emits `SuspicionSignal`s that are downstream load-bearing: a single high-severity signal forces `auto_approve=False` and triggers scrutiny in `app/rules/engine.py`, and the approve agent escalates to `needs_review`.

The LLM (Grok 3) is asked to make claims it cannot reliably make. Concretely, on invoice **INV-1006** (batch run `3f86ba97d7144ba7bcaa8e4f4d717758`):

- The LLM emitted `impossible_date: "Date is in the future (2026-01-25)"` when the actual current date was **2026-05-13** — the invoice date was ~3.5 months in the *past*. Grok 3 has no reliable awareness of "today" at inference time.
- The LLM emitted `round_number: "Total is a round number (2750.00) despite non-round line item prices"`. The line item prices were `$250.00` and `$500.00` — both perfectly round. The claim is factually wrong.

Both deterministic checks in `app/agents/validate.py` (math, dates, currency, inventory, vendor) passed cleanly. The cascade is: LLM hallucinates → signals enter `state.suspicion_signals` unverified → rules engine's `max_sev` gate flips → approve routes to `needs_review`.

The root cause is a **taxonomy error**: the LLM is being asked to emit signals whose truth value can be computed deterministically from extracted fields and `datetime.date.today()`. Objective claims should not flow through a probabilistic emitter.

## Goals

- Reassign every signal kind to the pipeline that can actually verify it: deterministic checks in `validate.py` for field-derived claims; LLM-emitted `SuspicionSignal`s only for textual/semantic heuristics.
- Make the contract enforceable at the schema layer (pydantic `Literal`) so a future prompt edit cannot silently reintroduce a banned kind.
- Add a deterministic future-date check that injects `today` from the caller (testable, no wall-clock dependency).
- Drop `round_number` entirely — `total_math_error` already catches the underlying risk.

## Non-Goals

- No unification of `ValidationIssue` and `SuspicionSignal` into a single `Signal` stream. The two-pipeline split is preserved; only the ownership of specific kinds moves.
- No changes to the rules engine (`app/rules/engine.py`) or `rules.yaml`. The new `future_date` issue is `warn` severity and rides the existing `has_warn` scrutiny path.
- No changes to the approve agent's prompts or critique loop. `_context_block` already serializes whatever validation issues exist.
- No new hard-block kinds. `future_date` does not hard-reject; legitimate scheduled/pre-billing invoices remain approvable with rationale.
- No frontend redesign. If a frontend lookup table enumerates `kind`, it gets `future_date` added and `impossible_date`/`round_number` removed — but no UI restructuring.
- No tiered severity (warn-near-future vs block-far-future). Considered and rejected as premature; can be added later if false negatives appear.
- No re-prompting/self-critique pass on the LLM's output. The schema-layer constraint is the enforcement mechanism.

## Design

### Principle

Each signal kind belongs to exactly **one** pipeline, chosen by *who can verify the claim*:

- **`validate.py` (ValidationIssue)** — claims derivable from extracted fields + `today` + DB lookups. Deterministic, testable, no LLM in the loop.
- **`ingest.py` (SuspicionSignal)** — purely textual/semantic claims requiring prose interpretation. LLM-emitted, with the existing `detect_homoglyphs` "deterministic floor" as the escape valve for kinds we want guaranteed coverage on.

### Kind-by-kind mapping

| Kind | Before | After | Notes |
|---|---|---|---|
| `impossible_date` | SuspicionSignal (LLM) | **ValidationIssue `future_date` (warn)** | Deterministic: `inv.date > today` |
| `round_number` | SuspicionSignal (LLM) | **Removed entirely** | `total_math_error` already covers the real risk; a round total with reconciling math is not informative |
| `urgent_language` | SuspicionSignal (LLM) | unchanged | Textual heuristic |
| `wire_transfer_demand` | SuspicionSignal (LLM) | unchanged | Textual heuristic |
| `unknown_vendor_pattern` | SuspicionSignal (LLM) | unchanged | Naming heuristic, complements deterministic `unknown_vendor` |
| `homoglyph_corruption` | SuspicionSignal (LLM + det floor) | unchanged | Already correct pattern |
| `other` | SuspicionSignal (LLM) | unchanged | Escape hatch |

### Schema changes — `app/graph/state.py`

`SuspicionSignal.kind` Literal: remove `"impossible_date"` and `"round_number"`. Final set:

```python
kind: Literal[
    "urgent_language",
    "unknown_vendor_pattern",
    "wire_transfer_demand",
    "homoglyph_corruption",
    "other",
]
```

`ValidationIssue.kind` Literal: add `"future_date"`. The remaining kinds are unchanged.

Removing kinds from the `Literal` means pydantic rejects any LLM response that emits them. This is the load-bearing enforcement — if a prompt regression reintroduces these claims, ingest fails fast with a validation error rather than silently propagating false signals.

### Validation check — `app/agents/validate.py`

New private helper:

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

`run_validate` gains a `today: dt.date | None = None` kwarg. If `None`, default to `dt.date.today()` at the *top of the function* (single point of wall-clock contact, easy to audit). Pass `today` into `_check_future_date`. The graph builder (`app/graph/builder.py`) passes through whatever it receives or relies on the default.

Tests inject a fixed `today` via the kwarg. Per CLAUDE.md ("Tests must be deterministic … don't depend on wall-clock time"), no test should call the no-arg form.

### Ingest prompt — `app/agents/ingest.py`

Update `SYSTEM_PROMPT`:

- **Remove** the bullet `"dates in the past or expressed as 'yesterday'"`.
- **Remove** the bullet `"round-number totals on otherwise odd line items"`.
- **Add** an explicit guardrail line: `"Do NOT emit signals about dates, totals, arithmetic, or other claims derivable from the extracted fields — these are checked deterministically after extraction. Emit only signals about the wording, naming, or visual integrity of the source text."`

No code-path changes in `run_ingest`. The existing `detect_homoglyphs` deterministic floor stays.

### Approve agent and rules engine

No changes. `_context_block` serializes whatever `ValidationIssue`s and `SuspicionSignal`s exist; the approver and critique LLMs see `future_date` in the JSON without code awareness. The rules engine's `has_warn` path picks up `future_date` (severity `warn`) and triggers scrutiny exactly as it does for `past_due_date`.

### Architecture diagram

```
Before:
  ingest LLM ──> SuspicionSignal{impossible_date, round_number, ...}
                                ↓ (no verification)
                          rules.engine ──> auto_approve / scrutiny

After:
  ingest LLM ──> SuspicionSignal{urgent_language, ...}     (textual only;
                                                           Literal-enforced)
                                ↓
  validate.py ──> ValidationIssue{future_date, ...}        (deterministic,
       ↑                                                    today injected)
       └── today: dt.date
                                ↓
                          rules.engine ──> auto_approve / scrutiny
```

## Testing

### Regression test — the INV-1006 case

Fixture: invoice with `date = today - 30 days`, round total, round line items, otherwise clean.

Inject a fixed `today` and a stubbed `GrokClient` that returns an empty `suspicion_signals` list (simulating a well-behaved LLM).

Assert:
- `state.validation.issues` contains no `future_date` issue.
- `state.suspicion_signals` is empty.
- `evaluate_rules(state).auto_approve` is `True`.

### Positive test — future date detected

Fixture: invoice with `date = today + 10 days`, otherwise clean. Inject fixed `today`.

Assert:
- `state.validation.issues` contains exactly one `future_date` issue at `warn`.
- The detail string includes the day count and both dates.
- `evaluate_rules(state).scrutiny` is `True`, `auto_approve` is `False`.

### Schema-enforcement tests

```python
with pytest.raises(ValidationError):
    SuspicionSignal(kind="impossible_date", detail="x", severity="high")

with pytest.raises(ValidationError):
    SuspicionSignal(kind="round_number", detail="x", severity="medium")
```

### Prompt-drift defense test

Stub `GrokClient.structured_complete` to return a raw JSON response containing a `SuspicionSignal` with `kind="impossible_date"`. Assert that the pydantic schema rejects it and `run_ingest` sets `state.error` to a value starting with `"unprocessable: extraction failed"`.

This pins the contract at the ingest boundary: even if the prompt regresses, the schema fails fast and loudly rather than silently propagating the bad signal.

### Existing tests to audit

Grep `backend/tests/` for `impossible_date`, `round_number`. Any fixture asserting these signals were emitted is rewritten (if the underlying concern is still relevant under the new taxonomy) or deleted (if the concern was redundant with deterministic checks).

## Rollout

1. **Schema changes first** (`state.py` Literal edits). Pydantic and mypy errors will light up everywhere that needs follow-up.
2. **Validation check + tests.** Implement `_check_future_date`, wire `today` through, add positive + schema-enforcement tests.
3. **Ingest prompt + tests.** Update `SYSTEM_PROMPT`, add prompt-drift defense test, run regression fixture.
4. **Replay historical runs.** Re-run the existing `backend/data/batch_results/runs/*.json` invoices against the new code. Diff `suspicion_signals` and `validation.issues` per invoice. Confirm:
   - INV-1006 no longer flags (no `future_date`, no `round_number`, `auto_approve=True` or at least no spurious scrutiny).
   - No previously-clean invoice newly flags as `future_date`.
   - No previously-flagged invoice now passes when it shouldn't (e.g., one that was correctly caught by `impossible_date` for a genuinely future date — those should now be caught deterministically).
5. **Full backend test suite.** No regressions.

## Risks and trade-offs

- **Risk: prompt-drift defense test is brittle.** It depends on the LLM client's error propagation contract. If `structured_complete` changes how it surfaces validation errors, the test breaks. Acceptable — the test is meant to catch contract changes.
- **Trade-off: warn vs. block for `future_date`.** Warn was chosen for consistency with `past_due_date` and to avoid blocking legitimate scheduled/pre-billing invoices. If false-negatives on far-future dates become a problem, the tiered-severity variant is a small follow-up.
- **Risk: legitimate "round_number" cases get missed.** Considered. The argument for keeping it was always that a round total with non-round line items might indicate fabrication. But `total_math_error` already catches every case where the numbers don't reconcile; a fabricated invoice whose math reconciles is indistinguishable from a real one with round prices. The signal carried no actionable information.
- **Path not taken: unified Signal stream.** Cleaner end-state but touches the rules engine, the `Decision`/`Critique` payloads, the SSE event shapes, and the frontend casefile rendering. The two-pipeline split with strict ownership achieves the same robustness with surgical changes.
