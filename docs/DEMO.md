# Demo runbook

A 5-minute walkthrough of the three eval-criteria highlights: **agentic tool use**, **reconciliation / retry**, and **business-impact metrics**.

> UI references on this page match the `feature/ui-improvement` branch (Case File redesign). See [README.md](../README.md) for the high-level tour and screenshots.

## Prerequisites

```bash
# One-time, from repo root
python3 -m venv .venv
source .venv/bin/activate
make -C backend install         # python deps
cp backend/.env.example backend/.env
# Open backend/.env and set XAI_API_KEY=<your key>
make -C backend seed            # creates backend/data/inventory.db
cd frontend && npm install && cd ..
```

## Start both servers

```bash
# Terminal 1 — backend (from repo root)
source .venv/bin/activate
uvicorn app.api.app:app --reload --app-dir backend --port 8000

# Terminal 2 — frontend (from repo root)
cd frontend
npm run dev                     # http://localhost:5173
```

> The backend reads `XAI_API_KEY` (not `X_API_KEY`). If ingest fails fast, double-check the env-var name in `backend/.env`.

Open `http://localhost:5173`. You should see the **empty state** intro card with three sample buttons and a metrics band reading zeros — that's expected for a fresh session.

## Scenario 1 — Agentic tool use (the "sophistication" criterion)

**What it shows:** the approve agent doesn't get inventory and vendor data spoon-fed in the prompt. On middle-band cases, an *investigate* pass lets the LLM call `lookup_inventory`, `lookup_vendor`, or `recompute_totals` on its own.

**Demo:**

1. Click **Upload invoice** in the top bar and pick `backend/data/invoices/invoice_1002.txt` (this invoice requests 20× GadgetX, only 5 in stock — a middle-band case).
2. The browser navigates to the Case File. Watch the **stage strip** (sticky bar under the hero card): the `Approve` pip pulses indigo as the LLM investigates.
3. When the run finishes, scroll to the **Agent reasoning** section. The **Propose** card has a "Tools consulted" footer listing each call as `tool({args}) → {result}`.

Compare with a simple case: from the batch overview, click the `INV-1001` sample button. The rule engine auto-approves, so investigate is skipped — no tool calls listed, predictable cost.

**Talking point:** "The LLM decides when to use tools. Auto-approve and hard-block paths are deterministic and stay cheap; only the genuinely ambiguous middle-band cases pay the investigate cost."

## Scenario 2 — Reconciliation & retry (closes the loop on the 30% error rate)

**What it shows:** when extraction is wrong (typo, missing field, negative quantity), users edit in place and dispatch a child run — without re-running ingest.

**Demo:**

1. **Upload invoice** → pick `backend/data/invoices/invoice_1009.json` (negative quantity → rejection).
2. Wait for the run to finish with outcome **Rejected** (chip turns rose).
3. In the **Extraction** panel (right side of the source/extraction split), edit any field directly — every input is live. Fix the negative quantity to a positive number.
4. Click **Save & retry**. The button is disabled until the draft is both dirty and valid (no field errors).
5. The browser navigates to the new run (child). The **left rail** shows the retry indented under its parent with a `↳ retry` label.
6. Click the parent row in the left rail. The original Case File shows a **"Superseded by retry · run <id>"** banner under the breadcrumb — one click away from the corrected run.

**Talking point:** "Manual processing's 30% error rate doesn't go away just because an LLM is in the loop — you need a way to correct extraction errors. Edits feed straight into validate → approve → pay, with `parent_run_id` linking the chain for audit."

## Scenario 3 — Business-impact metrics (the "presentation" criterion)

**What it shows:** the **metrics band** above every page is live across the whole session, translating technical outcomes into the case study's business framing.

**Demo:**

1. Refresh the page for a clean session, then click **Run all 16** in the top bar.
2. Watch the metrics band update as runs complete:
   - **Runs processed** → 16
   - **Auto-approved** → count + `(%)` cleared without scrutiny
   - **Avg processing time** → real seconds, with sub-label `vs. ~5 days manual`
   - **Total approved** → dollar value cleared
   - **Simulated savings** → `$192` (16 × $12 default manual cost)
3. The batch overview header shows a progress bar; the left rail's session card mirrors it. Up to 4 rows can be `Running` at a time (4-way semaphore in the backend).

Want a bigger savings figure? Stop the backend, set `MANUAL_COST_PER_INVOICE_USD=25` in `backend/.env`, restart, refresh — savings jumps to `$400`.

**Talking point:** "$12/invoice is an industry benchmark for fully-loaded AP manual processing. Plug in your org's number and the savings figure tracks with reality. The `vs. ~5 days manual` sub-label is the eval-criterion payoff in one phrase."

## Reset between demos

The run registry is in-memory. To reset metrics and the run list, restart the backend (`Ctrl-C` and re-run uvicorn). The inventory DB is persistent and doesn't need re-seeding.

## What to acknowledge if asked

- **Retried runs double-count in `simulated_dollars_saved`.** Each automated run is $12 saved; a retry is technically a second automated run. Demos rarely involve retries so the math reads cleanly; a follow-up could filter `parent_run_id IS NOT NULL`.
- **The run history isn't persisted.** Restart the backend and the run list is gone. Intentional for the prototype; a follow-up is to persist runs to SQLite.
- **OCR is not implemented.** Scanned PDFs surface a clear error. The sample set includes one OCR-typo'd PDF (`invoice_1012.pdf`) that exercises *string-normalisation* (`Widget A` → `WidgetA`, `26-Jan-2O26` → `2026-01-26`) but not actual OCR.

## Live smoke test

For a one-shot end-to-end verification against the real Grok API:

```bash
source .venv/bin/activate
RUN_LIVE_TESTS=1 pytest backend/tests/test_live_smoke.py -v
```
