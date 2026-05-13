# Demo runbook

A 5-minute walkthrough of the three eval-criteria highlights: **agentic tool use**, **reconciliation / retry**, and **business-impact metrics**.

## Prerequisites

```bash
# One-time, from repo root
cd /Users/mwakichako/repos/invoice-processing
make -C backend install         # python deps
make -C backend seed            # creates backend/data/inventory.db
cd frontend && npm install
```

## Start both servers

```bash
# Terminal 1 — backend
cd /Users/mwakichako/repos/invoice-processing
export XAI_API_KEY=...          # your live key
.venv/bin/uvicorn app.api.app:app --reload --app-dir backend --port 8000

# Terminal 2 — frontend
cd /Users/mwakichako/repos/invoice-processing/frontend
npm run dev                     # http://localhost:5173
```

> The backend reads `XAI_API_KEY` (not `X_API_KEY`). If extraction fails, double-check the env var name.

Open `http://localhost:5173`. The MetricsTile shows zeros — that's expected for a fresh session.

## Scenario 1 — Agentic tool use (the "sophistication" criterion)

**What it shows:** the approve agent doesn't get inventory and vendor data spoon-fed in the prompt. On middle-band cases, an *investigate* pass lets the LLM call `lookup_inventory`, `lookup_vendor`, or `recompute_totals` on its own.

**Demo:**

1. Drop `backend/data/invoices/invoice_1002.txt` onto the upload zone (this invoice requests 20× GadgetX, only 5 in stock — a middle-band case).
2. Watch the timeline. Under the `approve` stage you'll see purple `tool` rows as the LLM investigates.
3. When the run finishes, open the **Critique panel**. The new "Investigation tool calls" section lists each call with arguments → result and latency.

Compare with a simple case: drop `invoice_1001.txt`. The rule engine auto-approves, so investigate is skipped (no tool rows, predictable cost).

**Talking point:** "The LLM decides when to use tools. Auto-approve and hard-block paths are deterministic and stay cheap; only the genuinely ambiguous middle-band cases pay the investigate cost."

## Scenario 2 — Reconciliation & retry (closes the loop on the 30% error rate)

**What it shows:** when extraction is wrong (typo, missing field, negative quantity), users edit in place and dispatch a child run — without re-running ingest.

**Demo:**

1. Drop `backend/data/invoices/invoice_1009.json` (negative quantity → rejection).
2. Wait for the run to finish with outcome **rejected**.
3. In the extraction panel, click **Edit**. The form switches to inputs for every field.
4. Fix the negative quantity (set it to a positive number). Click **Save & retry**.
5. The timeline switches to the new run. A `↩ Retry of <parent_id>` chip appears at the top of the extraction panel.
6. Click the chip — selection jumps back to the parent. Click forward to the retry to see the new outcome.

**Talking point:** "Manual processing's 30% error rate doesn't go away just because an LLM is in the loop — you need a way to correct extraction errors. Edits feed straight into validate → approve → pay, with parent_run_id linking the chain for audit."

## Scenario 3 — Business-impact metrics (the "presentation" criterion)

**What it shows:** the dashboard's top tile is live across every run, translating technical outcomes into the case study's business framing.

**Demo:**

1. From a clean session (refresh the page), click **Run all 16** (the batch button).
2. Watch the MetricsTile update as runs complete:
   - **Invoices processed** → 16
   - **Auto-approved (%)** → the share that cleared without scrutiny
   - **Avg processing time** → real seconds, with sub-label "vs. ~5 days manual"
   - **Total approved** → dollar value cleared
   - **Simulated savings** → `$192` (16 × $12 default manual cost)

Want a bigger number? Stop the backend, set `MANUAL_COST_PER_INVOICE_USD=25` in `backend/.env`, restart, refresh — savings jumps to `$400`.

**Talking point:** "$12/invoice is an industry benchmark for fully-loaded AP manual processing. Plug in your org's number and the savings figure tracks with reality. The 'vs. 5 days manual' sub-label is the eval-criterion payoff in one phrase."

## Reset between demos

The run registry is in-memory. To reset metrics and the run list, restart the backend (`Ctrl-C` and re-run uvicorn). The inventory DB is persistent and doesn't need re-seeding.

## What to acknowledge if asked

- **Retried runs double-count in `simulated_dollars_saved`.** Each automated run is $12 saved; a retry is technically a second automated run. Demos rarely involve retries so the math reads cleanly; a follow-up could filter `parent_run_id is not None`.
- **The graph isn't persisted.** Restart the backend and the run history is gone. This is intentional for the prototype; a follow-up is to persist runs to SQLite.
- **OCR is not implemented.** Scanned PDFs surface a clear error. The sample set includes one OCR-typo'd PDF (`invoice_1012.pdf`) that exercises *string-normalisation* (Widget A → WidgetA) but not actual OCR.

## Live smoke test

If you want a one-shot end-to-end verification against the real API:

```bash
cd /Users/mwakichako/repos/invoice-processing
RUN_LIVE_TESTS=1 .venv/bin/pytest backend/tests/test_live_smoke.py -v
```
