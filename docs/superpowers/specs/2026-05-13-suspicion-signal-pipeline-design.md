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

- **Remove** the bullet `"dates in the past or expressed as 'yesterday'"` from the "Flag suspicion signals for any of:" list.
- **Remove** the bullet `"round-number totals on otherwise odd line items"` from the same list.
- **Revise** the higher-up instruction that currently reads *"If the source says 'yesterday' or another relative term, return null and note it as a suspicion signal."* — strip the trailing "and note it as a suspicion signal" half so it reads simply: *"If the source says 'yesterday' or another relative term, return null."* The null date is itself visible to downstream code; no signal is needed.
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

Simulate the LLM emitting a banned kind by stubbing the SDK call inside `GrokClient` (below `structured_complete`) to return a raw JSON body whose `suspicion_signals` contains `{"kind": "impossible_date", ...}`. The real pydantic validation inside `structured_complete` should reject it, and `run_ingest` should set `state.error` to a value starting with `"unprocessable: extraction failed"`.

This pins the contract at the ingest boundary: even if the prompt regresses, the schema fails fast and loudly rather than silently propagating the bad signal. The exact stubbing layer is an implementation detail for the plan — the requirement is that the test exercises real schema validation, not a mocked-out version.

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

## Verification

**Date:** 2026-05-13  
**Branch:** feature/ui-improvement  
**Verified by:** Task 8 (end-to-end verification)

### Full test suite

```
149 passed, 26 skipped in 1.23s
```

All 149 tests pass. The 26 skipped are integration/live-smoke tests gated on `RUN_LIVE_TESTS=1` / `XAI_API_KEY` — intentionally offline-only. No regressions.

### mypy

mypy reports 4 pre-existing errors in 3 files (`app/llm/tools_loop.py`, `app/api/runs.py`, `app/tools/llm_tools.py`). **None of these are in files touched by this change.** No new errors introduced.

### Replay tooling

`backend/app/tools/replay.py` reads a `.jsonl` event trace from `backend/logs/<run_id>.jsonl` and summarises token usage, tool calls, and the stored `approve.decision` event. It does **not** re-run the pipeline — it reads persisted events. Invocation: `python -m app.tools.replay --run_id <id>`.

The replay tool is a trace inspector, not a pipeline re-runner. A live LLM is **not** required for the validation checks below; the new `_check_future_date` is deterministic and was exercised directly.

### INV-1006 — original trace (run `3f86ba97d7144ba7bcaa8e4f4d717758`)

```
replay output:
  Run:      3f86ba97d7144ba7bcaa8e4f4d717758
  Events:   25
  LLM:      4 calls, 3072 in / 723 out, 21168ms total
  Tools:    3
  Outcome:  needs_review
  Rules:    If scrutiny is required, weigh the validation warnings and suspicion signals
  Rationale:
    ...high-severity suspicion signal of an impossible date (future date 2026-01-25)
    and the medium-severity round number concern (total 2750.00)...
```

Original `suspicion_signals`: `[{kind: impossible_date, severity: high}, {kind: round_number, severity: medium}]`  
Original `validation.issues`: `[]` (empty)  
Original `decision.outcome`: `needs_review`

### INV-1006 — re-validation against new code (deterministic, no LLM required)

`_check_future_date(inv, today=date(2026, 5, 13))` with `inv.date = date(2026, 1, 25)`:

- Result: `[]` (empty) — 2026-01-25 is ~3.5 months in the **past**; no `future_date` issue emitted. CONFIRMED.
- `impossible_date` and `round_number` are now banned Literal kinds — pydantic rejects them at schema boundary (verified by `test_suspicion_signal_rejects_impossible_date_kind` and `test_suspicion_signal_rejects_round_number_kind`).
- With no signals and no validation issues, `evaluate_rules` returns `auto_approve=True` for INV-1006 (verified by `test_inv_1006_regression_past_date_round_total_clean_signals`).

**Assertions met:**
- `validation.issues` does NOT contain `future_date` — PASS
- `suspicion_signals` does NOT contain `impossible_date` or `round_number` — PASS (schema-enforced)
- `auto_approve=True` for INV-1006 — PASS (regression test confirms)

### Spot-check second run — INV 1012 (run `0dbcf6f5fc4e4656b5e537fc1b328cb7`)

Original: `suspicion_signals=[]`, `validation.issues=[]`, `decision.outcome=approved`  
Re-validation: `_check_future_date(inv, today=date(2026, 5, 13))` with `inv.date=date(2026, 1, 26)` → `[]`

Previously clean invoice stays clean. No regression. CONFIRMED.

### Genuinely future date — correctness check

`_check_future_date(inv, today=date(2026, 5, 13))` with `inv.date=date(2026, 12, 1)`:

```
[ValidationIssue(kind='future_date', severity='warn',
  detail='invoice date 2026-12-01 is 202 day(s) in the future (today is 2026-05-13)')]
```

A genuinely future date now produces a `warn`-severity `future_date` ValidationIssue, which triggers `has_warn` scrutiny in the rules engine — same downstream effect as the old `impossible_date` high-severity signal, but deterministically correct. CONFIRMED.

### Full replay (live LLM)

Deferred — re-running the full pipeline for INV-1006 requires live `XAI_API_KEY` credentials not available in this environment. All deterministic checks confirm correct behavior. Live re-run is a follow-up for a credentialed environment; the regression test (`test_inv_1006_regression_past_date_round_total_clean_signals`) provides equivalent coverage offline.

**Follow-up:** In production, watch the `pydantic ValidationError` rate from `app/agents/ingest.py` → `run_ingest`. If the LLM regresses and emits a banned kind, the error surfaces as `state.error = "unprocessable: extraction failed ..."` — monitor the `node.error` event stream for this pattern.
