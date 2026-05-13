# Acme AP — Invoice Processing Automation

A working multi-agent prototype that ingests invoices in six formats (PDF, TXT, JSON, CSV, XML, email), validates them against an inventory database, runs an approver with a peer-critique loop, and pays approved invoices or logs rejections — end-to-end in seconds, with the full reasoning trace visible in a web UI.

## Why this matters

Acme Corp's manual workflow loses $2M/year:

- **30% error rate.** Six classes of error caught automatically (missing vendor, negative quantity, unknown item, out-of-stock, overstock, price drift). The propose-critique-finalize loop in the approver catches what a single LLM pass would miss. **See:** outcome breakdown in the metrics tile.
- **5-day delays.** Each invoice resolves in seconds. The "Run all 16" button processes the entire sample backlog while you watch. **See:** average processing time on the metrics tile.
- **Frustrated stakeholders.** Every decision carries a written rationale tied to named rules. AP, vendors, and the VP read the same trace. **See:** the Critique panel.

## Numbers you can read off the screen

The dashboard's top tile is live across every run in the session:

| Metric | What it answers |
|---|---|
| Runs processed | How many runs this session (includes retries) |
| Auto-approved (count and %) | What share clears without human review |
| Avg processing time | Throughput vs. the 5-day manual baseline |
| Total approved | Dollar value cleared |
| Simulated savings | Runs × `MANUAL_COST_PER_INVOICE_USD` (default $12, override in `.env`) |

The $12/invoice default is an industry benchmark for fully-loaded AP manual processing — set the env var to your org's number for a credible bottom-line figure on the demo.

## Quick start

```bash
make install           # one-time
export XAI_API_KEY=... # see .env.example
make seed              # creates data/inventory.db from seed.yaml
make demo              # runs all 16 sample invoices via CLI
```

For the UI:

```bash
make dev               # FastAPI on :8000
cd frontend && npm install && npm run dev    # React on :5173
```

Open `http://localhost:5173`, drop any file from `data/invoices/`, watch the agents work.

## Architecture

LangGraph state machine with four agent nodes:

```
ingest → validate → approve → pay   (or → log on reject/needs_review)
```

- **Ingest** — one Grok call per invoice with Pydantic structured output; retries once on validation failure.
- **Validate** — deterministic SQL checks against inventory and approved-vendors tables. Eight failure modes.
- **Approve** — investigate (tool-using on middle-band cases), then three sequential Grok calls: proposer, adversarial critic, finalizer. During investigate, the LLM may call `lookup_inventory`, `lookup_vendor`, or `recompute_totals` via xAI's function-calling API; results are captured on `Decision.tool_calls` and rendered in the UI. A rule engine (`rules.yaml`) provides hard blocks and gate thresholds; the LLM cannot override hard blocks.
- **Pay / Log** — mock payment API or structured rejection log.

Full design: [`docs/superpowers/specs/2026-05-13-invoice-processing-design.md`](docs/superpowers/specs/2026-05-13-invoice-processing-design.md).

## What's in the UI

- **Timeline** — live agent status with per-pass detail in the approver
- **Source / Extracted** — original file alongside the structured extraction; suspicion signals as red chips
- **Critique view** — initial proposal vs. critic vs. final, with changes highlighted
- **Reconciliation & retry** — toggle "Edit" on any extraction to correct fields (typos, missing values, negative quantities), then "Save & retry" dispatches a new run that skips ingest and re-validates from your edits. Retried runs link back to their parent with a "↩ Retry of …" chip so before/after comparisons are one click apart.
- **DB Inspector** — inventory and vendor tables; rows touched by the current run are highlighted
- **Batch queue** — every run with outcome chips, one click to inspect

## Demo script (3 minutes)

1. **INV-1001** (clean approve). Drop the file. Show: timeline fills in green; critique agrees; payment receipt appears. The whole run took ~5s.
2. **INV-1003** (fraud). Show: suspicion chips light up (urgency, wire-transfer demand, "yesterday" due date); validator flags `out_of_stock` + `unknown_vendor`; rule engine forces rejection; rationale cites all three rules.
3. **INV-1012** (OCR typos). Show: extraction succeeds despite "Widget A" vs "WidgetA", `26-Jan-2O26`, `$3,500.O0`. The validator still finds the right inventory rows because we normalize.
4. **"Run all 16"**. Watch the queue fill in seconds. Click through to a couple to highlight different outcomes.

## Testing

```bash
make test                        # unit + golden integration (mocked LLM, deterministic)
RUN_LIVE_TESTS=1 make test       # also runs the live-LLM smoke test
```

Fixtures are recorded with `make record-fixtures` (requires an API key) and committed.

## Repository

```
backend/  — python + langgraph + fastapi
frontend/ — vite + react + tailwind + zustand
docs/     — design spec + this plan
```
