# Invoice Processing Automation — Design Spec

**Date:** 2026-05-13
**Status:** Approved for implementation planning
**Source case:** `/Users/mwakichako/repos/galatiq-case-invoices/README.md`

## 1. Problem and business framing

Acme Corp is losing $2M/year on manual invoice processing: 30% error rate, 5-day delays, frustrated stakeholders. Invoices arrive as messy PDFs, text files, JSON, CSV, XML, and email-style attachments. Staff manually extract data, validate it against an inconsistent legacy inventory database, chase email approvals, and call a banking API.

We will ship a working multi-agent prototype that automates the end-to-end workflow with transparent, auditable reasoning at every step. The product priorities, in order: **functionality end-to-end**, **agentic sophistication** (real tool use + self-correction), **shipping mindset** (ruthless scope cuts), and **UI/UX** (the case's "above and beyond" criterion).

Three concrete business outcomes the prototype demonstrates:

- **Error reduction:** hard-block rules catch missing-vendor, negative-quantity, unknown-item, and overstock conditions; warn rules surface math errors and price drift; a propose-critique-finalize loop in the approver catches what the first pass misses.
- **Speed:** each invoice completes the graph in seconds, with the entire reasoning trace visible. A "Run all 16" batch button resolves the queue while the user watches.
- **Stakeholder trust:** every approved, rejected, or `needs_review` decision carries a written rationale tied to specific named rules, so AP, vendors, and the VP all see the same story.

## 2. Scope

### In scope
- 4-stage LangGraph pipeline: ingestion → validation → approval → payment/rejection-log
- LLM-driven extraction for all input formats (PDF, TXT, JSON, CSV, XML, email-style)
- SQLite-backed inventory and vendor validation
- Rule-driven approval with a propose → critique → finalize sub-loop inside the approver node
- Mock payment tool (no real banking API)
- FastAPI backend with Server-Sent Events
- React/TypeScript frontend with four panels: live timeline, batch queue, DB inspector, critique side-by-side
- CLI entry point matching the README contract: `python main.py --invoice_path=...`
- Structured per-run trace files (jsonl), unit tests, golden-fixture integration tests, opt-in live-LLM smoke test
- 5 additional adversarial test invoices we author

### Out of scope (and called out so we do not drift)
- Authentication, multi-user, role-based access
- Persistent run history across server restarts (in-memory + trace files only)
- Analytics dashboards / BI charts
- Real banking API integration
- Cross-process payment idempotency persistence
- OpenTelemetry / external trace backends
- Component library on the frontend
- Cloud deployment

### Future extension hooks (deliberately preserved, not built)
- The validator node is a deterministic Python function with a clean tool boundary so it can later be promoted to a tool-using sub-agent that decides which DB queries to run and reasons about fuzzy item matches.
- The ingestion node is one auditable LLM call so it can later become a sub-agent with tools like "re-read PDF page N" or "search prior invoices for this vendor."
- The approver's propose/critique/finalize triple can grow into a bounded N-round loop without changing the graph.

## 3. Technology choices

- **LLM:** xAI Grok via the OpenAI-compatible API at `https://api.x.ai/v1`, default model `grok-4`. Thin wrapper around the OpenAI SDK so we could swap providers.
- **Orchestration:** LangGraph.
- **Backend:** Python 3.11+, FastAPI, `pdfplumber` (PDF text), `PyMuPDF` (PDF fallback), Pydantic v2 (state + structured outputs).
- **Frontend:** Vite + React 18 + TypeScript (strict) + Tailwind + Zustand + React Query.
- **Tooling:** `uv` for Python deps with `pip` fallback, `ruff` lint+format, `mypy --strict` on `app/`, `pytest`. `pnpm` for the frontend with `npm` fallback. Make-/justfile for top-level scripts.

## 4. Architecture

A LangGraph state machine. One shared `InvoiceState` flows through four nodes; conditional edges handle retries and routing.

```
              ┌──────────────┐
              │   ingest     │  ← raw file → InvoiceData + suspicion_signals
              └──────┬───────┘
                     │  (Pydantic invalid → retry once;
                     │   still invalid or unreadable → log node)
                     ▼
              ┌──────────────┐
              │   validate   │  ← inventory + vendor + price checks
              └──────┬───────┘
                     │
                     ▼
              ┌──────────────┐
              │   approve    │  ← rules.yaml +
              │              │     propose → critique → finalize
              └──┬────────┬──┘
       approved │        │ rejected / needs_review / unprocessable
                ▼        ▼
         ┌──────────┐  ┌──────────┐
         │  pay     │  │  log     │
         └────┬─────┘  └────┬─────┘
              └──────┬──────┘
                     ▼
                  END
```

### Repository layout

```
invoice-processing/
  backend/
    app/
      agents/        # ingest.py, validate.py, approve.py, pay.py, log.py
      graph/         # state.py, builder.py
      llm/           # grok_client.py, structured_output.py
      tools/         # inventory_tool.py, vendor_tool.py, payment_tool.py
      rules/         # rules.yaml, engine.py
      logging/       # event_emitter.py
      api/           # routes.py, sse.py
      db/            # init_db.py, seed.yaml
      main.py        # CLI: python -m app.main --invoice_path=...
    tests/
      fixtures/      # recorded Grok responses keyed by invoice + node + pass
      expected_outcomes.yaml
    data/
      invoices/      # 16 sample invoices + 5 authored adversarial ones
      inventory.db   # generated; gitignored
  frontend/
    src/
      components/    # Timeline, BatchQueue, DBInspector, CritiquePanel,
                     # SourceAndExtraction, UploadZone
      pages/
      api/           # SSE client + REST hooks
      store/         # RunStore (Zustand)
  docs/
  Makefile
  README.md
```

## 5. Shared state and data contracts

All nodes communicate via one Pydantic `InvoiceState`. Pydantic models double as structured-output schemas for Grok.

```python
class LineItem(BaseModel):
    item: str
    quantity: int
    unit_price: float | None = None
    notes: str | None = None

class InvoiceData(BaseModel):
    invoice_number: str | None
    vendor: str | None
    date: date | None
    due_date: date | None
    line_items: list[LineItem]
    subtotal: float | None
    tax_amount: float | None
    total: float | None
    currency: str = "USD"
    payment_terms: str | None
    raw_text: str

class SuspicionSignal(BaseModel):
    kind: Literal["urgent_language", "impossible_date", "round_number",
                  "unknown_vendor_pattern", "wire_transfer_demand", "other"]
    detail: str
    severity: Literal["low", "medium", "high"]

class ValidationIssue(BaseModel):
    kind: Literal["unknown_item", "out_of_stock", "qty_exceeds_stock",
                  "price_mismatch", "unknown_vendor", "negative_qty",
                  "missing_vendor", "missing_total", "no_line_items",
                  "total_math_error", "past_due_date"]
    item: str | None = None
    detail: str
    severity: Literal["info", "warn", "block"]

class ValidationReport(BaseModel):
    issues: list[ValidationIssue]
    inventory_lookups: list[dict]
    vendor_lookup: dict | None

class Proposal(BaseModel):
    outcome: Literal["approved", "rejected", "needs_review"]
    rationale: str
    rules_applied: list[str]
    unresolved_concerns: list[str]

class Critique(BaseModel):
    agrees: bool
    objections: list[str]
    missed_signals: list[str]
    rule_misapplications: list[str]

class Decision(BaseModel):
    # The top-level fields are the canonical view used by downstream nodes (pay/log) and the UI summary.
    # They mirror final_proposal — kept at top level so callers do not have to traverse the audit trail.
    outcome: Literal["approved", "rejected", "needs_review"]
    rationale: str
    rules_applied: list[str]
    # Audit trail of the three approval passes.
    initial_proposal: Proposal
    critique: Critique
    final_proposal: Proposal

class InvoiceState(BaseModel):
    run_id: str
    source_path: str
    file_format: Literal["txt","json","csv","xml","pdf","email"]
    invoice: InvoiceData | None = None
    suspicion_signals: list[SuspicionSignal] = []
    extraction_confidence: float | None = None
    validation: ValidationReport | None = None
    decision: Decision | None = None
    payment_receipt: dict | None = None
    error: str | None = None
    events: list[dict] = []
```

Design rule: each node reads and writes its own slice. No node mutates another's output.

## 6. Ingestion agent

**Job:** turn any input file into a validated `InvoiceData` + `suspicion_signals` + `extraction_confidence`.

**Flow:**
1. Detect format from extension.
2. Convert to text: `pdfplumber` for PDF with `PyMuPDF` fallback; everything else read as UTF-8. JSON/CSV/XML are passed as text — the LLM handles them uniformly.
3. One Grok call with a Pydantic structured-output schema covering `InvoiceData`, `suspicion_signals`, and `extraction_confidence`. System prompt directs the model to extract verbatim, return `null` for missing fields, flag specified suspicion patterns, and emit confidence ≤ 0.5 when a human should re-check.
4. Pydantic validates the response. On failure, retry once with the validation error fed back into the prompt.
5. On success → populate state. On hard failure → set `state.error = "unprocessable"` and route to `log` (skipping validate/approve).

**Tools exposed in this node:** none. Ingestion is one auditable LLM call per attempt.

**Events emitted:** `ingest.start`, `ingest.llm_call`, `ingest.retry`, `ingest.complete`.

## 7. Validation agent

**Job:** check the extracted invoice against the inventory DB and rules, produce a `ValidationReport`.

**Approach:** deterministic Python with SQL lookups. No LLM call. Reasoning here is mechanical and putting an LLM in the loop would add latency, non-determinism, and noise in the DB Inspector panel.

**Checks (in order):**

| # | Check | Issue kind | Severity | Example trigger |
|---|---|---|---|---|
| 1a | vendor present | `missing_vendor` | `block` | INV-1009 (empty) |
| 1b | total present | `missing_total` | `block` | (defensive — no current sample) |
| 1c | at least one line item | `no_line_items` | `block` | (defensive) |
| 2 | quantity > 0 for every line item | `negative_qty` | `block` | INV-1009 (`-5`) |
| 3 | due date not in the past relative to invoice date | `past_due_date` | `warn` | INV-1003 ("yesterday"), INV-1008 (10-day terms) |
| 4 | qty × unit_price totals match stated total within $1 | `total_math_error` | `warn` | INV-1013 (off by $50) |
| 5a | line item present in inventory | `unknown_item` | `block` | INV-1008, INV-1016 |
| 5b | inventory `stock > 0` | `out_of_stock` | `block` | INV-1003 (FakeItem) |
| 5c | qty ≤ stock | `qty_exceeds_stock` | `block` | INV-1002 (20× GadgetX, stock 5) |
| 5d | unit_price within 10% of inventory price | `price_mismatch` | `warn` | INV-1014 (EUR), INV-1013 (volume discount) |
| 6 | vendor in approved list | `unknown_vendor` | `warn` | INV-1003, INV-1008 |

All issues are collected; the node never short-circuits. Approval has policy authority.

**Tools (Python functions, also event-logged):**
- `inventory_lookup(item) -> {found, stock, unit_price}` — one call per line item; results stored in `validation.inventory_lookups`.
- `vendor_lookup(name) -> {found, status}` — fuzzy match via normalization (lowercase, strip punctuation, strip `Inc.`/`LLC`/`Co.`).

**Events emitted:** `validate.start`, `validate.tool_call` (one per lookup), `validate.complete`.

## 8. Approval agent

**Job:** weigh validation issues + suspicion signals against `rules.yaml`, produce a final `Decision`.

Three sequential Grok calls, each separately auditable.

**Pass 1 — Approver proposes.** Inputs: `InvoiceData`, `ValidationReport`, `suspicion_signals`, evaluated rules, `extraction_confidence`. Returns `Proposal` with `outcome`, `rationale`, `rules_applied`, `unresolved_concerns`. System prompt: "You are an AP approver. Apply the rules verbatim. Cite each rule you used. Be concise."

**Pass 2 — Critic challenges.** Inputs: everything above + Pass 1's full `Proposal` + the raw invoice text. Returns `Critique` with `agrees`, `objections`, `missed_signals`, `rule_misapplications`. System prompt: "You are an adversarial reviewer. Challenge the approver's decision. Look for missed red flags, weak reasoning, rules applied incorrectly, low extraction confidence the approver glossed over. If you agree, say so plainly — do not manufacture objections."

**Pass 3 — Approver finalizes.** Inputs: Pass 1 + Pass 2. Returns the final `Proposal` (potentially revised). System prompt: "Reconsider given the critique. If the objections are valid, revise. If not, explain why you stand by the original. Produce the final decision."

### Rule engine — `rules.yaml`

```yaml
hard_blocks:          # ValidationIssue.kind values that force a rejection regardless of LLM output
  - missing_vendor
  - missing_total
  - no_line_items
  - negative_qty
  - unknown_item
  - out_of_stock
  - qty_exceeds_stock

auto_approve_when:
  - total_usd_lte: 10000
  - validation_clean: true
  - max_suspicion_severity: low
  - extraction_confidence_gte: 0.8

scrutiny_required_when:
  - total_usd_gt: 10000
  - any_warn_issue: true
  - max_suspicion_severity_gte: medium
  - extraction_confidence_lt: 0.8
```

A Python `evaluate_rules(state)` function returns `{hard_block: [...], auto_approve: bool, scrutiny: bool}` and is included in the approver's prompt as ground-truth context. The LLM does not re-derive the math; it reasons about borderline cases and explains the call.

**The LLM cannot override a hard block.** If `hard_block` is non-empty, the final outcome is forced to `rejected` regardless of model output; the model's role in that case is to produce a clear rationale.

### Failure handling
- Pass 1 or Pass 3 Pydantic-fails → retry once with the error fed back.
- Pass 2 fails → skip critique, mark decision `needs_review`. We never silently rubber-stamp.

**Events emitted:** `approve.rules_evaluated`, `approve.propose.start/complete`, `approve.critique.start/complete`, `approve.finalize.start/complete`, `approve.decision`. Each LLM call records token usage.

## 9. Payment and rejection-log nodes

### `pay`

```python
def mock_payment(vendor: str, amount: float, invoice_number: str, run_id: str) -> dict:
    return {
        "status": "success",
        "transaction_id": f"TXN-{run_id[:8]}",
        "vendor": vendor,
        "amount": amount,
        "invoice_number": invoice_number,
        "paid_at": datetime.utcnow().isoformat(),
    }
```

Lives in `tools/payment_tool.py`. Extra args (`invoice_number`, `run_id`) are tool-internal, not part of the README's two-param contract.

**Idempotency:** in-memory `paid_invoices` set keyed by `invoice_number`. Re-running an invoice in one process is a no-op with a `pay.skipped_duplicate` event. Persistent dedup is out of scope.

**Events:** `pay.start`, `pay.complete`, `pay.skipped_duplicate`.

### `log` (reject / unprocessable path)

Writes a structured rejection record to `logs/rejections.jsonl` and to the per-run trace.

```json
{
  "run_id": "...",
  "invoice_number": "INV-1003",
  "vendor": "Fraudster LLC",
  "outcome": "rejected",
  "rationale": "...",
  "rules_applied": ["hard_block:out_of_stock", "scrutiny:wire_transfer_demand"],
  "validation_issues": [...],
  "suspicion_signals": [...],
  "rejected_at": "..."
}
```

Same node serves `unprocessable` (ingestion gave up); the record carries `outcome: "unprocessable"` and the raw error.

**Events:** `log.rejection_written`, `log.unprocessable_written`.

## 10. FastAPI backend and SSE

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/runs` | Upload an invoice file (multipart). Creates a run, kicks off the graph as a background task, returns `{run_id}`. |
| `GET` | `/api/runs/{run_id}/events` | SSE stream. Replays events emitted before the client connected. Closes on run completion. |
| `GET` | `/api/runs/{run_id}` | Final state snapshot. |
| `GET` | `/api/runs` | List all runs with summary. Backs the batch queue. |
| `POST` | `/api/runs/batch` | Run all 16 sample invoices; returns the list of `run_id`s. |
| `GET` | `/api/inventory` | Current `inventory` + `vendors` table contents. |
| `GET` | `/api/runs/{run_id}/source` | Raw file content for the source panel. |

### Event schema (SSE wire format)

```typescript
type Event =
  | { kind: "node.start";    node: NodeName; ts: string }
  | { kind: "node.complete"; node: NodeName; ts: string; output: any }
  | { kind: "llm.call";      node: NodeName; ts: string; prompt_chars: number; response_chars: number; tokens_in: number; tokens_out: number; model: string; latency_ms: number }
  | { kind: "tool.call";     node: NodeName; ts: string; tool: string; args: any; result: any }
  | { kind: "retry";         node: NodeName; ts: string; reason: string }
  | { kind: "decision";      ts: string; outcome: "approved"|"rejected"|"needs_review"|"unprocessable"; final: Decision }
  | { kind: "run.complete";  ts: string; final_state: InvoiceState }
  | { kind: "run.error";     ts: string; error: string };
```

The same events are written to `logs/<run_id>.jsonl`. Trace files are the source of truth for replay.

### Concurrency

Runs execute in `asyncio` tasks. The graph itself is synchronous Python wrapped in `run_in_executor` to avoid blocking on LLM/DB calls. SSE clients subscribe to a per-run `asyncio.Queue`. Batch runs cap at 4 concurrent.

### CLI compatibility

`python -m app.main --invoice_path=...` runs the same graph in-process, writes a trace file, prints a final summary to stdout. The CLI does not require FastAPI to be running.

## 11. React frontend

### Layout

```
┌────────────────────────────────────────────────────────────────────┐
│  Acme AP                                            [Run all 16] ⚙ │
├──────────────────┬─────────────────────────────────────────────────┤
│  Batch Queue     │   Active Run: INV-1012                          │
│  ─────────────   │   ┌─────────────────────────────────────────┐   │
│  ✓ INV-1001      │   │  Timeline                               │   │
│  ✗ INV-1003      │   │   ● ingest      230ms   confidence 0.78 │   │
│  ▶ INV-1012      │   │   ● validate    18ms    3 issues        │   │
│  ✓ INV-1004      │   │   ◐ approve     running…                │   │
│  …               │   │     ├─ propose   1.2s                   │   │
│                  │   │     ├─ critique  …                      │   │
│                  │   │     └─ finalize  pending                 │   │
│                  │   └─────────────────────────────────────────┘   │
│                  │   ┌──────────────────────┬──────────────────┐   │
│                  │   │  Source / Extracted  │  Critique view   │   │
│                  │   ├──────────────────────┼──────────────────┤   │
│                  │   │ raw text │ parsed    │ proposal │ final │   │
│                  │   │          │ JSON      │ critique │       │   │
│                  │   └──────────────────────┴──────────────────┘   │
│                  │   ┌─────────────────────────────────────────┐   │
│                  │   │  DB Inspector                           │   │
│                  │   │  inventory · vendors · this run's       │   │
│                  │   │  lookups highlighted                    │   │
│                  │   └─────────────────────────────────────────┘   │
└──────────────────┴─────────────────────────────────────────────────┘
```

### Components

| Component | Reads | Renders |
|---|---|---|
| `UploadZone` | — | Drag-drop or click-to-pick; POSTs `/api/runs`. |
| `BatchQueue` | `/api/runs` + active-run summary events | Sortable list (status icon, invoice number, vendor, total, outcome). "Run all 16" button. Click selects active run. |
| `Timeline` | per-run SSE | Vertical stage list with live status, durations, summary chips. Sub-rows for the three approval passes. |
| `SourceAndExtraction` | `/api/runs/{id}/source` + `state.invoice` | Left: raw file text. Right: parsed JSON with nullable fields shown as muted `—`. Suspicion signals as red chips. |
| `CritiquePanel` | `state.decision` | Three columns (initial · critique · final); highlights changes between initial and final. |
| `DBInspector` | `/api/inventory` + `validation.inventory_lookups` | Inventory + vendors tables; rows touched by current run carry a "looked up" badge with the result. |

### State management

One `RunStore` (Zustand) per active run, rebuilt from SSE events via a reducer. React Query for static endpoints (`/api/inventory`, `/api/runs` list).

### Visual language

Grey for neutral, green for approved, amber for warn / needs_review / suspicion, red for rejected / hard block. Monospace for raw text and JSON; sans-serif elsewhere. A soft pulse on the active timeline node. No other animations.

## 12. DB schema and seed data

### `inventory.db`

```sql
CREATE TABLE inventory (
    item       TEXT PRIMARY KEY,
    stock      INTEGER NOT NULL,
    unit_price REAL    NOT NULL
);

CREATE TABLE vendors (
    name         TEXT PRIMARY KEY,   -- normalized: lowercase, no punctuation, no Inc/LLC/Co
    display_name TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('approved','pending','blocked'))
);
```

### Seed — inventory

| item    | stock | unit_price |
|---------|-------|------------|
| WidgetA | 15    | 250.00     |
| WidgetB | 10    | 500.00     |
| GadgetX | 5     | 750.00     |
| FakeItem| 0     | 0.00       |

### Seed — vendors (all `approved`)

Widgets Inc., Gadgets Co., Precision Parts Ltd., Global Supply Chain Partners, Acme Industrial Supplies, MegaWidgets Corp, Consolidated Materials Group, Summit Manufacturing Co., QuickShip Distributers, Atlas Industrial Supply, TechParts International, Reliable Components Inc.

Deliberately **not** seeded so the validator flags them: **Fraudster LLC** (INV-1003), **NoProd Industries** (INV-1008), and the empty vendor in INV-1009.

### Bootstrap

`app/db/init_db.py` reads `seed.yaml` and idempotently creates `inventory.db`. Runs on FastAPI startup if the file is missing. Also exposable as `python -m app.db.init_db --reset` to rebuild from seed.

## 13. Observability, testing, tooling

### Observability

- Single `event_emitter` per run. Every event: (1) appended to `state.events`, (2) appended to `logs/<run_id>.jsonl`, (3) pushed to the SSE queue.
- No `print` calls. Free-form strings only inside `detail` fields.
- Token + latency accounting on every LLM call; aggregated into `run.complete`.
- `python -m app.tools.replay --run_id=...` replays a jsonl trace, reconstructs final state, prints summary.

### Testing

| Layer | What | LLM |
|---|---|---|
| Unit | parsers, rule engine, normalization, validators, DB lookups, event emitter | mocked |
| Integration (golden) | full graph against all 16 sample invoices | **mocked** via recorded Grok responses |
| Live smoke | INV-1001 end-to-end against real Grok | real, opt-in via `RUN_LIVE_TESTS=1` |

**Golden fixtures.** `scripts/record_fixtures.py` hits the real API and writes `tests/fixtures/grok/<invoice>_<node>_<pass>.json`. Tests use a `MockGrokClient` keyed by prompt hash + invoice. Re-recording is one command; prompt changes require a re-record, which is visible in the diff.

**Expected outcomes** are encoded in `tests/expected_outcomes.yaml`:

```yaml
INV-1001: { outcome: approved, hard_blocks: [], warn_issues: [], suspicion: low }
INV-1002: { outcome: rejected, hard_blocks: [qty_exceeds_stock], warn_issues: [past_due_date], suspicion: low }
INV-1003: { outcome: rejected, hard_blocks: [out_of_stock], warn_issues: [unknown_vendor, past_due_date], suspicion: high }
INV-1008: { outcome: rejected, hard_blocks: [unknown_item, unknown_item], warn_issues: [unknown_vendor] }
INV-1009: { outcome: rejected, hard_blocks: [missing_vendor, negative_qty], warn_issues: [] }
```

(plus entries for all remaining sample invoices)

**Adversarial test invoices (authored, not provided):**
- **INV-9001** — extraction-confidence boundary; should land `needs_review`.
- **INV-9002** — duplicate of INV-1001 with different amount; documents duplicate-detection gap.
- **INV-9003** — JSON with subtotal/total mismatch; should `warn` on math, approve overall.
- **INV-9004** — multi-currency EUR invoice without conversion; should `warn` and route to needs_review.
- **INV-9005** — 50 line items; stress prompt size, confirm no truncation.

### Tooling

- Python 3.11+, deps pinned in `pyproject.toml` (uv preferred, pip-compatible). `ruff` for lint+format. `mypy --strict` on `app/`.
- Frontend: Vite + React 18 + TS strict + Tailwind; `pnpm` with `npm` fallback. No component library.
- Env: `.env` for `XAI_API_KEY`, `XAI_MODEL` (default `grok-4`). `.env.example` checked in.
- Scripts via Makefile: `make dev` (backend + frontend), `make test`, `make seed`, `make record-fixtures`, `make demo` (batch-run all 16).

## 14. Shipping order and cut-list

Each step leaves the system runnable:

1. **DB + seed + CLI smoke.** `init_db.py`, `rules.yaml`, one-file Grok client, all four nodes wired into LangGraph, CLI entry point. INV-1001 end-to-end.
2. **All 16 golden fixtures + test suite.** Record fixtures, encode expected outcomes, get integration tests green.
3. **FastAPI + SSE + trace files.** Wrap the graph in async, expose endpoints, write the event emitter. CLI still works.
4. **React shell + Timeline + Source/Extraction panels.** Minimum viable UI; single-run demo.
5. **Batch queue + DB Inspector + Critique panel.** Remaining UI surfaces.
6. **Adversarial test invoices + polish + README + demo script.**

If time slips, cut order is reverse: drop steps 5–6, then strip the frontend to a single timeline. Steps 1–3 ship the *required* prototype regardless.

## 15. Evaluation-criterion crosswalk

| Case criterion | How this design addresses it |
|---|---|
| Functionality (end-to-end) | All four stages implemented; CLI matches README; all 16 sample invoices have expected outcomes encoded and tested. |
| Code Quality | Pydantic everywhere, `mypy --strict`, ruff, structured logging only, single-purpose modules, golden-fixture tests. |
| Agentic Sophistication | LLM-driven extraction, structured outputs, validation tool calls, propose-critique-finalize loop with adversarial framing, retry-on-validation-error, fraud signals weighted into reasoning. |
| Shipping Mindset | Step 1 produces a working prototype; explicit cut-list documented; out-of-scope items called out. |
| Presentation | Business framing front-and-center in §1; demo script in README mapping pain points (30% errors, 5-day delays, frustrated stakeholders) to specific demo actions. |
| Above/Beyond | Extended DB schema (price + vendors), 5 authored adversarial invoices, full React UI with critique side-by-side, replay tool, batch runner. |
| UI/UX | Four-panel dashboard with live agent reasoning, batch queue, DB inspector, critique view; minimal visual language; everything in the trace is in the UI. |
