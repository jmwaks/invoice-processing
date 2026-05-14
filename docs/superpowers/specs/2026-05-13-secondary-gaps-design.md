# Secondary Gaps from Adversarial Eval — Design

**Date:** 2026-05-13
**Status:** approved (brainstorming) — pending implementation plan
**Scope:** Three secondary gaps surfaced by the 9000-series adversarial fixtures that were previously flagged but deferred.

## Context

The adversarial eval surfaced four secondary gaps. One — `currency_mismatch` — is already closed by the current uncommitted diff (`validate.py:61-69`, `state.py` adds the kind, `test_validate_agent.py` adds two tests). This spec covers the remaining three:

1. **Price-drift boundary** (INV-9004): `drift > PRICE_TOLERANCE` excludes the exact-10% boundary case. 4 × $225 vs catalog $250 → drift = 0.10 exactly → not flagged.
2. **Homoglyph corruption** (INV-9001): `INV0ICE`, `INV-9OO1`, `2026-O2-O3` — letter/digit visual substitutions that pass extraction silently. Spec expects `needs_review`.
3. **Cross-batch duplicate invoices** (INV-9002): file `invoice_9002.txt` claims `invoice_number = "INV-1001"` with a different total. The current `pay.py:21` in-memory `set[str]` catches in-batch dups but does not survive across CLI runs, server restarts, or workers.

All three are bounded changes; none requires architectural redesign. They are bundled into one spec for thematic coherence but are independent at the code level.

---

## Gap 1 — Price-drift boundary

### Change

`backend/app/agents/validate.py:145` — `if drift > PRICE_TOLERANCE` becomes `if drift >= PRICE_TOLERANCE`.

### Rationale

`PRICE_TOLERANCE = 0.10` reads as "10% or more drift is suspicious." Exact 10% currently slips through. Aligning the operator with the constant's semantic meaning is a one-character fix.

### Test

New `test_price_mismatch_fires_at_exact_tolerance_boundary` in `backend/tests/test_validate_agent.py`. Uses INV-9004's exact numbers (4 × $225 vs catalog $250). Asserts `"price_mismatch"` is in the issue kinds.

### Side-effect audit

- `test_price_mismatch_warns` (existing): 4 × $100 vs $250 → drift = 0.60 → still True under `>=`. Passes unchanged.
- No other test exercises the boundary.

### Out of scope

- Changing the tolerance value.
- Asymmetric upper/lower bound.

---

## Gap 2 — Homoglyph detection (INV-9001)

Two-layer detection: LLM prompt update for fuzzy/contextual catches + deterministic post-check as a guaranteed floor.

### Layer A — Ingest prompt update

`backend/app/agents/ingest.py` `SYSTEM_PROMPT` gets a new suspicion-signal bullet:

> * **homoglyph corruption**: invoice numbers or dates where letters substitute for digits (`O`↔`0`, `l`↔`1`, `I`↔`1`, `B`↔`8`, `S`↔`5`, `Z`↔`2`), or the literal word "INVOICE" mangled (e.g. "INV0ICE"). Emit kind=`homoglyph_corruption` with `text_match` set to the exact corrupted token from the source.

### Layer B — Deterministic post-check

New module `backend/app/agents/homoglyph_check.py`:

```python
HOMOGLYPH_MAP = {"O": "0", "I": "1", "l": "1", "B": "8", "S": "5", "Z": "2"}

def detect_homoglyphs(inv: InvoiceData) -> list[SuspicionSignal]:
    """Scan invoice_number, date strings, and the top of raw_text for
    high-signal homoglyph substitutions. Returns suspicion signals.
    """
```

Scanned fields (each is a targeted, regex-bounded scan — **not** an unbounded character sweep of the whole document):

- `invoice_number`: after the first `-`, any uppercase Latin letter that maps via `HOMOGLYPH_MAP` is flagged. Bounded to the `invoice_number` field only.
- `raw_text` for header mangling: scan the **whole document** (not just the first 500 chars) for the specific literal tokens `INV0ICE`, `1NVOICE`, `INV01CE`, `INVO1CE`, `1NV0ICE`. These literals are themselves highly unusual; matching is by exact-substring not character-class, so false positives in long preambles, T&Cs, or multi-page headers are negligible.
- Date strings in `raw_text`: regex `\b\d{4}-[\dA-Z]{2}-[\dA-Z]{2}\b` matches date-shaped tokens (case-sensitive so `Jan-Feb-...` is not caught). For each match, flag only if a slot contains a homoglyph letter from `HOMOGLYPH_MAP`. This avoids the false-positive trap of sweeping every `O` and `l` in addresses or product names — the scan is constrained to date-shaped slots. We scan `raw_text` rather than `inv.date` because the LLM may "helpfully" correct `2026-O2-O3` to `2026-02-03` during extraction; only the raw source preserves the evidence.

**Extending the map:** `HOMOGLYPH_MAP` is a module-level dict, intentionally minimal. Adding pairs (e.g., `v↔u`, `rn↔m` for OCR-derived inputs) is a one-line change; explicitly out of scope for this PR to avoid widening false-positive surface area without test data to validate against.

Runs in `ingest.run_ingest` after `state.invoice` is hydrated and before the terminal `node.complete` emit. Appends to `state.suspicion_signals`, deduped against existing signals by `text_match` so we don't double-emit if the LLM already caught it.

### State model change

Add `"homoglyph_corruption"` to `SuspicionSignal.kind` literal in `backend/app/graph/state.py`. Using a dedicated kind (rather than the existing `"other"`) gives the rules engine and UI a stable hook.

### Severity

`medium`. Per `rules/engine.py:56` the rules engine sets `scrutiny=True` when `max_suspicion_severity >= medium`, which routes to `needs_review` via the approver. Matches `expected_outcomes.yaml:18` (`INV-9001: needs_review`).

### Tests

- New `backend/tests/test_homoglyph_check.py`: unit tests on `detect_homoglyphs`. Covers `INV-9OO1`, `2026-O2-O3` in raw_text, `INV0ICE` header, clean control case.
- Add to `backend/tests/test_ingest_agent.py`: integration test that runs `run_ingest` against INV-9001 with a mocked LLM returning **no** signals — assert the post-check still emits one. Proves Layer B is the floor independent of LLM behavior.

### Out of scope

- Auto-correcting corrupted values.
- Generalized OCR confusion pairs (m↔rn, etc.) — limited to the high-signal pairs in `HOMOGLYPH_MAP`.

---

## Gap 3 — Persistent dedup registry + retroactive flagging

The largest piece. Adds a SQLite-backed `paid_invoices` table, surfaces duplicate detection as a validation issue, and retroactively flags the prior invoice when a later duplicate arrives.

### 3.1 Storage

New table in `invoice_processing.db` (same DB that holds `inventory` and `vendors`):

```sql
CREATE TABLE IF NOT EXISTS paid_invoices (
    vendor_normalized TEXT NOT NULL,  -- output of normalize_vendor()
    invoice_number    TEXT NOT NULL,
    run_id            TEXT NOT NULL,
    vendor_display    TEXT,            -- raw vendor string as extracted, for UI/audit
    amount            REAL NOT NULL,
    paid_at           TEXT NOT NULL,   -- ISO8601 UTC
    PRIMARY KEY (vendor_normalized, invoice_number)
);
```

**Why a composite key:** different vendors routinely use overlapping invoice-number sequences (e.g., Vendor A and Vendor B both issue `INV-001`). A single-column PK on `invoice_number` would produce false-positive duplicate flags across distinct vendors. The first column is the **normalized** vendor name (lowercase, suffix-stripped, punctuation-stripped) via the existing `normalize_vendor()` helper in `init_db.py:30` — handles "Acme Corp" vs. "Acme Corporation" reliably without an LLM call.

**Vendor=None handling:** if `inv.vendor` is `None` or blank, we cannot form a valid dedup key. In that case:
- `record_paid` is skipped (the invoice would already have been blocked by `missing_vendor` validation; pay node only runs after approval, so this is a defensive guard).
- `_check_duplicate_invoice` returns `[]` (no dup signal). An info-level event `duplicate_check_skipped` is emitted with `reason="missing_vendor"` for traceability.

DDL added to `backend/app/db/init_db.py`. `IF NOT EXISTS` keeps existing dev DBs working — no migration script required.

### 3.2 Access layer

New module `backend/app/db/paid_invoices.py` with typed Pydantic models (CLAUDE.md: no raw dicts at boundaries):

```python
class PaidInvoiceRecord(BaseModel):
    vendor_normalized: str
    invoice_number: str
    run_id: str
    vendor_display: str | None
    amount: float
    paid_at: dt.datetime

def lookup_paid(
    *, vendor: str, invoice_number: str, db_path: Path,
) -> PaidInvoiceRecord | None:
    """Looks up by (normalize_vendor(vendor), invoice_number). Returns None on miss
    or when vendor is blank."""

def record_paid(record: PaidInvoiceRecord, *, db_path: Path) -> None:
    """INSERT OR IGNORE on the composite PK. Concurrent inserts of the same
    (vendor_normalized, invoice_number) are race-safe; the second writer is a no-op."""
```

`record_paid` uses `INSERT OR IGNORE` so concurrent writes for the same composite key are race-safe. Both helpers open the connection with **`sqlite3.connect(db_path, timeout=30.0)`** — the default 5-second timeout is too tight for multi-worker contention; matches the project's existing pattern of explicit timeouts on external/IO calls (per `tasks/lessons.md` "External API safety"). Both helpers manage their connection via `try/finally: conn.close()` per the codebase convention.

### 3.3 Validate-time duplicate check

New helper `_check_duplicate_invoice` in `backend/app/agents/validate.py`:

- If `lookup_paid(vendor=inv.vendor, invoice_number=inv.invoice_number, db_path=db_path)` returns a record, emit:
  ```
  ValidationIssue(
      kind="duplicate_invoice", severity="warn",
      detail=f"already paid in run {prior.run_id} for ${prior.amount:.2f} "
             f"on {prior.paid_at:%Y-%m-%d}; this submission is ${inv.total:.2f}",
  )
  ```
- Severity is always `warn` (not `block`). Routes via rules-engine `has_warn` → `scrutiny=True`, `auto_approve=False` → approver weighs the duplicate context and decides. Matches user requirement: `needs_review`, not auto-rejected.

Add `"duplicate_invoice"` to `ValidationIssue.kind` literal in `state.py`. Note: this is the **validation issue** kind; the **event** kind emitted for retroactive flagging (Section 3.5) is `"duplicate_detected_retroactive"`. These live in separate namespaces and are intentionally distinct names.

### 3.4 Pay-time persistence

`backend/app/agents/pay.py`:

- After `mock_payment` succeeds, construct `PaidInvoiceRecord` with `vendor_normalized=normalize_vendor(inv.vendor)`, `vendor_display=inv.vendor`, and call `record_paid(record, db_path=db_path)`. Skip the write when `inv.vendor` is `None`/blank (defensive — the run should have been blocked at validate by `missing_vendor`, but we don't want to crash if it slips through).
- Keep the existing `paid_invoices: set[str]` parameter for backwards-compat with current tests and same-process fast-path, but **the SQLite write is the source of truth**.
- The in-batch `if invoice_number in paid_invoices` check at `pay.py:21` is replaced by `if lookup_paid(vendor=inv.vendor, invoice_number=inv.invoice_number, db_path=db_path) is not None`. Single source of truth, no drift between in-memory and disk.
- `pay.py` will need `db_path` plumbed through (mirroring how `validate.py` already receives it). `build_graph` already has `db_path` in scope; add it to the `run_pay` partial.

### 3.5 Retroactive flagging of prior invoice

When `_check_duplicate_invoice` finds a prior record:

1. Resolve `prior_log_path = log_dir / f"{prior.run_id}.jsonl"`.
2. If the file exists, append one event:
   ```json
   {"kind": "duplicate_detected_retroactive", "ts": "<now>",
    "later_run_id": "<current>", "later_amount": <float>,
    "later_invoice_path": "<path>"}
   ```
3. Append an override record to a new sidecar file `<rejections_file.parent>/decision_updates.jsonl`:
   ```json
   {"run_id": "<prior>", "invoice_number": "INV-1001",
    "previous_outcome": "approved", "new_outcome": "needs_review",
    "reason": "duplicate_detected", "updated_at": "<now>",
    "triggered_by_run_id": "<current>"}
   ```
4. If the prior log file does not exist (different host, purged, etc.), emit `duplicate_detected_retroactive_skipped` on the current run with `reason="prior_log_not_found"`. Best-effort — never raises.

### 3.6 Sidecar vs. mutating `rejections.jsonl`

`rejections.jsonl` is an append-only chronological log of write events; mutating an existing record would break replay semantics. A separate `decision_updates.jsonl` keeps both files clean and lets UI/exports compose them via `effective_outcome` (below).

### 3.7 Effective-outcome composition

New helper in `backend/app/api/decisions.py` (new module — keeps `runs.py` focused on run lifecycle):

```python
class EffectiveOutcome(BaseModel):
    outcome: Literal["approved", "rejected", "needs_review", "unprocessable"]
    override_reason: str | None
    overridden_at: dt.datetime | None
    triggered_by_run_id: str | None

def effective_outcome(run_id: str, log_dir: Path) -> EffectiveOutcome:
    """Returns the effective outcome for a run. Reads the latest matching entry
    from decision_updates.jsonl; falls back to the Decision recorded in the
    run's jsonl event log. override_reason/overridden_at/triggered_by_run_id
    are None when there is no retroactive override."""
```

**API surface:** `GET /runs/{run_id}` response gains an `effective_outcome` block:

```json
{
  "run_id": "...",
  "decision": { "outcome": "approved", ... },
  "effective_outcome": {
    "outcome": "needs_review",
    "override_reason": "duplicate_detected",
    "overridden_at": "2026-05-13T15:32:00Z",
    "triggered_by_run_id": "abc123..."
  }
}
```

When there is no override, `effective_outcome.outcome` equals `decision.outcome` and the other three fields are `null`. Stable contract for the frontend — no need to read `decision_updates.jsonl` directly from the UI.

**Used by:**

- `GET /runs/{run_id}` to surface the override in API responses.
- Test-harness assertions against `expected_outcomes.yaml`.

### 3.8 Replay safety

`app/tools/replay.py:11-44` is **read-only**: it reads the run's jsonl, counts events, and prints a summary. It does **not** re-invoke the graph or hit the database, so the persistent dedup registry has no effect on replay. The new `duplicate_detected_retroactive` event must not crash the event walker, but the current loop already iterates by `e.get("kind")` and only inspects specific kinds — unknown kinds are silently skipped. A small regression test confirms this for the new event kind.

**`/runs/{run_id}/retry` endpoint** (a different code path that re-executes the graph from a seeded state) **will** hit the new dedup check. This is correct behavior: if the original invoice was paid, the retry is by definition a duplicate, and surfacing that is the point of the check. Documented here so the test plan covers it.

### 3.9 Expected outcomes update

`backend/tests/expected_outcomes.yaml`:

- `INV-9002`: `{ outcome: approved }` → `{ outcome: needs_review, requires: [duplicate_invoice] }`.
- `INV-1001`: `{ outcome: approved }` stays as the **at-time** outcome (it was approved when processed; dup hadn't happened yet).
- Add an `effective_outcomes` map at the bottom for post-retroactive expectations:
  ```yaml
  effective_outcomes:
    INV-1001: { outcome: needs_review, override_reason: duplicate_detected }
  ```
  Test harness asserts both `outcome` (from Decision) and `effective_outcome` (from the composer).

### 3.10 Tests

**Unit:**

- `backend/tests/test_paid_invoices.py`:
  - lookup miss returns None
  - record-then-lookup returns the record
  - composite-key isolation: same `invoice_number` recorded under two different `vendor_normalized` values → both retrievable, no collision
  - vendor normalization parity: looking up with raw "Acme Corp" hits a row recorded with "Acme Corporation"
  - vendor=None/blank → `lookup_paid` returns None, `record_paid` is a no-op
  - `INSERT OR IGNORE` semantics: second insert of same composite key is a no-op, first row preserved
  - `init_db` creates the table on a fresh DB; running it on an existing DB with the table is idempotent

- `backend/tests/test_validate_agent.py` additions:
  - `test_duplicate_invoice_warns_when_registry_has_prior` — seed the registry, run validate with same (vendor, invoice_number), assert `duplicate_invoice` issue with `severity=warn`.
  - `test_duplicate_invoice_does_not_fire_for_different_vendor` — seed the registry under Vendor A, run validate with same `invoice_number` but Vendor B, assert NO `duplicate_invoice` issue (regression test for the composite-key fix).

- `backend/tests/test_replay.py` addition:
  - `test_replay_tolerates_duplicate_detected_retroactive_event` — write a jsonl with the new event kind, replay, assert no crash and summary fields are unchanged.

**Integration:**

- `backend/tests/test_pay.py` additions:
  - `test_pay_persists_to_registry` — run pay, assert `lookup_paid` returns the record.

- `backend/tests/test_integration.py` (or new `test_cross_batch_dedup.py`):
  - `test_cross_batch_dedup_retroactive_flag` — process INV-1001 through full graph (approved, paid, registry row written); then process INV-9002 through a fresh graph build (separate `paid_invoices=set()` to simulate cross-batch); assert (a) INV-9002 has `duplicate_invoice` issue and `needs_review` outcome; (b) INV-1001's jsonl has the `duplicate_detected_retroactive` event; (c) `decision_updates.jsonl` contains the override row; (d) `effective_outcome(INV-1001 run_id)` returns `("needs_review", "duplicate_detected")`.

### 3.11 Known limitations & out of scope

**Known limitations (accepted for this PR, document for ops):**

- **Validate-time race window.** If two workers process the same (vendor, invoice_number) simultaneously, both may pass `_check_duplicate_invoice` before either reaches `pay`. The first-to-pay wins via `INSERT OR IGNORE`; the second-to-pay no-ops at the registry level (no double payment) but its run records `approved` without a `duplicate_invoice` warning. Mitigation if this becomes operationally painful: introduce a `pending_invoices` registry written at validate-time and reconciled at pay-time. Not built here because the user explicitly accepted this edge case.
- **Registry maintenance on data corrections.** If a run record is deleted out-of-band, the corresponding `paid_invoices` row is not auto-cleaned and will continue to flag future submissions as duplicates. **Manual remediation** for now:
  ```sql
  DELETE FROM paid_invoices
   WHERE vendor_normalized = ? AND invoice_number = ?;
  ```
  A formal corrections API is a separate feature.

**Out of scope:**

- Refund/delta payment logic. `pay.py` still no-ops on dup; no refunds issued.
- Removing the in-memory `paid_invoices: set[str]` parameter from `build_graph`. Keep it for backwards-compat; it shadows the SQL check.
- UI surfacing of retroactive flags. Backend emits the data and the `effective_outcome` block (§3.7); frontend integration is a follow-up.
- Extending `HOMOGLYPH_MAP` with OCR pairs (`v↔u`, `rn↔m`) — see Layer B note in §Gap 2.

---

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Concurrent writes from multiple workers hitting the same `invoice_number` | `INSERT OR IGNORE` + PK; second writer no-ops, sees the prior on next read. |
| `lookup_paid` adds latency to every validate call | One indexed PK lookup per invoice; negligible. Reuse short-lived connection per call. |
| Retroactive write to a missing prior log file | Best-effort; emit `..._skipped` event with reason. No crash. |
| Replay across older run logs encountering the new event kind | Add regression test that replay tolerates unknown kinds. |
| Existing tests break because `paid_invoices` set no longer authoritative | Keep set parameter; SQL is source-of-truth, set is fast-path. Run full suite before merge. |
| Homoglyph post-check false positives on legitimate alphanumeric IDs | `HOMOGLYPH_MAP` is restricted to high-signal pairs and only triggers in invoice_number/date slots. Severity is `medium` (review, not block). |

## Touched files (summary)

| File | Change |
|---|---|
| `backend/app/agents/validate.py` | `>` → `>=` for price drift; new `_check_duplicate_invoice` helper |
| `backend/app/agents/ingest.py` | Prompt update; call new `detect_homoglyphs` post-extraction |
| `backend/app/agents/homoglyph_check.py` | **new** — deterministic detection helper |
| `backend/app/agents/pay.py` | Persist `PaidInvoiceRecord` on success; lookup via SQL |
| `backend/app/db/init_db.py` | Add `PAID_INVOICES_DDL` |
| `backend/app/db/paid_invoices.py` | **new** — typed accessors |
| `backend/app/api/decisions.py` | **new** — `effective_outcome` composer |
| `backend/app/graph/state.py` | Add `duplicate_invoice` to `ValidationIssue.kind`; add `homoglyph_corruption` to `SuspicionSignal.kind` |
| `backend/tests/expected_outcomes.yaml` | INV-9002 → needs_review; new `effective_outcomes` block |
| `backend/tests/test_validate_agent.py` | Boundary + duplicate-invoice tests |
| `backend/tests/test_homoglyph_check.py` | **new** — unit tests |
| `backend/tests/test_ingest_agent.py` | Integration test for Layer B floor |
| `backend/tests/test_paid_invoices.py` | **new** — table semantics |
| `backend/tests/test_pay.py` | Persistence assertion |
| `backend/tests/test_integration.py` (or new) | Cross-batch retroactive flag test |
