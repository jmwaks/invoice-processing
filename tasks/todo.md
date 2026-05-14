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

## 2026-05-13 — Bound Grok retry stack to a wall-clock budget

Cause of the 6-minute hang in run `1fb6368f6aaa4185aad3f065dacccf33`: cumulative timeout when Grok is at capacity. Two contributors stack multiplicatively:

1. `OpenAI()` is constructed without `max_retries=…`, so the SDK's own 2 retries layer on top of ours, tripling per-attempt latency to ~90s.
2. No global wall-clock budget; only per-call timeouts. Outer retry × inner validation retry × SDK retry × 30s timeout × fallback ≈ 9 min worst case.

### Plan

- [x] **1. Failing test for SDK `max_retries=0`.** In `backend/tests/test_grok_client.py`, add `test_sdk_constructed_with_zero_max_retries`: construct `GrokClient(api_key="sk-test", model="grok-4")` (no injected `sdk`), assert `client.sdk.max_retries == 0`. Run, confirm failure.
- [x] **2. Failing test for wall-clock budget.** Add `test_wall_clock_budget_short_circuits_retries`: monkeypatch `time.monotonic` to a controllable clock; each fake SDK call advances the clock by 30s and raises 429; assert exactly 3 SDK calls (third call ends past the 90s deadline → fallback skipped) and `LLMUnavailableError` raised. Run, confirm failure (currently makes 4 calls).
- [x] **3. Implement (1).** In `GrokClient.__init__` (`backend/app/llm/grok_client.py:67`), change to `OpenAI(api_key=api_key, base_url=base_url, max_retries=0)`.
- [x] **4. Implement (2).** Add `_TOTAL_DEADLINE_S = 90.0` constant. In `structured_complete`, compute `deadline = time.monotonic() + _TOTAL_DEADLINE_S` and thread it into `_call_with_retry` and the fallback path. In `_call_with_retry`, check the deadline at the top of each iteration and break to `LLMUnavailableError`. In `structured_complete`, skip the fallback if the deadline is already past.
- [x] **5. Verify.** Both new tests green; full `test_grok_client.py` and `test_api.py` still green.

### Review

**Files changed:**
- `backend/app/llm/grok_client.py` — added `_TOTAL_DEADLINE_S = 90.0`; `OpenAI(...)` now constructed with `max_retries=0`; `_call_with_retry` accepts a `deadline` and breaks out when `time.monotonic() >= deadline`; `structured_complete` computes the deadline once and shares it across primary + fallback (skips fallback if the deadline has already elapsed).
- `backend/tests/test_grok_client.py` — added `test_sdk_constructed_with_zero_max_retries` and `test_wall_clock_budget_short_circuits_retries` (uses a controllable `time.monotonic` to simulate per-attempt 30s timeouts).

**Verification:**
- TDD: both new tests failed first (sdk default `max_retries=2`; deadline test saw 4 calls), then passed after the implementation.
- `test_grok_client.py` 14/14 green; `test_grok_client + test_api + test_ingest_agent` 28/28 green; full backend suite **166 passed, 26 skipped**.

**Effect on the hang we investigated:**
- Per-call ceiling drops from ~90s (SDK 3× retry) to ~30s (single timeout).
- Worst-case `structured_complete` latency drops from ~9 min to ≤90s. For the 6 min hang on run `1fb6368f6aaa4185aad3f065dacccf33`, the equivalent failure would now surface as `LLMUnavailableError` in ≤90s, letting the caller (and the user) see a clean `run.error` quickly instead of staring at a blank ingest.

### Follow-up: split primary / fallback budget (same day)

A 91.8s failure on run `f5e20f0694be45459b8e53bf327817d9` exposed a regression in the single-deadline design: when grok-4 was at capacity, 3× 30s timeouts consumed the entire 90s budget and the deadline check at the fallback gate skipped grok-3 entirely. The fallback existed but never ran — exactly the case it was meant to handle.

**Change:** replaced `_TOTAL_DEADLINE_S = 90.0` with `_PRIMARY_DEADLINE_S = 60.0` + `_FALLBACK_TIMEOUT_S = 30.0`. `structured_complete` now uses the 60s deadline for primary retries, then drops the deadline gate before fallback and calls the fallback with `max_retries=0` (one SDK call, bounded by the 30s request timeout). Net ceiling ≈ 90s, but the fallback is now guaranteed a shot when configured.

**Tests:** renamed `test_wall_clock_budget_short_circuits_retries` → `test_primary_deadline_short_circuits_grok4_retries` (now uses `fallback_model=""` to test the primary path in isolation, asserts 2 SDK calls). Added `test_fallback_runs_when_primary_exhausts_primary_budget`: primary 429s twice, primary deadline cuts the 3rd attempt, fallback succeeds — asserts 3 SDK calls and `meta.model == "grok-3"`. Full suite **167 passed, 26 skipped**.

### Follow-up: per-attempt telemetry via `on_attempt` callback (same day)

Wall-time alone can't distinguish "3 grok-4 attempts, fallback skipped" from "2 grok-4 attempts + 1 grok-3 attempt" — both sum to ~91s. Run logs needed per-attempt visibility to confirm the fallback actually ran.

**Change:** added optional `on_attempt: Callable[[str], None] | None = None` parameter to `GrokClient.structured_complete`, threaded through `_call_with_retry` and `_call_once`. The callback fires just before each `sdk.chat.completions.create` call with the model name. Agents wire a lambda that emits `llm.attempt` events through their `EventEmitter`. Default `None` preserves all existing call sites.

**Wiring:**
- `app/agents/ingest.py` — emits `llm.attempt` with `node="ingest", model=…`.
- `app/agents/approve.py` — emits `llm.attempt` with `node="approve", sub=<propose|critique|finalize>, model=…` for the three `structured_complete` call sites. (`_run_investigate` uses `run_tool_loop` directly and is out of scope here — see `lessons.md`'s "resilience lives in X" entry for the same boundary.)

**Tests added:** `test_on_attempt_callback_fires_per_sdk_call` (429 then success → callback sees `["grok-4", "grok-4"]`) and `test_on_attempt_callback_fires_for_fallback_model` (3× 429 on grok-4 then grok-3 succeeds → callback sees `["grok-4", "grok-4", "grok-4", "grok-3"]`). Full suite **169 passed, 26 skipped**.

### Follow-up: stop asking the LLM to echo raw_text (same day)

Run `e9f8b718852e4f809776a82792d0ac25` (INV-9005 — 49 line items, ~2.3 KB) timed out 3 times in a row on grok-3. The new `llm.attempt` telemetry confirmed every attempt hit the 30 s SDK timeout — not an upstream-capacity event but an output-token-volume problem: the prompt asked the LLM to echo `raw_text` verbatim while also generating 49 line items, ~2–3 K output tokens per call.

**The dead-work bug:** `ingest.py:112` always overwrites the field with `state.invoice.raw_text = loaded.text` before any consumer reads it. So the LLM spent hundreds of output tokens echoing a 2.3 KB file we already had on disk, then we discarded the echo.

**Change:**
- `app/agents/ingest.py:51-62` — removed `raw_text` from the schema fragment in `SYSTEM_PROMPT` and dropped the "raw_text field should echo the input text exactly" line.
- `app/graph/state.py:27` — `raw_text: str = ""` (default) so the LLM can omit it; the post-LLM `state.invoice.raw_text = loaded.text` line in `ingest.py` stays unchanged and remains the sole source of truth.

**Tests added:** `test_ingest_hydrates_raw_text_from_disk_when_llm_omits_it` — mock SDK returns JSON without a `raw_text` field; assert `run_ingest` succeeds and `state.invoice.raw_text == loaded.text`. Full suite **170 passed, 26 skipped**.

**Expected effect:** any ingest call's output is now bounded by the structured fields it actually produces (line items + suspicion signals + small metadata). For INV-9005 the per-attempt LLM latency should drop comfortably under the 30 s SDK timeout, so the failing run will succeed on its first attempt. Smaller-but-real win for every other invoice too — every ingest call saves the cost of echoing its own input back.

### Out of scope

- Surfacing partial progress (e.g., emitting a heartbeat to the run log mid-retry). Useful but unrelated to bounding latency.
- Making `_TOTAL_DEADLINE_S` configurable via settings. The 90s default is the natural ceiling given `_MAX_ATTEMPTS=3` × ~30s/call; can be lifted later if needed.

## 2026-05-13 — Grok client resilience

- Added retry + grok-3 fallback + typed exceptions in `GrokClient`
- API layer maps typed exceptions to clean strings (no "graph crashed:" prefix)
- Spec: `docs/superpowers/specs/2026-05-13-grok-resilience-design.md`
- Plan: `docs/superpowers/plans/2026-05-13-grok-resilience.md`
- 9 new unit tests in `test_grok_client.py`, 1 new integration test in `test_api.py`
- Post-review follow-up: `_run_investigate` in `approve.py` bypassed `structured_complete` via direct `run_tool_loop` call; same OpenAI → typed exception mapping added there with 2 new tests. Final suite: 164 passed, 26 skipped.

