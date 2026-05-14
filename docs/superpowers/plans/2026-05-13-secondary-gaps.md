# Secondary Gaps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-05-13-secondary-gaps-design.md`

**Goal:** Close three secondary gaps surfaced by the 9000-series adversarial fixtures — price-drift boundary, homoglyph corruption detection, and persistent cross-batch duplicate-invoice registry.

**Architecture:** Three independent code-level changes bundled in one plan. Gap 1 is a one-character operator change in `validate.py` plus a regression test. Gap 2 adds a deterministic `homoglyph_check.py` helper called from `run_ingest`, alongside an ingest-prompt update; the post-check is the guaranteed floor. Gap 3 adds a SQLite-backed `paid_invoices` table with composite `(vendor_normalized, invoice_number)` PK, a validate-time duplicate check emitting a new `duplicate_invoice` issue, a pay-time persist, and retroactive flagging of the prior run via append-only `decision_updates.jsonl` plus an `effective_outcome` composer surfaced on `GET /runs/{run_id}`.

**Tech Stack:** Python 3.11, Pydantic 2, SQLite, pytest, FastAPI, LangGraph. mypy `--strict` is on — every new function needs full type annotations.

---

## Environment setup (one-time, before Task 1)

All commands assume the project venv is active and CWD is `backend/`:

```bash
cd /Users/mwakichako/repos/invoice-processing
source .venv/bin/activate     # or: . .venv/bin/activate
cd backend
```

If the venv does not exist, create it first:
```bash
cd /Users/mwakichako/repos/invoice-processing
python3.11 -m venv .venv
source .venv/bin/activate
cd backend && pip install -e ".[dev]"
```

`pytest` resolves modules from `backend/` because `pyproject.toml` lives there. Run all test commands from `backend/`.

---

## File Structure

| Path | Status | Responsibility |
|---|---|---|
| `backend/app/agents/validate.py` | modify | Boundary operator + new `_check_duplicate_invoice` helper |
| `backend/app/agents/ingest.py` | modify | Prompt bullet + call `detect_homoglyphs` after extraction |
| `backend/app/agents/homoglyph_check.py` | **create** | Pure-function deterministic homoglyph detector |
| `backend/app/agents/pay.py` | modify | Accept `db_path`, persist `PaidInvoiceRecord` on success |
| `backend/app/db/init_db.py` | modify | Add `PAID_INVOICES_DDL` |
| `backend/app/db/paid_invoices.py` | **create** | Typed `lookup_paid` / `record_paid` accessors |
| `backend/app/api/decisions.py` | **create** | `EffectiveOutcome` model + `effective_outcome` composer |
| `backend/app/api/routes.py` | modify | Include `effective_outcome` in `GET /runs/{run_id}` |
| `backend/app/graph/state.py` | modify | Add `duplicate_invoice` to `ValidationIssue.kind`; add `homoglyph_corruption` to `SuspicionSignal.kind` |
| `backend/app/graph/builder.py` | modify | Plumb `db_path` into `pay_node` |
| `backend/tests/test_validate_agent.py` | modify | Boundary + duplicate-invoice tests |
| `backend/tests/test_homoglyph_check.py` | **create** | Unit tests for `detect_homoglyphs` |
| `backend/tests/test_ingest_agent.py` | modify | Integration test for Layer B floor |
| `backend/tests/test_paid_invoices.py` | **create** | Table + accessor tests |
| `backend/tests/test_pay.py` | modify | Pay-time persistence assertion |
| `backend/tests/test_replay.py` | modify | Replay tolerates new event kind |
| `backend/tests/test_api.py` | modify | `effective_outcome` block in GET response |
| `backend/tests/test_cross_batch_dedup.py` | **create** | End-to-end retroactive flag test |
| `backend/tests/expected_outcomes.yaml` | modify | INV-9002 → needs_review; new `effective_outcomes` block |

---

## Task 1: Price-drift boundary fix

**Files:**
- Modify: `backend/app/agents/validate.py:145`
- Test: `backend/tests/test_validate_agent.py`

- [ ] **Step 1: Add a failing regression test**

Append to `backend/tests/test_validate_agent.py`:

```python
def test_price_mismatch_fires_at_exact_tolerance_boundary(tmp_path: Path):
    # INV-9004's exact numbers: 4 × $225 vs catalog $250 = drift exactly 10%.
    # `drift > PRICE_TOLERANCE` excludes this boundary; `drift >= PRICE_TOLERANCE`
    # catches it. Semantic intent of `PRICE_TOLERANCE = 0.10` is "10% or more".
    db = _seeded(tmp_path)
    state = _state(_inv(
        line_items=[LineItem(item="WidgetA", quantity=4, unit_price=225.0)],
        total=900.0,
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    kinds = {i.kind for i in out.validation.issues}
    assert "price_mismatch" in kinds
```

- [ ] **Step 2: Run test to confirm it FAILS**

```bash
pytest tests/test_validate_agent.py::test_price_mismatch_fires_at_exact_tolerance_boundary -v
```
Expected: FAIL — `AssertionError: 'price_mismatch' not in <set of kinds>`. The drift is exactly `0.10`, and `0.10 > 0.10` is False under the current operator.

- [ ] **Step 3: Change the operator**

In `backend/app/agents/validate.py` find:
```python
            drift = abs(li.unit_price - lookup.unit_price) / lookup.unit_price
            if drift > PRICE_TOLERANCE:
```
Change `>` to `>=`:
```python
            drift = abs(li.unit_price - lookup.unit_price) / lookup.unit_price
            if drift >= PRICE_TOLERANCE:
```

- [ ] **Step 4: Run new test + the existing price-mismatch test**

```bash
pytest tests/test_validate_agent.py::test_price_mismatch_fires_at_exact_tolerance_boundary tests/test_validate_agent.py::test_price_mismatch_warns -v
```
Expected: both PASS. `test_price_mismatch_warns` exercises drift = 0.60, still True under `>=`.

- [ ] **Step 5: Run full validate-agent suite to catch regressions**

```bash
pytest tests/test_validate_agent.py -v
```
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/agents/validate.py backend/tests/test_validate_agent.py
git commit -m "fix(validate): price drift fires at exact 10% boundary

PRICE_TOLERANCE = 0.10 reads as 10%-or-more drift is suspicious, but
the operator was strict >. INV-9004 (4 x \$225 vs catalog \$250) sits
exactly on the boundary and was silently passing. Flip to >= so the
operator matches the semantic intent of the constant.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: Add `homoglyph_corruption` to `SuspicionSignal.kind`

**Files:**
- Modify: `backend/app/graph/state.py:31-38`
- Test: `backend/tests/test_state_models.py` (existing — verify no breakage)

- [ ] **Step 1: Extend the Literal**

In `backend/app/graph/state.py`, find the `SuspicionSignal.kind` definition:

```python
class SuspicionSignal(BaseModel):
    kind: Literal[
        "urgent_language",
        "impossible_date",
        "round_number",
        "unknown_vendor_pattern",
        "wire_transfer_demand",
        "other",
    ]
```

Add `"homoglyph_corruption"` to the literal (placed before `"other"` to keep `"other"` as the catch-all sentinel):

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

- [ ] **Step 2: Run state-model tests**

```bash
pytest tests/test_state_models.py -v
```
Expected: PASS (no existing tests pin the literal length).

- [ ] **Step 3: Run mypy strict on `app/`**

```bash
mypy app
```
Expected: PASS. No call sites pattern-match against the literal.

- [ ] **Step 4: Commit (defer — bundle with Task 5)**

This is a non-functional schema addition. Hold the commit until Task 5 ties it to a caller.

---

## Task 3: Create `homoglyph_check.py` (TDD)

**Files:**
- Create: `backend/app/agents/homoglyph_check.py`
- Test: `backend/tests/test_homoglyph_check.py` (**create**)

- [ ] **Step 1: Write the failing unit-test file**

Create `backend/tests/test_homoglyph_check.py`:

```python
from app.agents.homoglyph_check import detect_homoglyphs
from app.graph.state import InvoiceData, LineItem


def _inv(**kw: object) -> InvoiceData:
    base: dict[str, object] = dict(
        invoice_number="INV-1001", vendor="Widgets Inc.",
        date=None, due_date=None, line_items=[],
        subtotal=None, tax_amount=None, total=None,
        currency="USD", payment_terms=None, raw_text="",
    )
    base.update(kw)
    return InvoiceData(**base)  # type: ignore[arg-type]


def test_clean_invoice_emits_no_signal() -> None:
    inv = _inv(
        invoice_number="INV-1001",
        raw_text="INVOICE\nInvoice Number: INV-1001\nDate: 2026-02-03\n",
    )
    assert detect_homoglyphs(inv) == []


def test_invoice_number_with_O_for_0_is_flagged() -> None:
    inv = _inv(
        invoice_number="INV-9OO1",
        raw_text="INVOICE\nInvoice Number: INV-9OO1\nDate: 2026-02-03\n",
    )
    signals = detect_homoglyphs(inv)
    assert any(
        s.kind == "homoglyph_corruption" and "INV-9OO1" in (s.text_match or "")
        for s in signals
    )


def test_header_INV0ICE_is_flagged() -> None:
    inv = _inv(
        invoice_number="INV-1001",
        raw_text="INV0ICE\nInvoice Number: INV-1001\nDate: 2026-02-03\n",
    )
    signals = detect_homoglyphs(inv)
    assert any(
        s.kind == "homoglyph_corruption" and (s.text_match or "") == "INV0ICE"
        for s in signals
    )


def test_date_with_O_in_raw_text_is_flagged() -> None:
    inv = _inv(
        invoice_number="INV-1001",
        raw_text="INVOICE\nInvoice Number: INV-1001\nDate: 2026-O2-O3\n",
    )
    signals = detect_homoglyphs(inv)
    assert any(
        s.kind == "homoglyph_corruption" and "2026-O2-O3" in (s.text_match or "")
        for s in signals
    )


def test_date_without_homoglyph_is_not_flagged() -> None:
    inv = _inv(
        invoice_number="INV-1001",
        raw_text="INVOICE\nInvoice Number: INV-1001\nDate: 2026-02-03\nDue: 2026-03-03\n",
    )
    signals = detect_homoglyphs(inv)
    assert not any(s.kind == "homoglyph_corruption" for s in signals)


def test_legitimate_O_in_vendor_address_not_flagged() -> None:
    # Vendor address with capital O's must not produce a homoglyph signal —
    # the scan is scoped to invoice_number / date-shaped tokens / specific header literals.
    inv = _inv(
        invoice_number="INV-1001",
        vendor="OAKWOOD HOLDINGS LLC",
        raw_text=(
            "INVOICE\nInvoice Number: INV-1001\n"
            "Vendor: OAKWOOD HOLDINGS LLC\nAddress: 100 OAK ROAD\n"
            "Date: 2026-02-03\n"
        ),
    )
    assert detect_homoglyphs(inv) == []


def test_dedup_by_text_match_does_not_double_emit() -> None:
    # Same homoglyph appears in both invoice_number and date-shaped token; we expect
    # at most one signal per distinct text_match (the caller dedups against existing
    # signals as well, but the helper itself should not emit two copies of the same match).
    inv = _inv(
        invoice_number="INV-1OO1",
        raw_text="INVOICE\nInvoice Number: INV-1OO1\nDate: 2026-02-03\n",
    )
    signals = detect_homoglyphs(inv)
    text_matches = [s.text_match for s in signals if s.kind == "homoglyph_corruption"]
    assert len(text_matches) == len(set(text_matches))
```

- [ ] **Step 2: Run tests — they all FAIL because the module does not exist**

```bash
pytest tests/test_homoglyph_check.py -v
```
Expected: collection error / ImportError on `app.agents.homoglyph_check`.

- [ ] **Step 3: Create the module**

Create `backend/app/agents/homoglyph_check.py`:

```python
from __future__ import annotations

import re

from app.graph.state import InvoiceData, SuspicionSignal

HOMOGLYPH_MAP: dict[str, str] = {
    "O": "0",
    "I": "1",
    "l": "1",
    "B": "8",
    "S": "5",
    "Z": "2",
}

# Specific literal tokens that indicate a mangled "INVOICE" header.
# Substring match on raw_text — these literals are unusual enough that
# whole-document scanning has negligible false-positive risk.
_HEADER_MANGLINGS: tuple[str, ...] = (
    "INV0ICE", "1NVOICE", "INV01CE", "INVO1CE", "1NV0ICE",
)

# Matches date-shaped tokens (case-sensitive, so month abbreviations like
# "Jan-Feb" are not caught). The character class includes A-Z so we can
# inspect each slot for a homoglyph letter.
_DATE_SHAPED_RE = re.compile(r"\b\d{4}-[\dA-Z]{2}-[\dA-Z]{2}\b")


def _has_homoglyph(token: str) -> bool:
    return any(c in HOMOGLYPH_MAP for c in token)


def _invoice_number_id_part(invoice_number: str) -> str:
    """Return the part of an invoice number after the first '-', or the whole
    string if there is no '-'."""
    if "-" not in invoice_number:
        return invoice_number
    return invoice_number.split("-", 1)[1]


def detect_homoglyphs(inv: InvoiceData) -> list[SuspicionSignal]:
    """Scan an extracted invoice for homoglyph corruption (O <-> 0, l <-> 1, etc.)
    in invoice_number, header word, and date-shaped tokens. Returns a list of
    SuspicionSignal entries with kind='homoglyph_corruption'. Empty list when clean.

    The scan is scoped: invoice_number's id part, specific INVOICE-header
    manglings, and date-shaped tokens. It deliberately avoids unbounded
    character-class scanning of the entire document to keep false-positive
    surface area minimal.
    """
    signals: list[SuspicionSignal] = []
    seen: set[str] = set()

    def _emit(text_match: str, detail: str) -> None:
        if text_match in seen:
            return
        seen.add(text_match)
        signals.append(SuspicionSignal(
            kind="homoglyph_corruption",
            detail=detail,
            severity="medium",
            text_match=text_match,
        ))

    if inv.invoice_number:
        id_part = _invoice_number_id_part(inv.invoice_number)
        if _has_homoglyph(id_part):
            _emit(
                inv.invoice_number,
                f"invoice_number {inv.invoice_number!r} contains characters that "
                f"visually resemble digits (homoglyphs): "
                f"{sorted(set(c for c in id_part if c in HOMOGLYPH_MAP))}",
            )

    raw = inv.raw_text or ""
    for token in _HEADER_MANGLINGS:
        if token in raw:
            _emit(
                token,
                f"document header contains {token!r}, a homoglyph-mangled "
                f"version of 'INVOICE'",
            )

    for match in _DATE_SHAPED_RE.finditer(raw):
        token = match.group(0)
        if _has_homoglyph(token):
            _emit(
                token,
                f"date-shaped token {token!r} contains characters that visually "
                f"resemble digits (homoglyphs)",
            )

    return signals
```

- [ ] **Step 4: Run tests — all should now PASS**

```bash
pytest tests/test_homoglyph_check.py -v
```
Expected: 7 PASSED.

- [ ] **Step 5: Run mypy on the new module**

```bash
mypy app/agents/homoglyph_check.py
```
Expected: PASS, no errors.

- [ ] **Step 6: Commit (defer to Task 5)**

The module is unused until Task 5 wires it in. Hold the commit.

---

## Task 4: Update ingest `SYSTEM_PROMPT` for homoglyph signal

**Files:**
- Modify: `backend/app/agents/ingest.py:31-36`

- [ ] **Step 1: Edit the prompt**

In `backend/app/agents/ingest.py`, find the suspicion-signal bullet list inside `SYSTEM_PROMPT`:

```python
- Flag suspicion signals for any of:
  * urgent / threatening language ("URGENT", "pay immediately", "wire transfer")
  * dates in the past or expressed as "yesterday"
  * round-number totals on otherwise odd line items
  * generic or alarming vendor names
  * unknown / made-up looking item names
```

Append the new bullet:

```python
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
```

- [ ] **Step 2: Add `"homoglyph_corruption"` to the JSON-schema doc comment if it lists kinds**

Inspect the JSON schema block at `ingest.py:43-53`. The schema description does not enumerate `kind` values, so no further change is needed. (Verify by reading the file; if a list exists, add the new value.)

- [ ] **Step 3: No automated test runs against the live prompt**

The prompt change is exercised end-to-end only against a real LLM. The deterministic post-check (Task 5) is the floor that guarantees the signal even if the LLM misses it.

- [ ] **Step 4: Commit (defer to Task 5)**

Hold for bundling.

---

## Task 5: Wire `detect_homoglyphs` into `run_ingest` (integration test + commit)

**Files:**
- Modify: `backend/app/agents/ingest.py:98-114`
- Test: `backend/tests/test_ingest_agent.py`

- [ ] **Step 1: Write the failing integration test**

Append to `backend/tests/test_ingest_agent.py` (preserve existing imports; add `MagicMock` if not already present):

```python
def test_homoglyph_post_check_emits_signal_even_when_llm_misses_it(tmp_path: Path) -> None:
    """Layer B is the floor: even if the LLM returns no suspicion_signals,
    the deterministic post-check must add one for an obviously corrupted invoice."""
    from unittest.mock import MagicMock
    from app.agents.ingest import IngestResponse, run_ingest
    from app.graph.state import InvoiceData, InvoiceState, LineItem
    from app.llm.grok_client import CallMeta
    from app.logging_.event_emitter import EventEmitter

    raw = (
        "INV0ICE\n"
        "Vendor: Atlas Industrial Supply\n"
        "Invoice Number: INV-9OO1\n"
        "Date: 2026-O2-O3\nDue Date: 2026-03-03\n"
        "Items:\n  Widget A    qty: 5    unit price: $250\nTotal: $1,250\n"
    )
    source = tmp_path / "invoice_9001.txt"
    source.write_text(raw)

    fake_llm = MagicMock()
    fake_llm.structured_complete.return_value = (
        IngestResponse(
            invoice=InvoiceData(
                invoice_number="INV-9OO1",
                vendor="Atlas Industrial Supply",
                date=None, due_date=None,
                line_items=[LineItem(item="Widget A", quantity=5, unit_price=250.0)],
                subtotal=None, tax_amount=None, total=1250.0,
                currency="USD", payment_terms="Net 30",
                raw_text=raw,
            ),
            suspicion_signals=[],
            extraction_confidence=0.9,
        ),
        CallMeta(tokens_in=100, tokens_out=50, latency_ms=120, model="stub"),
    )

    state = InvoiceState(
        run_id="r", source_path=str(source), file_format="txt",
    )
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_ingest(state, llm=fake_llm, emitter=emitter)

    kinds = [s.kind for s in out.suspicion_signals]
    assert "homoglyph_corruption" in kinds, (
        f"expected post-check to emit homoglyph_corruption, got {kinds}"
    )
```

- [ ] **Step 2: Run test — should FAIL**

```bash
pytest tests/test_ingest_agent.py::test_homoglyph_post_check_emits_signal_even_when_llm_misses_it -v
```
Expected: FAIL — `homoglyph_corruption` not in returned signals (post-check not yet wired in).

- [ ] **Step 3: Wire the post-check into `run_ingest`**

In `backend/app/agents/ingest.py`, add the import near the top with other `from app.*` imports:

```python
from app.agents.homoglyph_check import detect_homoglyphs
```

Then in `run_ingest`, after the line `state.suspicion_signals = parsed.suspicion_signals` (around `ingest.py:100`) and before the terminal `node.complete` emit, splice in the floor-check:

```python
    state.invoice = InvoiceData(**parsed.invoice.model_dump())
    state.invoice.raw_text = loaded.text
    state.suspicion_signals = parsed.suspicion_signals

    # Deterministic floor: ensure obvious homoglyph corruption is always flagged,
    # even if the LLM did not catch it. Dedup against signals the LLM already produced
    # so we do not double-emit the same text_match.
    existing_matches = {s.text_match for s in state.suspicion_signals if s.text_match}
    for sig in detect_homoglyphs(state.invoice):
        if sig.text_match in existing_matches:
            continue
        state.suspicion_signals.append(sig)
        existing_matches.add(sig.text_match)

    state.extraction_confidence = parsed.extraction_confidence
```

- [ ] **Step 4: Run integration test — should PASS**

```bash
pytest tests/test_ingest_agent.py::test_homoglyph_post_check_emits_signal_even_when_llm_misses_it -v
```
Expected: PASS.

- [ ] **Step 5: Run full ingest + homoglyph suites**

```bash
pytest tests/test_ingest_agent.py tests/test_homoglyph_check.py -v
```
Expected: all PASS.

- [ ] **Step 6: Run mypy strict**

```bash
mypy app
```
Expected: PASS.

- [ ] **Step 7: Commit Gap 2 as one logical change (Tasks 2-5)**

```bash
git add backend/app/agents/homoglyph_check.py \
        backend/app/agents/ingest.py \
        backend/app/graph/state.py \
        backend/tests/test_homoglyph_check.py \
        backend/tests/test_ingest_agent.py
git commit -m "feat(ingest): two-layer homoglyph corruption detection

INV-9001 ships obviously corrupted strings (INV-9OO1, 2026-O2-O3, INV0ICE).
Adds a deterministic post-extract floor in app/agents/homoglyph_check.py that
scans invoice_number, date-shaped tokens in raw_text, and specific
INVOICE-header manglings. Prompt also gains a bullet so the LLM can flag
contextual cases the regex would miss; the post-check dedups against LLM
signals via text_match so we do not double-emit.

Adds homoglyph_corruption to SuspicionSignal.kind. severity=medium routes
the run to scrutiny via the rules engine, matching expected_outcomes.yaml
(INV-9001: needs_review).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Add `paid_invoices` table to `init_db.py`

**Files:**
- Modify: `backend/app/db/init_db.py:10-24,43`
- Test: `backend/tests/test_db_init.py` (existing — verify; otherwise covered by Task 7)

- [ ] **Step 1: Add the DDL constant**

In `backend/app/db/init_db.py`, after `VENDORS_DDL`, add:

```python
PAID_INVOICES_DDL = """
CREATE TABLE IF NOT EXISTS paid_invoices (
    vendor_normalized TEXT NOT NULL,
    invoice_number    TEXT NOT NULL,
    run_id            TEXT NOT NULL,
    vendor_display    TEXT,
    amount            REAL NOT NULL,
    paid_at           TEXT NOT NULL,
    PRIMARY KEY (vendor_normalized, invoice_number)
);
"""
```

- [ ] **Step 2: Include it in `executescript`**

Find the line `conn.executescript(INVENTORY_DDL + VENDORS_DDL)` and change to:

```python
        conn.executescript(INVENTORY_DDL + VENDORS_DDL + PAID_INVOICES_DDL)
```

- [ ] **Step 3: Verify init_db still passes**

```bash
pytest tests/test_db_init.py -v
```
Expected: PASS (`CREATE TABLE IF NOT EXISTS` is idempotent and the existing tests do not query `paid_invoices`).

- [ ] **Step 4: Commit (defer — bundle with Task 7)**

---

## Task 7: Create `app/db/paid_invoices.py` (TDD)

**Files:**
- Create: `backend/app/db/paid_invoices.py`
- Test: `backend/tests/test_paid_invoices.py` (**create**)

- [ ] **Step 1: Write the failing test file**

Create `backend/tests/test_paid_invoices.py`:

```python
import datetime as dt
from pathlib import Path

import pytest

from app.db.paid_invoices import (
    PaidInvoiceRecord,
    lookup_paid,
    record_paid,
)

_NOW = dt.datetime(2026, 5, 13, 12, 0, tzinfo=dt.UTC)


def _record(
    invoice_number: str = "INV-1001",
    vendor_display: str = "Widgets Inc.",
    amount: float = 1250.0,
    run_id: str = "r1",
) -> PaidInvoiceRecord:
    from app.db.init_db import normalize_vendor
    return PaidInvoiceRecord(
        vendor_normalized=normalize_vendor(vendor_display),
        invoice_number=invoice_number,
        run_id=run_id,
        vendor_display=vendor_display,
        amount=amount,
        paid_at=_NOW,
    )


def test_lookup_miss_returns_none(seeded_db_path: Path) -> None:
    assert lookup_paid(
        vendor="Widgets Inc.", invoice_number="INV-1001", db_path=seeded_db_path,
    ) is None


def test_record_then_lookup_returns_record(seeded_db_path: Path) -> None:
    record_paid(_record(), db_path=seeded_db_path)
    got = lookup_paid(
        vendor="Widgets Inc.", invoice_number="INV-1001", db_path=seeded_db_path,
    )
    assert got is not None
    assert got.invoice_number == "INV-1001"
    assert got.amount == 1250.0
    assert got.run_id == "r1"


def test_composite_key_isolates_by_vendor(seeded_db_path: Path) -> None:
    # Same invoice_number under two different vendors must NOT collide.
    record_paid(_record(vendor_display="Vendor A", run_id="r1"), db_path=seeded_db_path)
    record_paid(_record(vendor_display="Vendor B", run_id="r2"), db_path=seeded_db_path)
    a = lookup_paid(vendor="Vendor A", invoice_number="INV-1001", db_path=seeded_db_path)
    b = lookup_paid(vendor="Vendor B", invoice_number="INV-1001", db_path=seeded_db_path)
    assert a is not None and a.run_id == "r1"
    assert b is not None and b.run_id == "r2"


def test_vendor_normalization_parity(seeded_db_path: Path) -> None:
    # "Acme Corp" and "Acme Corporation" must collide via normalize_vendor.
    record_paid(_record(vendor_display="Acme Corp", run_id="r1"), db_path=seeded_db_path)
    got = lookup_paid(
        vendor="Acme Corporation", invoice_number="INV-1001", db_path=seeded_db_path,
    )
    assert got is not None
    assert got.run_id == "r1"


def test_vendor_blank_lookup_returns_none(seeded_db_path: Path) -> None:
    record_paid(_record(), db_path=seeded_db_path)
    assert lookup_paid(vendor="", invoice_number="INV-1001", db_path=seeded_db_path) is None
    assert lookup_paid(vendor="   ", invoice_number="INV-1001", db_path=seeded_db_path) is None


def test_insert_or_ignore_preserves_first(seeded_db_path: Path) -> None:
    record_paid(_record(amount=1250.0, run_id="r1"), db_path=seeded_db_path)
    # Second insert for same composite key must be a no-op (first row preserved).
    record_paid(_record(amount=9999.0, run_id="r2"), db_path=seeded_db_path)
    got = lookup_paid(
        vendor="Widgets Inc.", invoice_number="INV-1001", db_path=seeded_db_path,
    )
    assert got is not None
    assert got.amount == 1250.0
    assert got.run_id == "r1"


def test_init_db_idempotent_on_existing_table(seeded_db_path: Path) -> None:
    # Running init_db a second time against an already-initialized DB must not raise.
    from app.db.init_db import init_db
    seed = Path(__file__).resolve().parent.parent / "app" / "db" / "seed.yaml"
    init_db(seeded_db_path, seed_path=seed, reset=False)
    # And paid_invoices is queryable.
    assert lookup_paid(
        vendor="Widgets Inc.", invoice_number="INV-1001", db_path=seeded_db_path,
    ) is None
```

- [ ] **Step 2: Run tests — all FAIL on ImportError**

```bash
pytest tests/test_paid_invoices.py -v
```
Expected: collection error — `app.db.paid_invoices` does not exist.

- [ ] **Step 3: Create the accessor module**

Create `backend/app/db/paid_invoices.py`:

```python
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

from pydantic import BaseModel

from app.db.init_db import normalize_vendor

_DB_TIMEOUT = 30.0  # seconds; covers multi-worker contention windows


class PaidInvoiceRecord(BaseModel):
    vendor_normalized: str
    invoice_number: str
    run_id: str
    vendor_display: str | None
    amount: float
    paid_at: dt.datetime


def _connect(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(db_path, timeout=_DB_TIMEOUT)


def lookup_paid(
    *, vendor: str | None, invoice_number: str, db_path: Path,
) -> PaidInvoiceRecord | None:
    """Look up a prior payment by composite key (normalize_vendor(vendor),
    invoice_number). Returns None on miss, on blank/None vendor, or on blank
    invoice_number."""
    if not vendor or not vendor.strip() or not invoice_number:
        return None
    vendor_normalized = normalize_vendor(vendor)
    if not vendor_normalized:
        return None
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT vendor_normalized, invoice_number, run_id, vendor_display, "
            "       amount, paid_at "
            "  FROM paid_invoices "
            " WHERE vendor_normalized = ? AND invoice_number = ?",
            (vendor_normalized, invoice_number),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return PaidInvoiceRecord(
        vendor_normalized=row[0],
        invoice_number=row[1],
        run_id=row[2],
        vendor_display=row[3],
        amount=row[4],
        paid_at=dt.datetime.fromisoformat(row[5]),
    )


def record_paid(record: PaidInvoiceRecord, *, db_path: Path) -> None:
    """Insert a paid-invoice record. INSERT OR IGNORE on the composite key:
    concurrent writes for the same (vendor_normalized, invoice_number) are
    race-safe; the second writer is a no-op."""
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO paid_invoices ("
            "  vendor_normalized, invoice_number, run_id, "
            "  vendor_display, amount, paid_at"
            ") VALUES (?, ?, ?, ?, ?, ?)",
            (
                record.vendor_normalized,
                record.invoice_number,
                record.run_id,
                record.vendor_display,
                record.amount,
                record.paid_at.isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests — all should PASS**

```bash
pytest tests/test_paid_invoices.py -v
```
Expected: 7 PASSED.

- [ ] **Step 5: Run mypy strict**

```bash
mypy app
```
Expected: PASS.

- [ ] **Step 6: Commit Tasks 6-7 together**

```bash
git add backend/app/db/init_db.py \
        backend/app/db/paid_invoices.py \
        backend/tests/test_paid_invoices.py
git commit -m "feat(db): add paid_invoices table + typed accessors

Adds CREATE TABLE IF NOT EXISTS paid_invoices to init_db with a composite
PRIMARY KEY of (vendor_normalized, invoice_number). The normalized vendor
column reuses init_db.normalize_vendor() so 'Acme Corp' and 'Acme
Corporation' resolve to the same key.

app/db/paid_invoices.py exposes typed lookup_paid / record_paid helpers
that open SQLite with timeout=30s to survive multi-worker contention.
record_paid is INSERT OR IGNORE so concurrent writes for the same key are
race-safe.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 8: Add `duplicate_invoice` to `ValidationIssue.kind`

**Files:**
- Modify: `backend/app/graph/state.py:44-58`

- [ ] **Step 1: Extend the Literal**

In `backend/app/graph/state.py`, find `ValidationIssue.kind` and add `"duplicate_invoice"`:

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

- [ ] **Step 2: Run state-model tests**

```bash
pytest tests/test_state_models.py -v
```
Expected: PASS.

- [ ] **Step 3: Commit (defer to Task 9)**

---

## Task 9: Add `_check_duplicate_invoice` to `validate.py` (TDD)

**Files:**
- Modify: `backend/app/agents/validate.py`
- Test: `backend/tests/test_validate_agent.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_validate_agent.py`:

```python
def test_duplicate_invoice_warns_when_registry_has_prior(tmp_path: Path):
    import datetime as dt
    from app.db.paid_invoices import PaidInvoiceRecord, record_paid
    from app.db.init_db import normalize_vendor

    db = _seeded(tmp_path)
    record_paid(
        PaidInvoiceRecord(
            vendor_normalized=normalize_vendor("Widgets Inc."),
            invoice_number="INV-1001",
            run_id="prior-run",
            vendor_display="Widgets Inc.",
            amount=5000.0,
            paid_at=dt.datetime(2026, 1, 16, 12, 0, tzinfo=dt.UTC),
        ),
        db_path=db,
    )
    state = _state(_inv(
        invoice_number="INV-1001", vendor="Widgets Inc.",
        line_items=[LineItem(item="WidgetA", quantity=5, unit_price=250.0)],
        total=1250.0,
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    by_kind = {i.kind: i for i in out.validation.issues}
    assert "duplicate_invoice" in by_kind
    assert by_kind["duplicate_invoice"].severity == "warn"
    assert "prior-run" in by_kind["duplicate_invoice"].detail


def test_duplicate_invoice_does_not_fire_for_different_vendor(tmp_path: Path):
    # Regression test for the composite-key fix: same invoice_number under a
    # different vendor must NOT be flagged as a duplicate.
    import datetime as dt
    from app.db.paid_invoices import PaidInvoiceRecord, record_paid
    from app.db.init_db import normalize_vendor

    db = _seeded(tmp_path)
    record_paid(
        PaidInvoiceRecord(
            vendor_normalized=normalize_vendor("Vendor A"),
            invoice_number="INV-001",
            run_id="r-a", vendor_display="Vendor A",
            amount=100.0,
            paid_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        ),
        db_path=db,
    )
    state = _state(_inv(
        invoice_number="INV-001", vendor="Widgets Inc.",
        line_items=[LineItem(item="WidgetA", quantity=1, unit_price=250.0)],
        total=250.0,
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    kinds = {i.kind for i in out.validation.issues}
    assert "duplicate_invoice" not in kinds


def test_duplicate_check_skipped_when_vendor_missing(tmp_path: Path):
    # vendor=None means missing_vendor is already a hard block; the duplicate
    # check defensively returns no issue rather than crashing.
    db = _seeded(tmp_path)
    state = _state(_inv(
        invoice_number="INV-1001", vendor=None,
        line_items=[LineItem(item="WidgetA", quantity=1, unit_price=250.0)],
        total=250.0,
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    kinds = {i.kind for i in out.validation.issues}
    assert "missing_vendor" in kinds
    assert "duplicate_invoice" not in kinds
```

- [ ] **Step 2: Run tests — should FAIL**

```bash
pytest tests/test_validate_agent.py::test_duplicate_invoice_warns_when_registry_has_prior \
       tests/test_validate_agent.py::test_duplicate_invoice_does_not_fire_for_different_vendor \
       tests/test_validate_agent.py::test_duplicate_check_skipped_when_vendor_missing -v
```
Expected: FAIL — `duplicate_invoice` not in kinds; helper not yet implemented.

- [ ] **Step 3: Implement the helper and wire it in**

In `backend/app/agents/validate.py`, add the import near the top with other `app.*` imports:

```python
from app.db.paid_invoices import lookup_paid
```

Then add a new helper after `_check_currency`:

```python
def _check_duplicate_invoice(inv: InvoiceData, db_path: Path) -> list[ValidationIssue]:
    if not inv.invoice_number or not inv.vendor or not inv.vendor.strip():
        return []
    prior = lookup_paid(
        vendor=inv.vendor, invoice_number=inv.invoice_number, db_path=db_path,
    )
    if prior is None:
        return []
    return [ValidationIssue(
        kind="duplicate_invoice",
        detail=(
            f"already paid in run {prior.run_id} for ${prior.amount:.2f} "
            f"on {prior.paid_at:%Y-%m-%d}; this submission is "
            f"${(inv.total or 0.0):.2f}"
        ),
        severity="warn",
    )]
```

In `run_validate`, splice the call in alongside the other checks (after `_check_currency`):

```python
    issues.extend(_check_required_fields(inv))
    issues.extend(_check_negative_quantities(inv))
    issues.extend(_check_dates(inv))
    issues.extend(_check_total_math(inv))
    issues.extend(_check_currency(inv))
    issues.extend(_check_duplicate_invoice(inv, db_path))
    inv_issues, lookups = _check_line_items_against_inventory(inv, db_path, emitter)
```

- [ ] **Step 4: Run new tests — should PASS**

```bash
pytest tests/test_validate_agent.py::test_duplicate_invoice_warns_when_registry_has_prior \
       tests/test_validate_agent.py::test_duplicate_invoice_does_not_fire_for_different_vendor \
       tests/test_validate_agent.py::test_duplicate_check_skipped_when_vendor_missing -v
```
Expected: PASS.

- [ ] **Step 5: Run full validate suite to catch regressions**

```bash
pytest tests/test_validate_agent.py -v
```
Expected: all PASS.

- [ ] **Step 6: Run mypy strict**

```bash
mypy app
```
Expected: PASS.

- [ ] **Step 7: Commit Tasks 8-9**

```bash
git add backend/app/agents/validate.py \
        backend/app/graph/state.py \
        backend/tests/test_validate_agent.py
git commit -m "feat(validate): emit duplicate_invoice issue from paid_invoices registry

Adds _check_duplicate_invoice which looks up (vendor, invoice_number) in the
SQLite paid_invoices registry and emits a warn-severity duplicate_invoice
issue when a prior payment exists. severity=warn routes the run via the
rules engine to scrutiny -> needs_review, letting the approver weigh the
duplicate context rather than auto-rejecting.

Adds duplicate_invoice to ValidationIssue.kind. Composite-key isolation
test confirms different vendors with the same invoice_number do not
collide.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 10: Persist on pay-time (TDD)

**Files:**
- Modify: `backend/app/agents/pay.py`
- Modify: `backend/app/graph/builder.py:43-44`
- Test: `backend/tests/test_pay.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_pay.py` (add imports at the top if missing):

```python
def test_pay_persists_to_registry(tmp_path: Path) -> None:
    from app.agents.pay import run_pay
    from app.db.paid_invoices import lookup_paid
    from app.db.init_db import init_db
    from app.graph.state import InvoiceData, InvoiceState, LineItem
    from app.logging_.event_emitter import EventEmitter

    seed = Path(__file__).resolve().parent.parent / "app" / "db" / "seed.yaml"
    db = tmp_path / "inv.db"
    init_db(db, seed_path=seed, reset=True)

    invoice = InvoiceData(
        invoice_number="INV-1001", vendor="Widgets Inc.",
        date=None, due_date=None,
        line_items=[LineItem(item="WidgetA", quantity=5, unit_price=250.0)],
        subtotal=None, tax_amount=None, total=1250.0,
        currency="USD", payment_terms=None, raw_text="",
    )
    state = InvoiceState(
        run_id="run-pay-1", source_path="x", file_format="txt", invoice=invoice,
    )
    emitter = EventEmitter("run-pay-1", state.events, tmp_path / "logs")
    run_pay(state, emitter=emitter, paid_invoices=set(), db_path=db)

    got = lookup_paid(vendor="Widgets Inc.", invoice_number="INV-1001", db_path=db)
    assert got is not None
    assert got.run_id == "run-pay-1"
    assert got.amount == 1250.0
```

- [ ] **Step 2: Run test — should FAIL**

```bash
pytest tests/test_pay.py::test_pay_persists_to_registry -v
```
Expected: FAIL — `run_pay` has no `db_path` parameter.

- [ ] **Step 3: Update `run_pay` signature and persist on success**

In `backend/app/agents/pay.py`, replace the entire `run_pay` function body. Imports to add near the top:

```python
from __future__ import annotations

import datetime as dt
from pathlib import Path

from app.db.init_db import normalize_vendor
from app.db.paid_invoices import PaidInvoiceRecord, lookup_paid, record_paid
from app.graph.state import InvoiceState
from app.logging_.event_emitter import EventEmitter
from app.tools.payment_tool import mock_payment


def run_pay(
    state: InvoiceState, *, emitter: EventEmitter, paid_invoices: set[str],
    db_path: Path,
) -> InvoiceState:
    emitter.emit("node.start", node="pay")
    inv = state.invoice
    if inv is None or inv.invoice_number is None or inv.total is None or not inv.vendor:
        emitter.emit(
            "node.complete", node="pay", output={"skipped": True, "reason": "missing fields"}
        )
        return state
    invoice_number: str = inv.invoice_number
    vendor: str = inv.vendor
    total: float = inv.total
    # SQL registry is source of truth; in-memory set is a same-process fast-path.
    if invoice_number in paid_invoices or lookup_paid(
        vendor=vendor, invoice_number=invoice_number, db_path=db_path,
    ) is not None:
        emitter.emit("pay.skipped_duplicate", node="pay",
                     output={"invoice_number": invoice_number})
        emitter.emit("node.complete", node="pay", output={"skipped": True, "reason": "duplicate"})
        return state
    receipt = mock_payment(
        vendor=vendor, amount=total,
        invoice_number=invoice_number, run_id=state.run_id,
    )
    paid_invoices.add(invoice_number)
    record_paid(
        PaidInvoiceRecord(
            vendor_normalized=normalize_vendor(vendor),
            invoice_number=invoice_number,
            run_id=state.run_id,
            vendor_display=vendor,
            amount=total,
            paid_at=dt.datetime.now(dt.UTC),
        ),
        db_path=db_path,
    )
    state.payment_receipt = receipt
    emitter.emit("tool.call", node="pay", tool="mock_payment",
                 args={"vendor": vendor, "amount": total}, result=receipt)
    emitter.emit("node.complete", node="pay", output=receipt)
    return state
```

- [ ] **Step 4: Plumb `db_path` through `builder.py`**

In `backend/app/graph/builder.py`, find the `pay_node` definition (line ~43):

```python
    def pay_node(state: InvoiceState) -> InvoiceState:
        return run_pay(state, emitter=make_emitter(state, log_dir), paid_invoices=paid_invoices)
```

Change to pass `db_path`:

```python
    def pay_node(state: InvoiceState) -> InvoiceState:
        return run_pay(
            state, emitter=make_emitter(state, log_dir),
            paid_invoices=paid_invoices, db_path=db_path,
        )
```

- [ ] **Step 5: Run pay tests — new test should PASS, existing ones must still PASS**

```bash
pytest tests/test_pay.py -v
```
Expected: all PASS. Existing pay tests may need a `db_path=...` kwarg added at their call sites. If any FAIL with `TypeError: run_pay() missing 1 required keyword-only argument: 'db_path'`, edit each failing test to add a seeded `db_path` (use the conftest `seeded_db_path` fixture, or create one with `init_db` in `tmp_path`). For each fix, the minimal diff is:

```python
# Before
out = run_pay(state, emitter=emitter, paid_invoices=set())
# After (using conftest)
out = run_pay(state, emitter=emitter, paid_invoices=set(), db_path=seeded_db_path)
```

- [ ] **Step 6: Run graph-builder tests**

```bash
pytest tests/test_graph_builder.py -v
```
Expected: PASS. `build_graph` already has `db_path` in scope, so plumbing should not break wiring.

- [ ] **Step 7: Run mypy strict**

```bash
mypy app
```
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/agents/pay.py \
        backend/app/graph/builder.py \
        backend/tests/test_pay.py
git commit -m "feat(pay): persist payment to paid_invoices registry

run_pay now takes db_path and writes a PaidInvoiceRecord on successful
mock_payment. The in-memory paid_invoices set stays as a same-process
fast-path; SQL is the source of truth and survives across CLI runs,
server restarts, and workers. Duplicate check at pay-time consults both.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 11: Retroactive flagging of prior run (TDD)

**Files:**
- Modify: `backend/app/agents/validate.py`
- Test: new test added to `backend/tests/test_validate_agent.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_validate_agent.py`:

```python
def test_duplicate_invoice_writes_retroactive_event_to_prior_log(tmp_path: Path):
    """When a duplicate is detected, append `duplicate_detected_retroactive`
    to the prior run's jsonl event log."""
    import datetime as dt
    import json
    from app.db.paid_invoices import PaidInvoiceRecord, record_paid
    from app.db.init_db import normalize_vendor

    db = _seeded(tmp_path)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    # Seed a prior run's log file so the retroactive append has a target.
    prior_run_id = "prior-run"
    prior_log = log_dir / f"{prior_run_id}.jsonl"
    prior_log.write_text(
        json.dumps({"kind": "node.start", "ts": "2026-01-16T12:00:00Z", "node": "ingest"})
        + "\n"
    )
    record_paid(
        PaidInvoiceRecord(
            vendor_normalized=normalize_vendor("Widgets Inc."),
            invoice_number="INV-1001", run_id=prior_run_id,
            vendor_display="Widgets Inc.", amount=5000.0,
            paid_at=dt.datetime(2026, 1, 16, 12, 0, tzinfo=dt.UTC),
        ),
        db_path=db,
    )

    state = _state(_inv(
        invoice_number="INV-1001", vendor="Widgets Inc.",
        line_items=[LineItem(item="WidgetA", quantity=5, unit_price=250.0)],
        total=1250.0,
    ))
    state.run_id = "later-run"
    emitter = EventEmitter("later-run", state.events, log_dir)
    run_validate(state, db_path=db, emitter=emitter)

    lines = prior_log.read_text().splitlines()
    retro = [
        json.loads(line) for line in lines
        if json.loads(line).get("kind") == "duplicate_detected_retroactive"
    ]
    assert len(retro) == 1
    assert retro[0]["later_run_id"] == "later-run"
    assert retro[0]["later_amount"] == 1250.0


def test_duplicate_invoice_writes_decision_update_sidecar(tmp_path: Path):
    """When a duplicate is detected, append a row to decision_updates.jsonl
    flipping the prior run to needs_review."""
    import datetime as dt
    import json
    from app.db.paid_invoices import PaidInvoiceRecord, record_paid
    from app.db.init_db import normalize_vendor

    db = _seeded(tmp_path)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    prior_run_id = "prior-run"
    (log_dir / f"{prior_run_id}.jsonl").write_text("")
    record_paid(
        PaidInvoiceRecord(
            vendor_normalized=normalize_vendor("Widgets Inc."),
            invoice_number="INV-1001", run_id=prior_run_id,
            vendor_display="Widgets Inc.", amount=5000.0,
            paid_at=dt.datetime(2026, 1, 16, tzinfo=dt.UTC),
        ),
        db_path=db,
    )

    state = _state(_inv(
        invoice_number="INV-1001", vendor="Widgets Inc.",
        line_items=[LineItem(item="WidgetA", quantity=5, unit_price=250.0)],
        total=1250.0,
    ))
    state.run_id = "later-run"
    emitter = EventEmitter("later-run", state.events, log_dir)
    run_validate(state, db_path=db, emitter=emitter)

    sidecar = log_dir / "decision_updates.jsonl"
    assert sidecar.exists()
    rows = [json.loads(line) for line in sidecar.read_text().splitlines() if line.strip()]
    matching = [r for r in rows if r["run_id"] == prior_run_id]
    assert len(matching) == 1
    assert matching[0]["new_outcome"] == "needs_review"
    assert matching[0]["reason"] == "duplicate_detected"
    assert matching[0]["triggered_by_run_id"] == "later-run"


def test_duplicate_invoice_handles_missing_prior_log_gracefully(tmp_path: Path):
    """If the prior run's jsonl is not on disk, emit a skipped event but do not raise."""
    import datetime as dt
    from app.db.paid_invoices import PaidInvoiceRecord, record_paid
    from app.db.init_db import normalize_vendor

    db = _seeded(tmp_path)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    # NOTE: no prior log file created.
    record_paid(
        PaidInvoiceRecord(
            vendor_normalized=normalize_vendor("Widgets Inc."),
            invoice_number="INV-1001", run_id="prior-run-gone",
            vendor_display="Widgets Inc.", amount=5000.0,
            paid_at=dt.datetime(2026, 1, 16, tzinfo=dt.UTC),
        ),
        db_path=db,
    )

    state = _state(_inv(
        invoice_number="INV-1001", vendor="Widgets Inc.",
        line_items=[LineItem(item="WidgetA", quantity=1, unit_price=250.0)],
        total=250.0,
    ))
    state.run_id = "later-run"
    emitter = EventEmitter("later-run", state.events, log_dir)
    out = run_validate(state, db_path=db, emitter=emitter)
    # Still emits the validation issue on the current run.
    kinds = {i.kind for i in out.validation.issues}
    assert "duplicate_invoice" in kinds
    # And emits a skipped event on the current run's event stream.
    event_kinds = [e.get("kind") for e in state.events]
    assert "duplicate_detected_retroactive_skipped" in event_kinds
```

- [ ] **Step 2: Run tests — should FAIL**

```bash
pytest tests/test_validate_agent.py::test_duplicate_invoice_writes_retroactive_event_to_prior_log \
       tests/test_validate_agent.py::test_duplicate_invoice_writes_decision_update_sidecar \
       tests/test_validate_agent.py::test_duplicate_invoice_handles_missing_prior_log_gracefully -v
```
Expected: FAIL — retroactive write logic does not yet exist.

- [ ] **Step 3: Implement retroactive write**

In `backend/app/agents/validate.py`, extend `_check_duplicate_invoice` so it returns issues **and** performs the retroactive writes. Replace the helper with this version (changes are: split into a helper that also writes, accept `emitter` for the skipped event):

```python
import datetime as dt
import json
```

(near top of file, if not already imported)

Replace the helper:

```python
def _check_duplicate_invoice(
    inv: InvoiceData, db_path: Path, *, state_run_id: str, emitter: EventEmitter,
) -> list[ValidationIssue]:
    if not inv.invoice_number or not inv.vendor or not inv.vendor.strip():
        return []
    prior = lookup_paid(
        vendor=inv.vendor, invoice_number=inv.invoice_number, db_path=db_path,
    )
    if prior is None:
        return []

    issue = ValidationIssue(
        kind="duplicate_invoice",
        detail=(
            f"already paid in run {prior.run_id} for ${prior.amount:.2f} "
            f"on {prior.paid_at:%Y-%m-%d}; this submission is "
            f"${(inv.total or 0.0):.2f}"
        ),
        severity="warn",
    )

    log_dir = emitter.log_dir
    now_iso = dt.datetime.now(dt.UTC).isoformat()
    prior_log = log_dir / f"{prior.run_id}.jsonl"

    if prior_log.exists():
        retroactive_event = {
            "kind": "duplicate_detected_retroactive",
            "ts": now_iso,
            "later_run_id": state_run_id,
            "later_amount": inv.total or 0.0,
            "later_invoice_number": inv.invoice_number,
        }
        with prior_log.open("a") as f:
            f.write(json.dumps(retroactive_event, default=str) + "\n")

        sidecar = log_dir / "decision_updates.jsonl"
        sidecar_row = {
            "run_id": prior.run_id,
            "invoice_number": prior.invoice_number,
            "previous_outcome": "approved",
            "new_outcome": "needs_review",
            "reason": "duplicate_detected",
            "updated_at": now_iso,
            "triggered_by_run_id": state_run_id,
        }
        with sidecar.open("a") as f:
            f.write(json.dumps(sidecar_row, default=str) + "\n")
    else:
        emitter.emit(
            "duplicate_detected_retroactive_skipped", node="validate",
            output={
                "prior_run_id": prior.run_id,
                "reason": "prior_log_not_found",
            },
        )

    return [issue]
```

Update the call site in `run_validate`:

```python
    issues.extend(_check_duplicate_invoice(
        inv, db_path, state_run_id=state.run_id, emitter=emitter,
    ))
```

- [ ] **Step 4: Run the three new tests — should PASS**

```bash
pytest tests/test_validate_agent.py::test_duplicate_invoice_writes_retroactive_event_to_prior_log \
       tests/test_validate_agent.py::test_duplicate_invoice_writes_decision_update_sidecar \
       tests/test_validate_agent.py::test_duplicate_invoice_handles_missing_prior_log_gracefully -v
```
Expected: PASS.

- [ ] **Step 5: Re-run earlier Task-9 tests to confirm they still pass under the new signature**

```bash
pytest tests/test_validate_agent.py -v
```
Expected: all PASS. (The Task-9 tests pass `emitter` already — they will keep working because `emitter` was already an argument to `run_validate`.)

- [ ] **Step 6: Run mypy strict**

```bash
mypy app
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/agents/validate.py \
        backend/tests/test_validate_agent.py
git commit -m "feat(validate): retroactive flagging of prior run on duplicate detect

When a duplicate is detected at validate-time, append a
duplicate_detected_retroactive event to the prior run's jsonl event log
and a decision-update row to a sidecar decision_updates.jsonl
(previous_outcome -> needs_review, reason=duplicate_detected). The
sidecar keeps rejections.jsonl append-only/replayable while the override
is composable downstream via app.api.decisions.effective_outcome.

Missing prior-log file is a best-effort no-op: emit a
duplicate_detected_retroactive_skipped event and continue. Never raises.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 12: Create `app/api/decisions.py` with `effective_outcome` (TDD)

**Files:**
- Create: `backend/app/api/decisions.py`
- Test: `backend/tests/test_api.py` (existing file — add a section)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_api.py`:

```python
def test_effective_outcome_no_override_falls_back_to_decision(tmp_path: Path) -> None:
    import json
    from app.api.decisions import effective_outcome

    log_dir = tmp_path
    run_id = "r1"
    (log_dir / f"{run_id}.jsonl").write_text(
        json.dumps({
            "kind": "approve.decision",
            "output": {"outcome": "approved", "rationale": "all gates green",
                       "rules_applied": []},
        }) + "\n"
    )

    eo = effective_outcome(run_id, log_dir=log_dir)
    assert eo.outcome == "approved"
    assert eo.override_reason is None
    assert eo.overridden_at is None
    assert eo.triggered_by_run_id is None


def test_effective_outcome_applies_override_from_sidecar(tmp_path: Path) -> None:
    import json
    from app.api.decisions import effective_outcome

    log_dir = tmp_path
    run_id = "r1"
    (log_dir / f"{run_id}.jsonl").write_text(
        json.dumps({
            "kind": "approve.decision",
            "output": {"outcome": "approved", "rationale": "",
                       "rules_applied": []},
        }) + "\n"
    )
    (log_dir / "decision_updates.jsonl").write_text(
        json.dumps({
            "run_id": run_id,
            "invoice_number": "INV-1001",
            "previous_outcome": "approved",
            "new_outcome": "needs_review",
            "reason": "duplicate_detected",
            "updated_at": "2026-05-13T12:00:00+00:00",
            "triggered_by_run_id": "later-run",
        }) + "\n"
    )

    eo = effective_outcome(run_id, log_dir=log_dir)
    assert eo.outcome == "needs_review"
    assert eo.override_reason == "duplicate_detected"
    assert eo.triggered_by_run_id == "later-run"
    assert eo.overridden_at is not None


def test_effective_outcome_uses_latest_when_multiple_overrides(tmp_path: Path) -> None:
    import json
    from app.api.decisions import effective_outcome

    log_dir = tmp_path
    run_id = "r1"
    (log_dir / f"{run_id}.jsonl").write_text(
        json.dumps({"kind": "approve.decision",
                    "output": {"outcome": "approved", "rationale": "",
                               "rules_applied": []}}) + "\n"
    )
    (log_dir / "decision_updates.jsonl").write_text(
        json.dumps({"run_id": run_id, "invoice_number": "INV-1001",
                    "previous_outcome": "approved", "new_outcome": "needs_review",
                    "reason": "duplicate_detected",
                    "updated_at": "2026-05-13T12:00:00+00:00",
                    "triggered_by_run_id": "x"}) + "\n"
        + json.dumps({"run_id": run_id, "invoice_number": "INV-1001",
                      "previous_outcome": "needs_review", "new_outcome": "rejected",
                      "reason": "manual_review",
                      "updated_at": "2026-05-13T15:00:00+00:00",
                      "triggered_by_run_id": "y"}) + "\n"
    )

    eo = effective_outcome(run_id, log_dir=log_dir)
    assert eo.outcome == "rejected"
    assert eo.override_reason == "manual_review"
    assert eo.triggered_by_run_id == "y"
```

- [ ] **Step 2: Run tests — FAIL on ImportError**

```bash
pytest tests/test_api.py::test_effective_outcome_no_override_falls_back_to_decision \
       tests/test_api.py::test_effective_outcome_applies_override_from_sidecar \
       tests/test_api.py::test_effective_outcome_uses_latest_when_multiple_overrides -v
```
Expected: ImportError on `app.api.decisions`.

- [ ] **Step 3: Create the module**

Create `backend/app/api/decisions.py`:

```python
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

Outcome = Literal["approved", "rejected", "needs_review", "unprocessable"]


class EffectiveOutcome(BaseModel):
    outcome: Outcome
    override_reason: str | None = None
    overridden_at: dt.datetime | None = None
    triggered_by_run_id: str | None = None


def _decision_from_event_log(log_path: Path) -> Outcome:
    if not log_path.exists():
        return "unprocessable"
    for line in log_path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("kind") == "approve.decision":
            outcome = event.get("output", {}).get("outcome")
            if outcome in ("approved", "rejected", "needs_review"):
                return outcome  # type: ignore[return-value]
    return "unprocessable"


def _latest_override(sidecar_path: Path, run_id: str) -> dict[str, object] | None:
    if not sidecar_path.exists():
        return None
    latest: dict[str, object] | None = None
    for line in sidecar_path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("run_id") != run_id:
            continue
        latest = row  # later row wins (file is append-only chronological)
    return latest


def effective_outcome(run_id: str, *, log_dir: Path) -> EffectiveOutcome:
    """Return the effective outcome for a run, applying any retroactive override
    recorded in decision_updates.jsonl on top of the run's recorded Decision."""
    base = _decision_from_event_log(log_dir / f"{run_id}.jsonl")
    override = _latest_override(log_dir / "decision_updates.jsonl", run_id)
    if override is None:
        return EffectiveOutcome(outcome=base)
    return EffectiveOutcome(
        outcome=override["new_outcome"],  # type: ignore[arg-type]
        override_reason=str(override["reason"]),
        overridden_at=dt.datetime.fromisoformat(str(override["updated_at"])),
        triggered_by_run_id=str(override["triggered_by_run_id"]),
    )
```

- [ ] **Step 4: Run tests — should PASS**

```bash
pytest tests/test_api.py::test_effective_outcome_no_override_falls_back_to_decision \
       tests/test_api.py::test_effective_outcome_applies_override_from_sidecar \
       tests/test_api.py::test_effective_outcome_uses_latest_when_multiple_overrides -v
```
Expected: 3 PASSED.

- [ ] **Step 5: Run mypy strict**

```bash
mypy app
```
Expected: PASS.

- [ ] **Step 6: Commit (defer to Task 13)**

---

## Task 13: Surface `effective_outcome` on `GET /runs/{run_id}` (TDD)

**Files:**
- Modify: `backend/app/api/routes.py:79-90` (the run-detail GET handler)
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Confirmed handler shape**

`backend/app/api/routes.py:79-84` defines:

```python
@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    run = registry.get(run_id)
    if run is None:
        raise HTTPException(404)
    return run.state.model_dump(mode="json")
```

The `RunRegistry` (constructed at `app/api/runs.py:41-42`) holds `log_dir` as an instance attribute, so `registry.log_dir` is the right source for the composer.

- [ ] **Step 2: Write a failing endpoint test**

Append to `backend/tests/test_api.py`:

```python
def test_get_run_includes_effective_outcome_block(api_client, tmp_path: Path) -> None:
    # Seed a run via the existing /api/runs/sample flow or create one directly;
    # easiest is to POST a tiny invoice and read back.
    import json
    invoice_file = tmp_path / "inv.txt"
    invoice_file.write_text("INVOICE\nVendor: V\nInvoice Number: INV-X\nTotal: 100\n")
    with invoice_file.open("rb") as f:
        resp = api_client.post(
            "/api/runs", files={"file": ("inv.txt", f, "text/plain")},
        )
    run_id = resp.json()["run_id"]

    detail = api_client.get(f"/api/runs/{run_id}").json()
    assert "effective_outcome" in detail
    eo = detail["effective_outcome"]
    assert "outcome" in eo
    assert "override_reason" in eo
    assert "overridden_at" in eo
    assert "triggered_by_run_id" in eo
    # No override has been written for this fresh run.
    assert eo["override_reason"] is None
```

- [ ] **Step 3: Run test — should FAIL**

```bash
pytest tests/test_api.py::test_get_run_includes_effective_outcome_block -v
```
Expected: FAIL — KeyError or AssertionError on `effective_outcome`.

- [ ] **Step 4: Wire `effective_outcome` into the handler**

In `backend/app/api/routes.py`, add the import alongside the existing `from app.api.runs import ...` block:

```python
from app.api.decisions import effective_outcome
```

Replace the `get_run` handler (lines 79-84) with:

```python
    @router.get("/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        run = registry.get(run_id)
        if run is None:
            raise HTTPException(404)
        payload = run.state.model_dump(mode="json")
        payload["effective_outcome"] = effective_outcome(
            run_id, log_dir=registry.log_dir,
        ).model_dump(mode="json")
        return payload
```

(No other handler needs to change. List/metrics endpoints continue to use the recorded `Decision.outcome` per the existing `_summary` shape.)

- [ ] **Step 5: Run the endpoint test — should PASS**

```bash
pytest tests/test_api.py::test_get_run_includes_effective_outcome_block -v
```
Expected: PASS.

- [ ] **Step 6: Run full API suite + decisions tests**

```bash
pytest tests/test_api.py -v
```
Expected: all PASS.

- [ ] **Step 7: Run mypy strict**

```bash
mypy app
```
Expected: PASS.

- [ ] **Step 8: Commit Tasks 12-13**

```bash
git add backend/app/api/decisions.py \
        backend/app/api/routes.py \
        backend/tests/test_api.py
git commit -m "feat(api): expose effective_outcome on GET /runs/{run_id}

New app/api/decisions.py composes the effective outcome of a run by
applying the latest decision_updates.jsonl override on top of the
recorded approve.decision. Surfaced as an effective_outcome block on the
run-detail endpoint so the frontend has a stable contract for
'approved (now needs_review — duplicate_detected)' rendering without
having to read sidecar files directly.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 14: Replay tolerates the new event kind

**Files:**
- Test: `backend/tests/test_replay.py`

- [ ] **Step 1: Verify replay loop already tolerates unknown kinds**

Read `backend/app/tools/replay.py:11-44` — it iterates events and inspects `e.get("kind")` against specific values (`"llm.call"`, `"tool.call"`, `"approve.decision"`). Unknown kinds are silently skipped. The test below pins this contract for the new kind.

- [ ] **Step 2: Write the regression test**

Append to `backend/tests/test_replay.py`:

```python
def test_replay_tolerates_duplicate_detected_retroactive_event(tmp_path: Path) -> None:
    import json
    from app.tools.replay import replay_trace

    run_id = "test-run"
    log = tmp_path / f"{run_id}.jsonl"
    log.write_text(
        json.dumps({"kind": "node.start", "node": "ingest"}) + "\n"
        + json.dumps({
            "kind": "duplicate_detected_retroactive",
            "ts": "2026-05-13T12:00:00Z",
            "later_run_id": "later",
            "later_amount": 1250.0,
            "later_invoice_number": "INV-1001",
        }) + "\n"
        + json.dumps({
            "kind": "approve.decision",
            "output": {"outcome": "approved", "rationale": "x", "rules_applied": []},
        }) + "\n"
    )
    summary = replay_trace(run_id, log_dir=tmp_path)
    assert summary["events"] == 3
    assert summary["decision"] is not None
    assert summary["decision"]["outcome"] == "approved"
```

- [ ] **Step 3: Run — should PASS without any code change**

```bash
pytest tests/test_replay.py::test_replay_tolerates_duplicate_detected_retroactive_event -v
```
Expected: PASS. If it fails, the replay loop has a kind-allowlist somewhere that needs widening; in that case, modify `replay.py` to skip unknown kinds gracefully.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_replay.py
git commit -m "test(replay): pin tolerance of duplicate_detected_retroactive event

The replay tool reads jsonl event logs and counts/summarizes; unknown
event kinds are skipped. Regression test pins this behavior for the new
duplicate_detected_retroactive event written by validate.py on
cross-batch dup detection.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 15: Update `expected_outcomes.yaml`

**Files:**
- Modify: `backend/tests/expected_outcomes.yaml`

- [ ] **Step 1: Edit the YAML**

In `backend/tests/expected_outcomes.yaml`:

- Find line 19: `INV-9002: { outcome: approved }`
- Change to: `INV-9002: { outcome: needs_review, requires: [duplicate_invoice] }`

Then append at the end of the file:

```yaml
# Outcomes after retroactive flagging — used by integration tests that
# assert effective_outcome composed via app.api.decisions.
effective_outcomes:
  INV-1001: { outcome: needs_review, override_reason: duplicate_detected }
```

- [ ] **Step 2: Identify the harness that reads this file**

```bash
grep -rn "expected_outcomes" backend/tests/ backend/app/ 2>/dev/null
```

Inspect the consumer (likely `test_integration.py` or a separate harness). If the consumer does not yet read `effective_outcomes`, defer harness wiring to the integration test in Task 16 — the YAML addition is forward-compatible (consumers that only read top-level invoice keys will simply ignore the new `effective_outcomes` block).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/expected_outcomes.yaml
git commit -m "test(spec): INV-9002 -> needs_review; add effective_outcomes block

The persistent paid_invoices registry now catches INV-9002's re-submission
of INV-1001 across batches. Updates expected_outcomes to reflect the new
behavior: INV-9002 now requires the duplicate_invoice issue and resolves
to needs_review. Adds an effective_outcomes map so the integration test
can assert the retroactive override flips INV-1001 to needs_review after
INV-9002 is processed.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 16: End-to-end cross-batch retroactive flag test

**Files:**
- Create: `backend/tests/test_cross_batch_dedup.py`

- [ ] **Step 1: Write the integration test**

Create `backend/tests/test_cross_batch_dedup.py`:

```python
"""End-to-end: process INV-1001 through pay (registry row written), then
process a second invoice with the same (vendor, invoice_number) through a
fresh paid_invoices set to simulate a cross-batch arrival. Asserts the
retroactive flag, the validation issue, the sidecar override, and the
effective_outcome composer."""

import datetime as dt
import json
from pathlib import Path

from app.agents.pay import run_pay
from app.agents.validate import run_validate
from app.api.decisions import effective_outcome
from app.db.init_db import init_db
from app.db.paid_invoices import lookup_paid
from app.graph.state import InvoiceData, InvoiceState, LineItem
from app.logging_.event_emitter import EventEmitter

SEED = Path(__file__).resolve().parent.parent / "app" / "db" / "seed.yaml"


def _state(run_id: str, invoice: InvoiceData) -> InvoiceState:
    return InvoiceState(
        run_id=run_id, source_path=f"{run_id}.txt", file_format="txt",
        invoice=invoice,
    )


def _invoice_1001() -> InvoiceData:
    return InvoiceData(
        invoice_number="INV-1001", vendor="Widgets Inc.",
        date=None, due_date=None,
        line_items=[
            LineItem(item="WidgetA", quantity=10, unit_price=250.0),
            LineItem(item="WidgetB", quantity=5, unit_price=500.0),
        ],
        subtotal=5000.0, tax_amount=0.0, total=5000.0,
        currency="USD", payment_terms=None, raw_text="",
    )


def _invoice_9002_resubmit() -> InvoiceData:
    return InvoiceData(
        invoice_number="INV-1001", vendor="Widgets Inc.",
        date=None, due_date=None,
        line_items=[LineItem(item="WidgetA", quantity=5, unit_price=250.0)],
        subtotal=None, tax_amount=None, total=1250.0,
        currency="USD", payment_terms=None, raw_text="",
    )


def test_cross_batch_dedup_retroactive_flag(tmp_path: Path) -> None:
    db = tmp_path / "inv.db"
    init_db(db, seed_path=SEED, reset=True)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    # ----- Batch 1: pay INV-1001 -----
    s1 = _state("run-1001", _invoice_1001())
    e1 = EventEmitter("run-1001", s1.events, log_dir)
    run_pay(s1, emitter=e1, paid_invoices=set(), db_path=db)
    # Need a recorded decision so effective_outcome has a base to read.
    (log_dir / "run-1001.jsonl").open("a").write(
        json.dumps({
            "kind": "approve.decision",
            "output": {"outcome": "approved", "rationale": "auto",
                       "rules_applied": ["auto_approve"]},
        }) + "\n"
    )

    assert lookup_paid(
        vendor="Widgets Inc.", invoice_number="INV-1001", db_path=db,
    ) is not None

    # ----- Batch 2: validate the re-submit (fresh in-memory set) -----
    s2 = _state("run-9002", _invoice_9002_resubmit())
    e2 = EventEmitter("run-9002", s2.events, log_dir)
    out = run_validate(s2, db_path=db, emitter=e2)

    # (a) duplicate_invoice issue on the new run
    kinds = {i.kind for i in out.validation.issues}
    assert "duplicate_invoice" in kinds

    # (b) retroactive event appended to prior log
    prior_events = [
        json.loads(line) for line in (log_dir / "run-1001.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert any(e.get("kind") == "duplicate_detected_retroactive" for e in prior_events)

    # (c) sidecar override row exists
    sidecar = log_dir / "decision_updates.jsonl"
    rows = [json.loads(line) for line in sidecar.read_text().splitlines() if line.strip()]
    matching = [r for r in rows if r["run_id"] == "run-1001"]
    assert len(matching) == 1 and matching[0]["new_outcome"] == "needs_review"

    # (d) effective_outcome composer flips INV-1001 to needs_review
    eo = effective_outcome("run-1001", log_dir=log_dir)
    assert eo.outcome == "needs_review"
    assert eo.override_reason == "duplicate_detected"
    assert eo.triggered_by_run_id == "run-9002"
```

- [ ] **Step 2: Run the test**

```bash
pytest tests/test_cross_batch_dedup.py -v
```
Expected: PASS. If any assertion fails, that points at a wiring gap from earlier tasks.

- [ ] **Step 3: Run the full backend test suite**

```bash
pytest -v
```
Expected: full suite GREEN. Watch for any test that constructs `run_pay(...)` without `db_path=` — patch each call site with the conftest's `seeded_db_path` fixture.

- [ ] **Step 4: Run mypy strict + ruff**

```bash
mypy app
ruff check app tests
```
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_cross_batch_dedup.py
git commit -m "test(integration): cross-batch dedup retroactive flag E2E

End-to-end test that processes INV-1001 through pay (registry row),
then processes a re-submission in a fresh in-memory paid_invoices set
to simulate a cross-batch arrival. Asserts (a) duplicate_invoice on the
new run, (b) retroactive event on the prior log, (c) sidecar override,
(d) effective_outcome flips the prior run to needs_review.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Final verification

- [ ] **Step 1: Full suite GREEN**

```bash
pytest -v
mypy app
ruff check app tests
```
Expected: all PASS.

- [ ] **Step 2: Manual smoke against the real fixtures (optional, requires XAI_API_KEY)**

```bash
make demo
```
Confirm:
- INV-9001 → suspicion signal `homoglyph_corruption` present in trace; outcome `needs_review`.
- INV-9002 → validation issue `duplicate_invoice`; outcome `needs_review`; INV-1001's log has the retroactive event.
- INV-9004 → validation issues include `price_mismatch` (10% boundary) and `currency_mismatch`; outcome `needs_review`.

- [ ] **Step 3: Push branch**

```bash
git push -u origin feature/ui-improvement
```

(Do NOT open a PR automatically — the user decides when.)

---

## Operational notes (for ops / future ops docs)

- **Registry maintenance:** to clear a `paid_invoices` row out-of-band (e.g., a run was deleted and the invoice needs to be re-submittable):
  ```sql
  DELETE FROM paid_invoices
   WHERE vendor_normalized = ? AND invoice_number = ?;
  ```
- **Validate-time race window:** if two workers process the same `(vendor, invoice_number)` simultaneously, both may pass `_check_duplicate_invoice` before either reaches pay. First-to-pay wins via `INSERT OR IGNORE`; second-to-pay no-ops at the registry. The current spec accepts this edge case explicitly.
