# Reconciliation / Retry UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users correct a failed or low-confidence extraction in the UI and re-run validation → approval → payment without re-running the LLM ingest pass. Directly addresses the case's "30% error rate" framing by closing the human-in-the-loop on extraction errors.

**Architecture:** Adds `POST /api/runs/{run_id}/retry` that accepts an edited `InvoiceData`, creates a new run seeded with that invoice, and dispatches the graph starting from validate. The ingest node short-circuits when `state.invoice` is already populated. The new run links to its parent via `parent_run_id` so the UI can show the chain.

**Tech Stack:** FastAPI (existing), Pydantic (existing), React + Zustand (existing), no new dependencies.

---

## File Structure

**Created:**
- `frontend/src/components/RetryButton.tsx` — wraps an edit-and-retry flow
- `backend/tests/test_retry_endpoint.py` — API-level tests for the retry endpoint

**Modified:**
- `backend/app/graph/state.py` — add `parent_run_id: str | None` to `InvoiceState`
- `backend/app/agents/ingest.py` — short-circuit when invoice is already seeded
- `backend/app/api/runs.py` — `RunRegistry.create_seeded(invoice, parent_run_id)` method
- `backend/app/api/routes.py` — new `POST /api/runs/{run_id}/retry` route; surface `parent_run_id` in summaries
- `backend/tests/test_ingest_agent.py` — assert seed-skip path
- `frontend/src/types/state.ts` — add `parent_run_id` to `InvoiceState`
- `frontend/src/api/client.ts` — `retryRun(runId, invoice)`
- `frontend/src/components/SourceAndExtraction.tsx` — editable extraction mode
- `frontend/src/pages/Dashboard.tsx` — render `RetryButton` and parent-link chip

---

## Task 1: Add parent_run_id to state

**Files:**
- Modify: `backend/app/graph/state.py`
- Test: `backend/tests/test_state_models.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_state_models.py`:

```python
def test_invoice_state_supports_parent_run_id():
    state = InvoiceState(
        run_id="r2", source_path="/tmp/x.txt", file_format="txt",
        parent_run_id="r1",
    )
    assert state.parent_run_id == "r1"


def test_invoice_state_parent_run_id_optional():
    state = InvoiceState(run_id="r1", source_path="/tmp/x.txt", file_format="txt")
    assert state.parent_run_id is None
```

If `InvoiceState` is not imported, ensure the import line is present.

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd backend && .venv/bin/pytest tests/test_state_models.py::test_invoice_state_supports_parent_run_id -v
```

Expected: `ValidationError: Extra inputs are not permitted` (Pydantic strict).

- [ ] **Step 3: Add the field**

In `backend/app/graph/state.py`, in `InvoiceState`, add after `run_id` and `source_path`:

```python
parent_run_id: str | None = None
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd backend && .venv/bin/pytest tests/test_state_models.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/graph/state.py backend/tests/test_state_models.py
git commit -m "feat(state): add parent_run_id to InvoiceState"
```

---

## Task 2: Ingest skip-when-seeded path

**Files:**
- Modify: `backend/app/agents/ingest.py`
- Modify: `backend/tests/test_ingest_agent.py`

- [ ] **Step 1: Write the failing test**

In `backend/tests/test_ingest_agent.py`, add (adjust imports/fixtures to match the file's existing style — search first):

```bash
cd backend && grep -n "run_ingest\|EventEmitter\|InvoiceState" tests/test_ingest_agent.py | head -20
```

```python
def test_ingest_skips_llm_when_invoice_already_seeded(tmp_path):
    """If state.invoice is already populated, ingest must not call the LLM
    — this is the seed path used by retry."""

    class _PoisonedLLM:
        def structured_complete(self, **kwargs):
            raise AssertionError("LLM must not be called when invoice is pre-seeded")

    src = tmp_path / "src.txt"
    src.write_text("ignored — not used because invoice is seeded")

    pre_invoice = InvoiceData(
        invoice_number="INV-X",
        vendor="Test Vendor",
        date=None, due_date=None,
        line_items=[LineItem(item="WidgetA", quantity=1, unit_price=250.0)],
        subtotal=250.0, tax_amount=0.0, total=250.0,
        currency="USD", payment_terms=None,
        raw_text="ignored",
    )
    state = InvoiceState(
        run_id="r1", source_path=str(src), file_format="txt",
        invoice=pre_invoice, parent_run_id="parent",
    )
    emitter = EventEmitter(run_id="r1", events=state.events, log_dir=tmp_path)

    out = run_ingest(state, llm=_PoisonedLLM(), emitter=emitter)

    assert out.invoice is pre_invoice
    assert any(e["kind"] == "ingest.skipped" for e in state.events)
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd backend && .venv/bin/pytest tests/test_ingest_agent.py::test_ingest_skips_llm_when_invoice_already_seeded -v
```

Expected: `AssertionError: LLM must not be called when invoice is pre-seeded`.

- [ ] **Step 3: Add the skip path**

In `backend/app/agents/ingest.py`, modify `run_ingest` to short-circuit when seeded. At the top of the function, after `emitter.emit("node.start", node="ingest")`, insert:

```python
    if state.invoice is not None:
        emitter.emit("ingest.skipped", node="ingest", reason="invoice pre-seeded (retry path)")
        emitter.emit("node.complete", node="ingest", output={
            "vendor": state.invoice.vendor,
            "total": state.invoice.total,
            "skipped": True,
        })
        return state
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd backend && .venv/bin/pytest tests/test_ingest_agent.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/ingest.py backend/tests/test_ingest_agent.py
git commit -m "feat(ingest): skip extraction when invoice is pre-seeded"
```

---

## Task 3: RunRegistry.create_seeded

**Files:**
- Modify: `backend/app/api/runs.py`
- Modify: `backend/tests/test_runs_registry.py`

- [ ] **Step 1: Write the failing test**

In `backend/tests/test_runs_registry.py`, add (check imports first):

```bash
cd backend && head -30 tests/test_runs_registry.py
```

```python
def test_create_seeded_carries_parent_and_invoice(tmp_path):
    from app.graph.state import InvoiceData, LineItem
    registry = RunRegistry(log_dir=tmp_path)
    invoice = InvoiceData(
        invoice_number="INV-X", vendor="V",
        date=None, due_date=None,
        line_items=[LineItem(item="WidgetA", quantity=1, unit_price=250.0)],
        subtotal=250.0, tax_amount=0.0, total=250.0,
        currency="USD", payment_terms=None, raw_text="",
    )
    run = registry.create_seeded(
        source_path="/tmp/x.txt", file_format="txt",
        invoice=invoice, parent_run_id="parent-id",
    )
    assert run.state.parent_run_id == "parent-id"
    assert run.state.invoice == invoice
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd backend && .venv/bin/pytest tests/test_runs_registry.py::test_create_seeded_carries_parent_and_invoice -v
```

Expected: `AttributeError: 'RunRegistry' object has no attribute 'create_seeded'`.

- [ ] **Step 3: Add the method**

In `backend/app/api/runs.py`, after the existing `create` method, add:

```python
    def create_seeded(
        self, *, source_path: str, file_format: str,
        invoice: "InvoiceData", parent_run_id: str,
    ) -> Run:
        run_id = uuid.uuid4().hex
        state = InvoiceState(  # type: ignore[arg-type]
            run_id=run_id, source_path=source_path, file_format=file_format,
            invoice=invoice, parent_run_id=parent_run_id,
        )
        emitter = _FanoutEmitter(run_id, state.events, self.log_dir)
        run = Run(run_id=run_id, state=state, emitter=emitter)
        emitter._run = run
        self._runs[run_id] = run
        return run
```

Add the `InvoiceData` import at the top:

```python
from app.graph.state import InvoiceData, InvoiceState
```

(Combine with the existing `InvoiceState` import if present.)

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd backend && .venv/bin/pytest tests/test_runs_registry.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/runs.py backend/tests/test_runs_registry.py
git commit -m "feat(runs): add create_seeded for retry path"
```

---

## Task 4: POST /api/runs/{run_id}/retry endpoint

**Files:**
- Modify: `backend/app/api/routes.py`
- Create: `backend/tests/test_retry_endpoint.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_retry_endpoint.py`. First check the existing API test pattern:

```bash
cd backend && head -50 tests/test_api.py
```

Follow that pattern — typically a `TestClient` fixture and a graph stub. Then write:

```python
from __future__ import annotations

from fastapi.testclient import TestClient


def test_retry_creates_child_run_with_seeded_invoice(api_client: TestClient, seeded_run_id: str):
    """Issuing retry with an edited invoice should:
    - create a new run
    - mark parent_run_id on the new run
    - seed the new run's invoice from the request body
    - dispatch the graph (we assert via the eventual final state)
    """
    edited = {
        "invoice_number": "INV-X-edit",
        "vendor": "Test Vendor",
        "date": None, "due_date": None,
        "line_items": [{"item": "WidgetA", "quantity": 1, "unit_price": 250.0, "notes": None}],
        "subtotal": 250.0, "tax_amount": 0.0, "total": 250.0,
        "currency": "USD", "payment_terms": None,
        "raw_text": "edited by user",
    }
    resp = api_client.post(
        f"/api/runs/{seeded_run_id}/retry", json={"invoice": edited},
    )
    assert resp.status_code == 200
    new_run_id = resp.json()["run_id"]
    assert new_run_id != seeded_run_id

    new_state = api_client.get(f"/api/runs/{new_run_id}").json()
    assert new_state["parent_run_id"] == seeded_run_id
    assert new_state["invoice"]["invoice_number"] == "INV-X-edit"


def test_retry_404_for_unknown_parent(api_client: TestClient):
    resp = api_client.post("/api/runs/does-not-exist/retry", json={"invoice": {}})
    assert resp.status_code == 404
```

If `api_client` and `seeded_run_id` fixtures don't exist, add them to `backend/tests/conftest.py`. Search first to avoid duplicating existing fixtures:

```bash
cd backend && grep -n "TestClient\|api_client\|seeded_run_id" tests/conftest.py tests/test_api.py
```

Reuse the existing pattern. If absent, here is a minimal version (adapt to the project's existing graph-stubbing pattern):

```python
from fastapi.testclient import TestClient
from app.api.app import build_app


@pytest.fixture
def api_client(tmp_path, seeded_db_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("INVOICE_PROCESSING_DB_PATH", str(seeded_db_path))
    monkeypatch.setenv("INVOICE_PROCESSING_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    app = build_app()
    return TestClient(app)


@pytest.fixture
def seeded_run_id(api_client: TestClient) -> str:
    files = {"file": ("inv.txt", b"INV-PARENT\nVendor: V\nTotal: 100\n", "text/plain")}
    resp = api_client.post("/api/runs", files=files)
    return resp.json()["run_id"]
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd backend && .venv/bin/pytest tests/test_retry_endpoint.py -v
```

Expected: `404` or `405` from FastAPI — the route doesn't exist yet.

- [ ] **Step 3: Add the retry route**

In `backend/app/api/routes.py`, after the existing `create_run` route inside `build_router`, add:

```python
    from pydantic import BaseModel
    from app.graph.state import InvoiceData

    class RetryRequest(BaseModel):
        invoice: InvoiceData

    @router.post("/runs/{run_id}/retry")
    async def retry_run(run_id: str, body: RetryRequest) -> dict[str, str]:
        parent = registry.get(run_id)
        if parent is None:
            raise HTTPException(404, "parent run not found")
        new_run = registry.create_seeded(
            source_path=parent.state.source_path,
            file_format=parent.state.file_format,
            invoice=body.invoice,
            parent_run_id=run_id,
        )
        asyncio.create_task(_run_graph(new_run.run_id))
        return {"run_id": new_run.run_id}
```

Move the `from pydantic import BaseModel` and `from app.graph.state import InvoiceData` imports to the top of the file rather than inline if the file already imports `InvoiceState` from the same module.

Also update the `_summary` helper to include `parent_run_id`:

```python
def _summary(state: InvoiceState) -> dict[str, Any]:
    decision = state.decision
    inv = state.invoice
    return {
        "run_id": state.run_id,
        "parent_run_id": state.parent_run_id,
        "source_path": state.source_path,
        "invoice_number": inv.invoice_number if inv else None,
        "vendor": inv.vendor if inv else None,
        "total": inv.total if inv else None,
        "outcome": (
            decision.outcome if decision else ("unprocessable" if state.error else "running")
        ),
        "error": state.error,
    }
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd backend && .venv/bin/pytest tests/test_retry_endpoint.py -v
```

Expected: both tests pass.

- [ ] **Step 5: Confirm full suite still passes**

```bash
cd backend && .venv/bin/pytest -x -q
```

Expected: green.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes.py backend/tests/test_retry_endpoint.py backend/tests/conftest.py
git commit -m "feat(api): POST /api/runs/{id}/retry with edited invoice"
```

---

## Task 5: Frontend types and API client

**Files:**
- Modify: `frontend/src/types/state.ts`
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Mirror parent_run_id in TS**

In `frontend/src/types/state.ts`, find `InvoiceState` and add:

```typescript
parent_run_id: string | null;
```

Also update the listRuns return type. Inspect `frontend/src/api/client.ts` lines 20-32 — that inline type definition needs a `parent_run_id: string | null` field added too.

- [ ] **Step 2: Add retryRun helper**

In `frontend/src/api/client.ts`, append:

```typescript
import type { InvoiceData } from "../types/state.ts";

export async function retryRun(
  runId: string, invoice: InvoiceData,
): Promise<{ run_id: string }> {
  const resp = await fetch(`/api/runs/${runId}/retry`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ invoice }),
  });
  if (!resp.ok) throw new Error(`retry failed: ${resp.status}`);
  return resp.json();
}
```

`InvoiceData` must be exported from `frontend/src/types/state.ts` for this import to compile. Verify:

```bash
grep -n "export type InvoiceData\|export interface InvoiceData" /Users/mwakichako/repos/invoice-processing/frontend/src/types/state.ts
```

If not exported, add `export` to its declaration.

- [ ] **Step 3: Typecheck**

```bash
cd frontend && npm run build
```

Expected: clean. If there's a separate `npm run typecheck`, run that.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/state.ts frontend/src/api/client.ts
git commit -m "feat(frontend): retryRun API client and parent_run_id types"
```

---

## Task 6: Edit-mode in SourceAndExtraction + RetryButton

**Files:**
- Create: `frontend/src/components/RetryButton.tsx`
- Modify: `frontend/src/components/SourceAndExtraction.tsx`
- Modify: `frontend/src/pages/Dashboard.tsx`

- [ ] **Step 1: Inspect SourceAndExtraction current shape**

```bash
cat /Users/mwakichako/repos/invoice-processing/frontend/src/components/SourceAndExtraction.tsx
```

Note the props it accepts and how it currently renders extracted fields. The edit mode must integrate with that shape, not replace it.

- [ ] **Step 2: Add a draft state and editable fields**

Modify `SourceAndExtraction.tsx`. The pattern: keep current view-only rendering, add an `isEditing` boolean state, and when editing render `<input>` / `<textarea>` for each field of `InvoiceData`. On save, call the new prop `onRetry(draft)`.

Add to the component's props type:

```typescript
type Props = {
  // ...existing props
  invoice: InvoiceData | null;
  onRetry?: (edited: InvoiceData) => void;
};
```

At the top of the component body:

```typescript
const [isEditing, setIsEditing] = React.useState(false);
const [draft, setDraft] = React.useState<InvoiceData | null>(invoice);
React.useEffect(() => { setDraft(invoice); }, [invoice]);
```

When `isEditing && draft` render a form. Use minimal markup — one input per scalar field, a textarea for `raw_text`, and an array editor for `line_items` (add/remove rows, edit quantity and unit_price). Keep the form short: a single column, no validation beyond `number` types on numeric inputs.

The "Save & retry" button calls `onRetry(draft)` then sets `isEditing(false)`. A "Cancel" button reverts `draft` and exits edit mode.

If the existing component uses Tailwind classes consistently, match that style.

- [ ] **Step 3: Create RetryButton**

Create `frontend/src/components/RetryButton.tsx`:

```typescript
import * as React from "react";
import type { InvoiceData } from "../types/state.ts";
import { retryRun } from "../api/client.ts";

type Props = {
  parentRunId: string;
  invoice: InvoiceData;
  onRetried: (newRunId: string) => void;
};

export function RetryButton({ parentRunId, invoice, onRetried }: Props) {
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const handle = async () => {
    setPending(true);
    setError(null);
    try {
      const { run_id } = await retryRun(parentRunId, invoice);
      onRetried(run_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "retry failed");
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={handle}
        disabled={pending}
        className="px-3 py-1 bg-blue-600 text-white rounded disabled:opacity-50"
      >
        {pending ? "Retrying…" : "Save & retry"}
      </button>
      {error && <span className="text-sm text-red-600">{error}</span>}
    </div>
  );
}
```

Wire `SourceAndExtraction` to use this button in edit mode (replace the plain "Save & retry" button stub from Step 2 with `<RetryButton ...>`).

- [ ] **Step 4: Wire it into Dashboard**

In `frontend/src/pages/Dashboard.tsx`, locate where `SourceAndExtraction` is rendered. Pass an `onRetry` handler that calls `RetryButton` semantics, or pass props through so the child renders the button. After a successful retry, select the new run in the run store so the timeline switches to it.

If the store has a `selectRun(runId)` method, use it:

```typescript
const onRetried = (newRunId: string) => {
  store.selectRun(newRunId);
};
```

If not, inspect `frontend/src/store/runStore.ts` and use whatever the existing selection pattern is.

- [ ] **Step 5: Show parent-link chip on retried runs**

Where the Dashboard renders run metadata (header area, run summary), if `state.parent_run_id` is set, render a small chip:

```tsx
{state.parent_run_id && (
  <button
    type="button"
    onClick={() => store.selectRun(state.parent_run_id!)}
    className="text-xs px-2 py-0.5 bg-gray-100 rounded border hover:bg-gray-200"
  >
    ↩ Retry of {state.parent_run_id.slice(0, 8)}
  </button>
)}
```

- [ ] **Step 6: Build the frontend**

```bash
cd frontend && npm run build
```

Expected: clean.

- [ ] **Step 7: Manual smoke test**

```bash
# Terminal 1
cd backend && .venv/bin/uvicorn app.api.app:app --reload
# Terminal 2
cd frontend && npm run dev
```

In the browser:
1. Upload `data/invoices/invoice_1009.json` (the negative-quantity case — likely to fail validation).
2. Wait for it to finish. Confirm the outcome is `rejected` or `needs_review`.
3. Click an "Edit" toggle on the extraction panel. Fix the negative quantity (e.g., set it to a positive number).
4. Click "Save & retry". Confirm a new run appears, the timeline switches to it, and a "↩ Retry of …" chip is visible.
5. Confirm the new run's `parent_run_id` matches the original via `GET /api/runs/<new_id>`.
6. Click the chip — selection should jump back to the parent.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/RetryButton.tsx frontend/src/components/SourceAndExtraction.tsx frontend/src/pages/Dashboard.tsx
git commit -m "feat(ui): editable extraction with retry button and parent-link chip"
```

---

## Task 7: README and demo note

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a section under UI features**

Insert under the existing UI features list:

```markdown
- **Reconciliation & retry**: click "Edit" on any extraction to correct fields
  (typos, missing values, negative quantities), then "Save & retry" — a new run
  is dispatched that skips ingest and re-validates, re-approves, and re-pays
  from your edits. New runs link back to their parent so you can compare the
  before/after side-by-side.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document retry/reconciliation flow"
```

---

## Self-Review Notes (for plan-writer's reference)

- Tasks 1, 2, 3 are mostly independent and could parallelise; Task 4 depends on all three.
- Task 5 depends only on the API contract being stable from Task 4.
- Task 6 is the bulk of frontend work — the SourceAndExtraction edit form is the riskiest part. Keep validation minimal and trust the backend Pydantic model to catch bad shapes (the retry endpoint returns 422 on a bad InvoiceData, which the frontend already surfaces via `retryRun`'s thrown error).
- Idempotency: payment_tool already de-dupes by invoice_number in a `paid_invoices` set. If a user edits an invoice and re-pays, the same invoice_number will be rejected as a duplicate. This is the correct behaviour — but call it out in the UI: if the parent was paid, warn before retry. (Out of scope for this plan, but worth a follow-up.)
