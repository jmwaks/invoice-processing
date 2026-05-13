# UI Redesign — Case File Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the frontend as a "case file" UI for stakeholder demos — modern fintech aesthetic, end-to-end auditable single-invoice view, batch overview portfolio, persistent metrics scoreboard.

**Architecture:** Single-page React app driven by URL (wouter). Two main-pane modes — Batch Overview (`/`) and Case File (`/runs/:id`) — wrapped in an AppShell of TopBar + permanent MetricsBand + LeftRail. Backend gains two small additions: an optional `text_match` field on `SuspicionSignal` and a `POST /api/runs/sample/{filename}` route for the demo's one-click sample buttons. Frontend state machine inherits the existing pattern: poll `/api/runs` every 1.5s for the runs list; open SSE only for the currently-viewed run.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, pytest (backend). React 18, TypeScript, Vite, Tailwind, zustand, @tanstack/react-query, **wouter** (new), **lucide-react** (new), Inter + JetBrains Mono fonts (new).

**Spec:** `docs/superpowers/specs/2026-05-13-ui-redesign-case-file.md`

**Testing posture:**
- **Backend:** strict TDD with pytest. Every backend change starts with a failing test.
- **Frontend:** the existing codebase has no test runner. We do not add one in this plan. Each frontend task ends with `npx tsc --noEmit` passing and `npm run build` succeeding. Phase boundaries include a manual dev-server check against named acceptance criteria from §13 of the spec.

**Branch:** `feature/ui-improvement` (already current).

---

## Phase 1 — Backend deltas & shared types

### Task 1: `SuspicionSignal.text_match` field

**Files:**
- Modify: `backend/app/graph/state.py:30-40`
- Modify: `backend/tests/test_state_models.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_state_models.py`:

```python
def test_suspicion_signal_text_match_defaults_to_none():
    from app.graph.state import SuspicionSignal

    sig = SuspicionSignal(kind="urgent_language", detail="says URGENT", severity="medium")
    assert sig.text_match is None


def test_suspicion_signal_accepts_text_match_phrase():
    from app.graph.state import SuspicionSignal

    sig = SuspicionSignal(
        kind="wire_transfer_demand",
        detail="demands wire transfer",
        severity="high",
        text_match="wire transfer required within 24 hours",
    )
    assert sig.text_match == "wire transfer required within 24 hours"


def test_suspicion_signal_text_match_round_trips_json():
    from app.graph.state import SuspicionSignal

    sig = SuspicionSignal(
        kind="urgent_language", detail="x", severity="low",
        text_match="URGENT — pay now",
    )
    payload = sig.model_dump_json()
    restored = SuspicionSignal.model_validate_json(payload)
    assert restored.text_match == "URGENT — pay now"
```

- [ ] **Step 2: Run test to verify it fails**

Run from `backend/`:
```bash
cd backend && pytest tests/test_state_models.py::test_suspicion_signal_text_match_defaults_to_none tests/test_state_models.py::test_suspicion_signal_accepts_text_match_phrase tests/test_state_models.py::test_suspicion_signal_text_match_round_trips_json -v
```
Expected: FAIL with `unexpected keyword argument 'text_match'` or `AttributeError`.

- [ ] **Step 3: Add the optional field**

In `backend/app/graph/state.py`, modify the `SuspicionSignal` model (around lines 30-40):

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
    detail: str
    severity: Literal["low", "medium", "high"]
    text_match: str | None = None
```

- [ ] **Step 4: Run tests and verify they pass**

```bash
cd backend && pytest tests/test_state_models.py -v
```
Expected: all tests in the file PASS (including the three new ones).

- [ ] **Step 5: Run the full backend suite to confirm no regressions**

```bash
cd backend && pytest -q
```
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/graph/state.py backend/tests/test_state_models.py
git commit -m "feat(state): optional text_match field on SuspicionSignal"
```

---

### Task 2: Ingest agent emits `text_match`

**Files:**
- Modify: `backend/app/agents/ingest.py:22-50` (SYSTEM_PROMPT)
- Test: `backend/tests/test_ingest_agent.py` (modify or extend)

- [ ] **Step 1: Find the existing ingest test to extend**

```bash
grep -n "suspicion" backend/tests/test_ingest_agent.py
```

If a suspicion test already exists, extend it. If not, add a new test that mocks the LLM to return a payload with `text_match`.

- [ ] **Step 2: Write the failing test**

Append to `backend/tests/test_ingest_agent.py`:

```python
def test_ingest_passes_text_match_through_from_llm(monkeypatch, tmp_path):
    """The ingest agent must propagate text_match from the LLM response to state."""
    from unittest.mock import MagicMock
    from pathlib import Path

    from app.agents.ingest import IngestResponse, run_ingest
    from app.graph.state import InvoiceData, InvoiceState, SuspicionSignal
    from app.logging_.event_emitter import EventEmitter

    invoice_text = "URGENT — wire transfer required within 24 hours. Vendor: X. Total: $100."
    src = tmp_path / "inv.txt"
    src.write_text(invoice_text)

    fake_invoice = InvoiceData(
        invoice_number="X-1", vendor="X", date=None, due_date=None,
        line_items=[], subtotal=None, tax_amount=None, total=100.0, raw_text=invoice_text,
    )
    fake_response = IngestResponse(
        invoice=fake_invoice,
        suspicion_signals=[
            SuspicionSignal(
                kind="wire_transfer_demand",
                detail="demands wire within 24 hours",
                severity="high",
                text_match="wire transfer required within 24 hours",
            ),
        ],
        extraction_confidence=0.9,
    )
    fake_meta = MagicMock(tokens_in=1, tokens_out=1, latency_ms=1, model="fake")

    fake_llm = MagicMock()
    fake_llm.structured_complete.return_value = (fake_response, fake_meta)

    state = InvoiceState(run_id="r1", source_path=str(src), file_format="txt")
    emitter = EventEmitter("r1", state.events, tmp_path)
    out = run_ingest(state, llm=fake_llm, emitter=emitter)

    assert len(out.suspicion_signals) == 1
    assert out.suspicion_signals[0].text_match == "wire transfer required within 24 hours"
```

- [ ] **Step 3: Run test to verify it passes**

Because Pydantic accepts the new optional field with a default of `None`, this test should already pass once Task 1 is done. Run:
```bash
cd backend && pytest tests/test_ingest_agent.py::test_ingest_passes_text_match_through_from_llm -v
```
Expected: PASS.

(If it fails, the propagation in `ingest.py` line 96 — `state.suspicion_signals = parsed.suspicion_signals` — is broken. Investigate.)

- [ ] **Step 4: Update the SYSTEM_PROMPT to instruct the LLM to emit `text_match`**

In `backend/app/agents/ingest.py`, modify `SYSTEM_PROMPT` (around lines 22-50). Replace the existing block with:

```python
SYSTEM_PROMPT = """You are an invoice extractor.
Convert the provided invoice text into a structured JSON object.

Rules:
- Extract values verbatim from the source. Do not invent values.
- If a field is missing or unreadable, return null. Do not guess.
- Dates use YYYY-MM-DD. If the source says "yesterday" or another relative term,
  return null and note it as a suspicion signal.
- Quantities are integers; preserve negative values as written.
- Flag suspicion signals for any of:
  * urgent / threatening language ("URGENT", "pay immediately", "wire transfer")
  * dates in the past or expressed as "yesterday"
  * round-number totals on otherwise odd line items
  * generic or alarming vendor names
  * unknown / made-up looking item names
- For each suspicion signal, when possible, set `text_match` to the EXACT verbatim
  phrase from the source that triggered the signal (e.g. "wire transfer required
  within 24 hours"). The phrase must appear in the source character-for-character.
  Omit `text_match` (return null) only when no single phrase captures the signal.
- Confidence is your self-assessment: 1.0 = perfect, 0.5 = needs human re-check, <0.3 = unreadable.

Return JSON matching this schema exactly:
{
  "invoice": {
    invoice_number, vendor, date, due_date,
    line_items:[{item, quantity, unit_price, notes}],
    subtotal, tax_amount, total, currency, payment_terms, raw_text
  },
  "suspicion_signals": [{ kind, detail, severity, text_match }],
  "extraction_confidence": number
}
The raw_text field should echo the input text exactly.
"""
```

- [ ] **Step 5: Run the ingest tests + full suite**

```bash
cd backend && pytest tests/test_ingest_agent.py tests/test_state_models.py -v && pytest -q
```
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/agents/ingest.py backend/tests/test_ingest_agent.py
git commit -m "feat(ingest): emit text_match phrase per suspicion signal"
```

---

### Task 3: `POST /api/runs/sample/{filename}` endpoint

**Files:**
- Modify: `backend/app/api/routes.py` (after the `run_batch` route, before `metrics`)
- Create: `backend/tests/test_sample_endpoint.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_sample_endpoint.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def sample_api_client(tmp_path, seeded_db_path, monkeypatch):
    """A TestClient whose invoices dir contains a single known sample file."""
    from unittest.mock import MagicMock

    from app.api.app import create_app
    from app.config import get_settings

    # Build a sample invoices dir on tmp_path
    invoices_dir = tmp_path / "invoices"
    invoices_dir.mkdir()
    (invoices_dir / "INV-SAMPLE.txt").write_text(
        "Invoice\nVendor: Acme\nWidgetA x 1 @ $10\nTotal: $10\n"
    )

    # Patch the settings to point at our sample dir
    settings = get_settings()
    monkeypatch.setattr(settings, "invoice_processing_invoices_dir", invoices_dir)

    fake_llm = MagicMock()
    fake_llm.structured_complete.side_effect = RuntimeError("no LLM in sample test")
    app = create_app(llm=fake_llm, db_path=seeded_db_path, log_dir=tmp_path / "logs")
    return TestClient(app), invoices_dir


def test_sample_endpoint_creates_run_for_known_file(sample_api_client):
    client, _ = sample_api_client
    resp = client.post("/api/runs/sample/INV-SAMPLE.txt")
    assert resp.status_code == 200
    body = resp.json()
    assert "run_id" in body
    assert len(body["run_id"]) > 0


def test_sample_endpoint_returns_404_for_missing_file(sample_api_client):
    client, _ = sample_api_client
    resp = client.post("/api/runs/sample/does-not-exist.txt")
    assert resp.status_code == 404


def test_sample_endpoint_rejects_path_traversal_dot_dot(sample_api_client):
    client, _ = sample_api_client
    resp = client.post("/api/runs/sample/..%2Fetc%2Fpasswd")
    # FastAPI decodes; we then guard against ".." and slashes
    assert resp.status_code in (400, 404)


def test_sample_endpoint_rejects_filename_with_slash(sample_api_client):
    client, _ = sample_api_client
    resp = client.post("/api/runs/sample/subdir%2Ffile.txt")
    assert resp.status_code in (400, 404)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && pytest tests/test_sample_endpoint.py -v
```
Expected: FAIL with `404` for the happy-path test (endpoint doesn't exist yet — FastAPI returns 404 for unknown routes).

- [ ] **Step 3: Add the endpoint**

In `backend/app/api/routes.py`, insert this route immediately after the `run_batch` handler (after line 122, before `metrics` at line 124). Use the same indentation level (8 spaces — inside `build_router`):

```python
    @router.post("/runs/sample/{filename}")
    async def create_run_from_sample(filename: str) -> dict[str, str]:
        from app.config import get_settings
        invoices_dir = get_settings().invoice_processing_invoices_dir.resolve()
        # Reject path traversal: filename must be a single path component.
        if "/" in filename or "\\" in filename or filename in {".", ".."}:
            raise HTTPException(400, "invalid filename")
        target = (invoices_dir / filename).resolve()
        if not target.is_relative_to(invoices_dir) or not target.is_file():
            raise HTTPException(404, "sample not found")
        loaded = load_invoice_file(target)
        run = registry.create(source_path=str(target), file_format=loaded.format)
        asyncio.create_task(_run_graph(run.run_id))
        return {"run_id": run.run_id}
```

- [ ] **Step 4: Run the new tests and the full suite**

```bash
cd backend && pytest tests/test_sample_endpoint.py -v && pytest -q
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes.py backend/tests/test_sample_endpoint.py
git commit -m "feat(api): POST /api/runs/sample/{filename} for demo sample buttons"
```

---

### Task 4: Frontend types + API client for new backend surface

**Files:**
- Modify: `frontend/src/types/state.ts:26-30` (add `text_match`)
- Modify: `frontend/src/api/client.ts` (add `createSampleRun`)

- [ ] **Step 1: Add `text_match` to the TypeScript `SuspicionSignal`**

Edit `frontend/src/types/state.ts`. Replace the `SuspicionSignal` interface (lines 26-30):

```ts
export interface SuspicionSignal {
  kind: string;
  detail: string;
  severity: SuspicionSeverity;
  text_match: string | null;
}
```

- [ ] **Step 2: Add `createSampleRun` to the API client**

Edit `frontend/src/api/client.ts`. Append at the bottom (after `getMetrics`):

```ts
export async function createSampleRun(filename: string): Promise<{ run_id: string }> {
  const resp = await fetch(`/api/runs/sample/${encodeURIComponent(filename)}`, {
    method: "POST",
  });
  if (!resp.ok) throw new Error(`sample run failed: ${resp.status}`);
  return resp.json();
}
```

- [ ] **Step 3: Type-check the frontend**

```bash
cd frontend && npx tsc --noEmit
```
Expected: zero errors. (Existing callers that destructure `SuspicionSignal` may now see a required `text_match` field. If any old fixture or test data omits it, fix by adding `text_match: null`.)

- [ ] **Step 4: Build the frontend to confirm**

```bash
cd frontend && npm run build
```
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/state.ts frontend/src/api/client.ts
git commit -m "feat(frontend): text_match field + createSampleRun API helper"
```

---

## Phase 2 — Frontend foundation

### Task 5: Install dependencies + configure fonts

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/index.html`
- Modify: `frontend/tailwind.config.js`

- [ ] **Step 1: Install wouter and lucide-react**

```bash
cd frontend && npm install wouter@^3.0.0 lucide-react@^0.400.0
```

- [ ] **Step 2: Load Inter and JetBrains Mono in index.html**

Replace `frontend/index.html` with:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Acme AP</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap"
      rel="stylesheet"
    />
  </head>
  <body class="bg-slate-50 text-slate-900 font-sans">
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 3: Extend tailwind.config.js with font families**

Replace `frontend/tailwind.config.js` with:

```js
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
    },
  },
  plugins: [],
};
```

- [ ] **Step 4: Type-check + build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```
Expected: both succeed.

- [ ] **Step 5: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/index.html frontend/tailwind.config.js
git commit -m "feat(frontend): add wouter + lucide-react + Inter/JetBrains Mono fonts"
```

---

### Task 6: Central Icons module

**Files:**
- Create: `frontend/src/components/common/Icons.tsx`

- [ ] **Step 1: Create the Icons module**

Create `frontend/src/components/common/Icons.tsx`:

```tsx
// Single import point for all Lucide icons used in the app.
// Keeps icon choices auditable in one place and trims unused ones from the bundle.
export {
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Circle,
  Loader2,
  Upload,
  Play,
  RotateCcw,
  ArrowLeft,
  Flag,
  Wrench,
  ScrollText,
  Receipt,
  FileSearch,
} from "lucide-react";
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npx tsc --noEmit
```
Expected: zero errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/common/Icons.tsx
git commit -m "feat(frontend): central Icons module re-exporting Lucide picks"
```

---

### Task 7: Extend runStore for `currentBatch` and `setActiveRunId`

**Files:**
- Modify: `frontend/src/store/runStore.ts`

- [ ] **Step 1: Extend the store**

Replace `frontend/src/store/runStore.ts` with:

```ts
import { create } from "zustand";
import type { RunEvent } from "../types/events.ts";
import type { Decision, InvoiceState } from "../types/state.ts";

type NodeStatus = "pending" | "running" | "complete" | "error";

interface NodeStageView {
  status: NodeStatus;
  startedAt?: string;
  completedAt?: string;
  summary?: any;
}

interface ApproveSubStages {
  propose: NodeStatus;
  critique: NodeStatus;
  finalize: NodeStatus;
}

export interface ActiveRunView {
  runId: string;
  events: RunEvent[];
  stages: Record<"ingest" | "validate" | "approve" | "pay" | "log", NodeStageView>;
  approveSubStages: ApproveSubStages;
  state: Partial<InvoiceState>;
  done: boolean;
}

export interface CurrentBatch {
  runIds: string[];
  startedAt: number;
}

interface Store {
  activeRunId: string | null;
  runs: Record<string, ActiveRunView>;
  currentBatch: CurrentBatch | null;
  selectRun: (runId: string) => void;
  setActiveRunId: (runId: string | null) => void;
  appendEvent: (runId: string, e: RunEvent) => void;
  initializeRun: (runId: string) => void;
  startBatch: (runIds: string[]) => void;
  clearBatchIfComplete: (doneRunIds: Set<string>) => void;
}

const emptyStages = (): ActiveRunView["stages"] => ({
  ingest: { status: "pending" },
  validate: { status: "pending" },
  approve: { status: "pending" },
  pay: { status: "pending" },
  log: { status: "pending" },
});

export const useRunStore = create<Store>((set, get) => ({
  activeRunId: null,
  runs: {},
  currentBatch: null,
  selectRun: (runId) => set({ activeRunId: runId }),
  setActiveRunId: (runId) => set({ activeRunId: runId }),
  initializeRun: (runId) =>
    set((s) => ({
      activeRunId: runId,
      runs: {
        ...s.runs,
        [runId]: {
          runId,
          events: [],
          stages: emptyStages(),
          approveSubStages: { propose: "pending", critique: "pending", finalize: "pending" },
          state: { run_id: runId },
          done: false,
        },
      },
    })),
  appendEvent: (runId, e) => {
    const current = get().runs[runId];
    if (!current) {
      get().initializeRun(runId);
    }
    set((s) => {
      const r = { ...(s.runs[runId] ?? { runId, events: [], stages: emptyStages(),
        approveSubStages: { propose: "pending", critique: "pending", finalize: "pending" },
        state: { run_id: runId }, done: false }) };
      r.events = [...r.events, e];
      if (e.kind === "node.start") r.stages[e.node].status = "running";
      if (e.kind === "node.complete") {
        r.stages[e.node].status = "complete";
        r.stages[e.node].summary = e.output;
      }
      if (e.kind === "approve.propose.start") r.approveSubStages.propose = "running";
      if (e.kind === "approve.propose.complete") r.approveSubStages.propose = "complete";
      if (e.kind === "approve.critique.start") r.approveSubStages.critique = "running";
      if (e.kind === "approve.critique.complete") r.approveSubStages.critique = "complete";
      if (e.kind === "approve.finalize.start") r.approveSubStages.finalize = "running";
      if (e.kind === "approve.finalize.complete") r.approveSubStages.finalize = "complete";
      if (e.kind === "approve.decision") r.state.decision = e.output as Decision;
      if (e.kind === "run.complete") {
        r.state = e.final_state;
        r.done = true;
      }
      if (e.kind === "run.error") r.done = true;
      return { runs: { ...s.runs, [runId]: r } };
    });
  },
  startBatch: (runIds) =>
    set({ currentBatch: { runIds, startedAt: Date.now() } }),
  clearBatchIfComplete: (doneRunIds) => {
    const batch = get().currentBatch;
    if (batch === null) return;
    const allDone = batch.runIds.every((rid) => doneRunIds.has(rid));
    if (allDone) set({ currentBatch: null });
  },
}));
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npx tsc --noEmit
```
Expected: zero errors. (Existing call sites that use `selectRun`, `appendEvent`, `initializeRun` still work — we only added fields.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/store/runStore.ts
git commit -m "feat(store): add currentBatch state and setActiveRunId action"
```

---

## Phase 3 — Routing & app shell

### Task 8: Wire wouter routes in App.tsx

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Rewrite App.tsx to use wouter and URL/store sync**

Replace `frontend/src/App.tsx` with:

```tsx
import { useEffect } from "react";
import { Route, Switch, useRoute } from "wouter";
import { AppShell } from "./components/layout/AppShell.tsx";
import { BatchPage } from "./pages/BatchPage.tsx";
import { CaseFilePage } from "./pages/CaseFilePage.tsx";
import { useRunStore } from "./store/runStore.ts";

function RunRouteSync() {
  const [match, params] = useRoute<{ id: string }>("/runs/:id");
  const setActiveRunId = useRunStore((s) => s.setActiveRunId);
  useEffect(() => {
    setActiveRunId(match && params ? params.id : null);
  }, [match, params?.id, setActiveRunId]);
  return null;
}

export default function App() {
  return (
    <AppShell>
      <RunRouteSync />
      <Switch>
        <Route path="/runs/:id" component={CaseFilePage} />
        <Route component={BatchPage} />
      </Switch>
    </AppShell>
  );
}
```

- [ ] **Step 2: Create placeholder pages and shell so the build still works**

We'll fill these in later tasks. For now, create minimal stubs.

Create `frontend/src/components/layout/AppShell.tsx`:

```tsx
import type { ReactNode } from "react";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <div className="max-w-7xl mx-auto p-6">{children}</div>
    </div>
  );
}
```

Create `frontend/src/pages/BatchPage.tsx`:

```tsx
export function BatchPage() {
  return <div>Batch (stub)</div>;
}
```

Create `frontend/src/pages/CaseFilePage.tsx`:

```tsx
export function CaseFilePage() {
  return <div>Case file (stub)</div>;
}
```

- [ ] **Step 3: Delete the old Dashboard.tsx**

```bash
rm frontend/src/pages/Dashboard.tsx
```

- [ ] **Step 4: Type-check + build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```
Expected: both succeed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/layout/AppShell.tsx frontend/src/pages/BatchPage.tsx frontend/src/pages/CaseFilePage.tsx
git rm frontend/src/pages/Dashboard.tsx
git commit -m "feat(routing): wouter routes for / and /runs/:id with URL/store sync"
```

---

### Task 9: TopBar component

**Files:**
- Create: `frontend/src/components/layout/TopBar.tsx`
- Modify: `frontend/src/components/layout/AppShell.tsx`

- [ ] **Step 1: Build the TopBar**

Create `frontend/src/components/layout/TopBar.tsx`:

```tsx
import { useRef } from "react";
import { useLocation } from "wouter";
import { createSampleRun, runBatch, uploadInvoice } from "../../api/client.ts";
import { useRunStore } from "../../store/runStore.ts";
import { Play, Upload } from "../common/Icons.tsx";

export function TopBar() {
  const [, setLocation] = useLocation();
  const startBatch = useRunStore((s) => s.startBatch);
  const fileRef = useRef<HTMLInputElement>(null);

  const onUploadClick = () => fileRef.current?.click();

  const onFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    const { run_id } = await uploadInvoice(files[0]);
    setLocation(`/runs/${run_id}`);
  };

  const onRunAll = async () => {
    const { run_ids } = await runBatch();
    startBatch(run_ids);
    setLocation("/");
  };

  return (
    <header className="flex items-center justify-between h-12 mb-6">
      <h1 className="text-base font-semibold tracking-tight">Acme AP</h1>
      <div className="flex items-center gap-2">
        <input
          ref={fileRef}
          type="file"
          hidden
          onChange={(e) => onFiles(e.target.files)}
        />
        <button
          onClick={onUploadClick}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded border border-slate-200 bg-white hover:bg-slate-50"
        >
          <Upload size={16} /> Upload invoice
        </button>
        <button
          onClick={onRunAll}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-700"
        >
          <Play size={16} /> Run all 16
        </button>
      </div>
    </header>
  );
}
```

- [ ] **Step 2: Mount TopBar inside AppShell**

Replace `frontend/src/components/layout/AppShell.tsx`:

```tsx
import type { ReactNode } from "react";
import { TopBar } from "./TopBar.tsx";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <div className="max-w-7xl mx-auto p-6">
        <TopBar />
        {children}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Type-check + build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```
Expected: both succeed.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/layout/TopBar.tsx frontend/src/components/layout/AppShell.tsx
git commit -m "feat(layout): TopBar with upload + run all 16 actions"
```

---

## Phase 4 — Metrics band & left rail

### Task 10: MetricsBand component

**Files:**
- Create: `frontend/src/components/layout/MetricsBand.tsx`
- Modify: `frontend/src/components/layout/AppShell.tsx`

- [ ] **Step 1: Build the MetricsBand**

Create `frontend/src/components/layout/MetricsBand.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { getMetrics, type Metrics } from "../../api/client.ts";

const fmtUSD = (n: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(n);

export function MetricsBand() {
  const { data: m, error } = useQuery<Metrics>({
    queryKey: ["metrics"],
    queryFn: getMetrics,
    refetchInterval: 1500,
  });

  if (error) {
    return (
      <div className="bg-white border border-slate-200 rounded-lg p-6 mb-6">
        <p className="text-sm text-rose-600">Metrics unavailable — retrying</p>
      </div>
    );
  }
  if (!m) {
    return (
      <div className="bg-white border border-slate-200 rounded-lg p-6 mb-6 h-[112px]" />
    );
  }

  const approvedPct =
    m.total_runs === 0 ? 0 : Math.round((m.approved_count / m.total_runs) * 100);
  const avgSec = m.avg_run_seconds === null ? "—" : `${m.avg_run_seconds.toFixed(1)}s`;

  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-6 bg-white border border-slate-200 rounded-lg p-6 mb-6">
      <Stat label="Runs processed" value={String(m.total_runs)} mono />
      <Stat label="Auto-approved" value={`${m.approved_count}`} suffix={`(${approvedPct}%)`} mono />
      <Stat label="Avg processing time" value={avgSec} sub="vs. ~5 days manual" mono />
      <Stat label="Total approved" value={fmtUSD(m.total_dollars_approved)} mono />
      <Stat
        label="Simulated savings"
        value={fmtUSD(m.simulated_dollars_saved)}
        sub={`@ ${fmtUSD(m.manual_cost_per_invoice_usd)}/invoice manual cost`}
        mono
      />
    </div>
  );
}

function Stat({
  label,
  value,
  sub,
  suffix,
  mono,
}: {
  label: string;
  value: string;
  sub?: string;
  suffix?: string;
  mono?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </span>
      <span className="text-3xl font-semibold text-slate-900 leading-none">
        <span className={mono ? "font-mono" : ""}>{value}</span>
        {suffix && <span className="ml-1.5 text-2xl text-slate-500">{suffix}</span>}
      </span>
      {sub && <span className="text-xs text-slate-500">{sub}</span>}
    </div>
  );
}
```

- [ ] **Step 2: Mount MetricsBand inside AppShell**

Update `frontend/src/components/layout/AppShell.tsx`:

```tsx
import type { ReactNode } from "react";
import { MetricsBand } from "./MetricsBand.tsx";
import { TopBar } from "./TopBar.tsx";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <div className="max-w-7xl mx-auto p-6">
        <TopBar />
        <MetricsBand />
        {children}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Verify QueryClient is mounted**

Check `frontend/src/main.tsx`. If `@tanstack/react-query`'s `QueryClientProvider` isn't wrapping `<App />` yet, add it. Read the file:

```bash
cat frontend/src/main.tsx
```

If `QueryClientProvider` is missing, replace `main.tsx` with:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App.tsx";
import "./index.css";

const queryClient = new QueryClient();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
);
```

- [ ] **Step 4: Type-check + build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```
Expected: both succeed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/layout/MetricsBand.tsx frontend/src/components/layout/AppShell.tsx frontend/src/main.tsx
git commit -m "feat(layout): permanent MetricsBand on 1.5s poll"
```

---

### Task 11: LeftRail — session summary card

**Files:**
- Create: `frontend/src/components/layout/LeftRail.tsx`
- Modify: `frontend/src/pages/BatchPage.tsx`
- Modify: `frontend/src/pages/CaseFilePage.tsx`

- [ ] **Step 1: Build LeftRail with session summary card only (runs list comes in next task)**

Create `frontend/src/components/layout/LeftRail.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { Link } from "wouter";
import { getMetrics, listRuns, type Metrics } from "../../api/client.ts";
import { useRunStore } from "../../store/runStore.ts";

const fmtCompactUSD = (n: number) => {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(1)}k`;
  return `$${Math.round(n)}`;
};

export function LeftRail() {
  const { data: m } = useQuery<Metrics>({
    queryKey: ["metrics"],
    queryFn: getMetrics,
    refetchInterval: 1500,
  });
  const { data: runs } = useQuery({
    queryKey: ["runs"],
    queryFn: listRuns,
    refetchInterval: 1500,
  });
  const batch = useRunStore((s) => s.currentBatch);

  const doneCount = (() => {
    if (!batch || !runs) return 0;
    const byId = new Map(runs.map((r) => [r.run_id, r.outcome] as const));
    return batch.runIds.filter((rid) => {
      const o = byId.get(rid);
      return o && o !== "running";
    }).length;
  })();

  return (
    <aside className="w-[280px] shrink-0">
      <div className="bg-white border border-slate-200 rounded-lg p-4 mb-3">
        <h2 className="text-xs font-medium uppercase tracking-wide text-slate-500 mb-2">
          Session
        </h2>
        {m && (
          <p className="text-sm text-slate-700">
            {m.total_runs} runs · {m.approved_count} approved ·{" "}
            {fmtCompactUSD(m.total_dollars_approved)} approved
          </p>
        )}
        <Link
          href="/"
          className="block mt-3 text-sm text-indigo-600 hover:text-indigo-700"
        >
          ▶ Batch overview
        </Link>
        {batch && (
          <div className="mt-3">
            <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-indigo-600 transition-all duration-300"
                style={{ width: `${(doneCount / batch.runIds.length) * 100}%` }}
              />
            </div>
            <p className="text-xs text-slate-500 mt-1">
              {doneCount} / {batch.runIds.length} done
            </p>
          </div>
        )}
      </div>
      {/* Runs list will be added in the next task */}
    </aside>
  );
}
```

- [ ] **Step 2: Wire LeftRail into BatchPage and CaseFilePage**

Update `frontend/src/pages/BatchPage.tsx`:

```tsx
import { LeftRail } from "../components/layout/LeftRail.tsx";

export function BatchPage() {
  return (
    <div className="flex gap-6">
      <LeftRail />
      <main className="flex-1 min-w-0">
        <div className="bg-white border border-slate-200 rounded-lg p-6">
          Batch overview (stub)
        </div>
      </main>
    </div>
  );
}
```

Update `frontend/src/pages/CaseFilePage.tsx`:

```tsx
import { LeftRail } from "../components/layout/LeftRail.tsx";

export function CaseFilePage() {
  return (
    <div className="flex gap-6">
      <LeftRail />
      <main className="flex-1 min-w-0">
        <div className="bg-white border border-slate-200 rounded-lg p-6">
          Case file (stub)
        </div>
      </main>
    </div>
  );
}
```

- [ ] **Step 3: Type-check + build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```
Expected: both succeed.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/layout/LeftRail.tsx frontend/src/pages/BatchPage.tsx frontend/src/pages/CaseFilePage.tsx
git commit -m "feat(layout): LeftRail with session summary card and batch progress"
```

---

### Task 12: LeftRail — runs list with retry indentation

**Files:**
- Modify: `frontend/src/components/layout/LeftRail.tsx`

- [ ] **Step 1: Build a small util to group runs into parent/child**

Replace `frontend/src/components/layout/LeftRail.tsx` with:

```tsx
import { useQuery } from "@tanstack/react-query";
import { Link, useRoute } from "wouter";
import { getMetrics, listRuns, type Metrics } from "../../api/client.ts";
import { useRunStore } from "../../store/runStore.ts";
import { AlertTriangle, CheckCircle2, Circle, Loader2, XCircle } from "../common/Icons.tsx";

type RunSummary = Awaited<ReturnType<typeof listRuns>>[number];

const fmtCompactUSD = (n: number) => {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(1)}k`;
  return `$${Math.round(n)}`;
};

const fmtTotal = (n: number | null) => (n === null ? "—" : fmtCompactUSD(n));

function groupRunsByParent(runs: RunSummary[]): RunSummary[][] {
  // Returns an array of [parent, ...children] groups, in original order.
  const byId = new Map(runs.map((r) => [r.run_id, r] as const));
  const placed = new Set<string>();
  const groups: RunSummary[][] = [];
  for (const r of runs) {
    if (r.parent_run_id && byId.has(r.parent_run_id)) continue;
    const children = runs.filter((c) => c.parent_run_id === r.run_id);
    groups.push([r, ...children]);
    placed.add(r.run_id);
    for (const c of children) placed.add(c.run_id);
  }
  // Append any orphans (children whose parent isn't in the list) at the end.
  for (const r of runs) if (!placed.has(r.run_id)) groups.push([r]);
  return groups;
}

function OutcomeIcon({ outcome }: { outcome: string }) {
  const size = 14;
  if (outcome === "approved") return <CheckCircle2 size={size} className="text-emerald-600" />;
  if (outcome === "rejected") return <XCircle size={size} className="text-rose-600" />;
  if (outcome === "needs_review") return <AlertTriangle size={size} className="text-amber-500" />;
  if (outcome === "running") return <Loader2 size={size} className="text-indigo-600 animate-spin" />;
  return <Circle size={size} className="text-slate-300" />;
}

function RunRow({ run, indent, active }: { run: RunSummary; indent: boolean; active: boolean }) {
  const label = run.invoice_number ?? run.run_id.slice(0, 8);
  return (
    <Link
      href={`/runs/${run.run_id}`}
      className={`flex items-center gap-2 text-sm py-1.5 px-2 rounded relative
        ${active ? "bg-slate-100" : "hover:bg-slate-50"}
        ${indent ? "pl-6" : ""}`}
    >
      {active && (
        <span className="absolute left-0 top-1.5 bottom-1.5 w-[3px] bg-indigo-600 rounded-r" />
      )}
      <OutcomeIcon outcome={run.outcome} />
      <span className="truncate flex-1">
        {indent && <span className="text-slate-400 mr-1">↳</span>}
        {indent ? "retry" : label}
      </span>
      <span className="font-mono text-xs text-slate-500">{fmtTotal(run.total)}</span>
    </Link>
  );
}

export function LeftRail() {
  const { data: m } = useQuery<Metrics>({
    queryKey: ["metrics"],
    queryFn: getMetrics,
    refetchInterval: 1500,
  });
  const { data: runs } = useQuery({
    queryKey: ["runs"],
    queryFn: listRuns,
    refetchInterval: 1500,
  });
  const batch = useRunStore((s) => s.currentBatch);
  const [, params] = useRoute<{ id: string }>("/runs/:id");
  const activeId = params?.id ?? null;

  const doneCount = (() => {
    if (!batch || !runs) return 0;
    const byId = new Map(runs.map((r) => [r.run_id, r.outcome] as const));
    return batch.runIds.filter((rid) => {
      const o = byId.get(rid);
      return o && o !== "running";
    }).length;
  })();

  const groups = runs ? groupRunsByParent(runs) : [];

  return (
    <aside className="w-[280px] shrink-0">
      <div className="bg-white border border-slate-200 rounded-lg p-4 mb-3">
        <h2 className="text-xs font-medium uppercase tracking-wide text-slate-500 mb-2">
          Session
        </h2>
        {m && (
          <p className="text-sm text-slate-700">
            {m.total_runs} runs · {m.approved_count} approved ·{" "}
            {fmtCompactUSD(m.total_dollars_approved)} approved
          </p>
        )}
        <Link href="/" className="block mt-3 text-sm text-indigo-600 hover:text-indigo-700">
          ▶ Batch overview
        </Link>
        {batch && (
          <div className="mt-3">
            <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-indigo-600 transition-all duration-300"
                style={{ width: `${(doneCount / batch.runIds.length) * 100}%` }}
              />
            </div>
            <p className="text-xs text-slate-500 mt-1">
              {doneCount} / {batch.runIds.length} done
            </p>
          </div>
        )}
      </div>
      <div className="bg-white border border-slate-200 rounded-lg p-2">
        <h3 className="text-xs font-medium uppercase tracking-wide text-slate-500 px-2 py-1">
          Runs
        </h3>
        <div className="max-h-[60vh] overflow-y-auto">
          {groups.length === 0 ? (
            <p className="text-sm text-slate-400 px-2 py-3">No runs yet.</p>
          ) : (
            groups.flatMap(([parent, ...children]) => [
              <RunRow
                key={parent.run_id}
                run={parent}
                indent={false}
                active={parent.run_id === activeId}
              />,
              ...children.map((c) => (
                <RunRow key={c.run_id} run={c} indent={true} active={c.run_id === activeId} />
              )),
            ])
          )}
        </div>
      </div>
    </aside>
  );
}
```

- [ ] **Step 2: Type-check + build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```
Expected: both succeed.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/layout/LeftRail.tsx
git commit -m "feat(rail): runs list with retry indentation and active-row accent"
```

---

## Phase 5 — Batch Overview

### Task 13: EmptyState intro card with sample buttons

**Files:**
- Create: `frontend/src/components/batch/EmptyState.tsx`

- [ ] **Step 1: Build the EmptyState**

Create `frontend/src/components/batch/EmptyState.tsx`:

```tsx
import { useRef, useState } from "react";
import { useLocation } from "wouter";
import { createSampleRun, uploadInvoice } from "../../api/client.ts";
import { Upload } from "../common/Icons.tsx";

const SAMPLES: Array<{ filename: string; label: string; subtitle: string }> = [
  { filename: "INV-1001.txt", label: "INV-1001", subtitle: "Clean approval" },
  { filename: "INV-1003.json", label: "INV-1003", subtitle: "Fraud catch" },
  { filename: "INV-1012.pdf", label: "INV-1012", subtitle: "OCR resilience" },
];

export function EmptyState() {
  const [, setLocation] = useLocation();
  const [pending, setPending] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const onSample = async (filename: string) => {
    setPending(filename);
    try {
      const { run_id } = await createSampleRun(filename);
      setLocation(`/runs/${run_id}`);
    } finally {
      setPending(null);
    }
  };

  const onFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    const { run_id } = await uploadInvoice(files[0]);
    setLocation(`/runs/${run_id}`);
  };

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-12 text-center">
      <h2 className="text-xl font-semibold mb-2">Process your first invoice</h2>
      <p className="text-sm text-slate-500 mb-8">
        Drop a file or try a sample to see the agents work.
      </p>
      <div
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          onFiles(e.dataTransfer.files);
        }}
        onClick={() => fileRef.current?.click()}
        className="border-2 border-dashed border-slate-300 rounded-lg py-12 mb-8 cursor-pointer hover:border-indigo-400 hover:bg-slate-50"
      >
        <input
          ref={fileRef}
          type="file"
          hidden
          onChange={(e) => onFiles(e.target.files)}
        />
        <Upload size={24} className="mx-auto text-slate-400 mb-2" />
        <p className="text-sm text-slate-500">Drag an invoice here or click to upload</p>
      </div>
      <p className="text-xs uppercase tracking-wide text-slate-500 mb-3">
        Or try a sample
      </p>
      <div className="grid grid-cols-3 gap-3">
        {SAMPLES.map((s) => (
          <button
            key={s.filename}
            onClick={() => onSample(s.filename)}
            disabled={pending !== null}
            className="border border-slate-200 rounded-lg p-4 text-left hover:border-indigo-400 hover:bg-slate-50 disabled:opacity-50"
          >
            <div className="font-mono text-sm font-semibold">{s.label}</div>
            <div className="text-xs text-slate-500 mt-1">{s.subtitle}</div>
            {pending === s.filename && (
              <div className="text-xs text-indigo-600 mt-2">Starting…</div>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Type-check + build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```
Expected: both succeed.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/batch/EmptyState.tsx
git commit -m "feat(batch): EmptyState intro card with three sample-invoice buttons"
```

---

### Task 14: BatchTable with filter & sort

**Files:**
- Create: `frontend/src/components/batch/BatchTable.tsx`
- Create: `frontend/src/components/common/OutcomeChip.tsx`

- [ ] **Step 1: Build the OutcomeChip**

Create `frontend/src/components/common/OutcomeChip.tsx`:

```tsx
import { AlertTriangle, CheckCircle2, Circle, Loader2, XCircle } from "./Icons.tsx";

const STYLES: Record<string, { cls: string; label: string }> = {
  approved: { cls: "bg-emerald-50 text-emerald-700 border-emerald-200", label: "Approved" },
  rejected: { cls: "bg-rose-50 text-rose-700 border-rose-200", label: "Rejected" },
  needs_review: { cls: "bg-amber-50 text-amber-700 border-amber-200", label: "Needs review" },
  unprocessable: { cls: "bg-slate-100 text-slate-600 border-slate-200", label: "Unprocessable" },
  running: { cls: "bg-indigo-50 text-indigo-700 border-indigo-200", label: "Running" },
};

function Icon({ outcome, size }: { outcome: string; size: number }) {
  if (outcome === "approved") return <CheckCircle2 size={size} />;
  if (outcome === "rejected") return <XCircle size={size} />;
  if (outcome === "needs_review") return <AlertTriangle size={size} />;
  if (outcome === "running") return <Loader2 size={size} className="animate-spin" />;
  return <Circle size={size} />;
}

export function OutcomeChip({ outcome, large = false }: { outcome: string; large?: boolean }) {
  const s = STYLES[outcome] ?? { cls: "bg-slate-100 text-slate-600 border-slate-200", label: outcome };
  const padding = large ? "px-3 py-1.5 text-sm" : "px-2 py-0.5 text-xs";
  const iconSize = large ? 16 : 12;
  return (
    <span className={`inline-flex items-center gap-1.5 rounded border ${s.cls} ${padding}`}>
      <Icon outcome={outcome} size={iconSize} />
      {s.label}
    </span>
  );
}
```

- [ ] **Step 2: Build BatchTable**

Create `frontend/src/components/batch/BatchTable.tsx`:

```tsx
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation } from "wouter";
import { listRuns } from "../../api/client.ts";
import { Flag } from "../common/Icons.tsx";
import { OutcomeChip } from "../common/OutcomeChip.tsx";

type RunSummary = Awaited<ReturnType<typeof listRuns>>[number];

type Filter = "all" | "approved" | "rejected" | "needs_review" | "unprocessable";
type Sort = "time" | "vendor" | "amount" | "outcome";

const fmtUSD = (n: number | null) =>
  n === null
    ? "—"
    : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);

export function BatchTable() {
  const [, setLocation] = useLocation();
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<Sort>("time");

  const { data: runs } = useQuery({
    queryKey: ["runs"],
    queryFn: listRuns,
    refetchInterval: 1500,
  });

  if (!runs) return null;

  const filtered = runs.filter((r) => filter === "all" || r.outcome === filter);
  const sorted = [...filtered].sort((a, b) => {
    if (sort === "vendor") return (a.vendor ?? "").localeCompare(b.vendor ?? "");
    if (sort === "amount") return (b.total ?? 0) - (a.total ?? 0);
    if (sort === "outcome") return a.outcome.localeCompare(b.outcome);
    return 0; // time = insertion order from the backend
  });

  return (
    <div className="bg-white border border-slate-200 rounded-lg">
      <div className="flex items-center gap-3 px-4 py-3 border-b border-slate-100">
        <label className="text-xs uppercase tracking-wide text-slate-500">Filter</label>
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value as Filter)}
          className="text-sm border border-slate-200 rounded px-2 py-1 bg-white"
        >
          <option value="all">All</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
          <option value="needs_review">Needs review</option>
          <option value="unprocessable">Unprocessable</option>
        </select>
        <label className="text-xs uppercase tracking-wide text-slate-500 ml-4">Sort</label>
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as Sort)}
          className="text-sm border border-slate-200 rounded px-2 py-1 bg-white"
        >
          <option value="time">Time</option>
          <option value="vendor">Vendor</option>
          <option value="amount">Amount</option>
          <option value="outcome">Outcome</option>
        </select>
      </div>
      <table className="w-full">
        <thead>
          <tr className="text-left text-xs uppercase tracking-wide text-slate-500 border-b border-slate-100">
            <th className="px-4 py-2 font-medium">Invoice #</th>
            <th className="px-4 py-2 font-medium">Vendor</th>
            <th className="px-4 py-2 font-medium">Total</th>
            <th className="px-4 py-2 font-medium">Outcome</th>
            <th className="px-4 py-2 font-medium">Signals</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <BatchRow key={r.run_id} run={r} onClick={() => setLocation(`/runs/${r.run_id}`)} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BatchRow({ run, onClick }: { run: RunSummary; onClick: () => void }) {
  return (
    <tr
      onClick={onClick}
      className="cursor-pointer hover:bg-slate-50 border-b border-slate-100 last:border-0"
    >
      <td className="px-4 py-3 font-mono text-sm">
        {run.invoice_number ?? run.run_id.slice(0, 8)}
      </td>
      <td className="px-4 py-3 text-sm text-slate-700">{run.vendor ?? "—"}</td>
      <td className="px-4 py-3 font-mono text-sm">{fmtUSD(run.total)}</td>
      <td className="px-4 py-3">
        <OutcomeChip outcome={run.outcome} />
      </td>
      <td className="px-4 py-3">
        {/* Signal flag only when suspicion_signals is non-empty — but listRuns
            doesn't include those yet, so for now we omit. The Case File shows them. */}
      </td>
    </tr>
  );
}
```

- [ ] **Step 3: Type-check + build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```
Expected: both succeed.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/common/OutcomeChip.tsx frontend/src/components/batch/BatchTable.tsx
git commit -m "feat(batch): BatchTable with filter/sort and OutcomeChip primitive"
```

---

### Task 15: Compose BatchPage with header, progress, table, empty state

**Files:**
- Create: `frontend/src/components/batch/BatchHeader.tsx`
- Modify: `frontend/src/pages/BatchPage.tsx`

- [ ] **Step 1: Build BatchHeader**

Create `frontend/src/components/batch/BatchHeader.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { listRuns } from "../../api/client.ts";
import { useRunStore } from "../../store/runStore.ts";

export function BatchHeader() {
  const batch = useRunStore((s) => s.currentBatch);
  const { data: runs } = useQuery({
    queryKey: ["runs"],
    queryFn: listRuns,
    refetchInterval: 1500,
  });

  if (!batch || !runs) {
    return (
      <header className="mb-6">
        <h1 className="text-2xl font-semibold">Batch overview</h1>
      </header>
    );
  }
  const byId = new Map(runs.map((r) => [r.run_id, r.outcome] as const));
  const done = batch.runIds.filter((rid) => {
    const o = byId.get(rid);
    return o && o !== "running";
  }).length;
  const pct = (done / batch.runIds.length) * 100;

  return (
    <header className="mb-6">
      <h1 className="text-2xl font-semibold">Batch overview</h1>
      <p className="text-sm text-slate-500 mt-1">
        {batch.runIds.length} invoices · processing in 4-way parallel
      </p>
      <div className="mt-3 h-1.5 bg-slate-100 rounded-full overflow-hidden">
        <div
          className="h-full bg-indigo-600 transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="text-xs text-slate-500 mt-1">
        {done} / {batch.runIds.length} done
      </p>
    </header>
  );
}
```

- [ ] **Step 2: Update BatchPage to assemble the view**

Replace `frontend/src/pages/BatchPage.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { listRuns } from "../api/client.ts";
import { BatchHeader } from "../components/batch/BatchHeader.tsx";
import { BatchTable } from "../components/batch/BatchTable.tsx";
import { EmptyState } from "../components/batch/EmptyState.tsx";
import { LeftRail } from "../components/layout/LeftRail.tsx";

export function BatchPage() {
  const { data: runs } = useQuery({ queryKey: ["runs"], queryFn: listRuns, refetchInterval: 1500 });
  const isEmpty = runs !== undefined && runs.length === 0;

  return (
    <div className="flex gap-6">
      <LeftRail />
      <main className="flex-1 min-w-0">
        {isEmpty ? (
          <EmptyState />
        ) : (
          <>
            <BatchHeader />
            <BatchTable />
          </>
        )}
      </main>
    </div>
  );
}
```

- [ ] **Step 3: Wire `currentBatch` clearance**

The BatchHeader uses `currentBatch`. Once all rows in `currentBatch.runIds` are no longer `running`, we want the batch state to clear (so the progress bar disappears). Add this side effect to BatchHeader. Update `frontend/src/components/batch/BatchHeader.tsx` — replace the file with:

```tsx
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { listRuns } from "../../api/client.ts";
import { useRunStore } from "../../store/runStore.ts";

export function BatchHeader() {
  const batch = useRunStore((s) => s.currentBatch);
  const clearBatchIfComplete = useRunStore((s) => s.clearBatchIfComplete);
  const { data: runs } = useQuery({
    queryKey: ["runs"],
    queryFn: listRuns,
    refetchInterval: 1500,
  });

  useEffect(() => {
    if (!batch || !runs) return;
    const doneIds = new Set(
      runs.filter((r) => r.outcome !== "running").map((r) => r.run_id),
    );
    clearBatchIfComplete(doneIds);
  }, [batch, runs, clearBatchIfComplete]);

  if (!batch || !runs) {
    return (
      <header className="mb-6">
        <h1 className="text-2xl font-semibold">Batch overview</h1>
      </header>
    );
  }
  const byId = new Map(runs.map((r) => [r.run_id, r.outcome] as const));
  const done = batch.runIds.filter((rid) => {
    const o = byId.get(rid);
    return o && o !== "running";
  }).length;
  const pct = (done / batch.runIds.length) * 100;

  return (
    <header className="mb-6">
      <h1 className="text-2xl font-semibold">Batch overview</h1>
      <p className="text-sm text-slate-500 mt-1">
        {batch.runIds.length} invoices · processing in 4-way parallel
      </p>
      <div className="mt-3 h-1.5 bg-slate-100 rounded-full overflow-hidden">
        <div
          className="h-full bg-indigo-600 transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="text-xs text-slate-500 mt-1">
        {done} / {batch.runIds.length} done
      </p>
    </header>
  );
}
```

- [ ] **Step 4: Type-check + build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```
Expected: both succeed.

- [ ] **Step 5: Manual verification (Phase 5 boundary)**

Start the backend + frontend dev servers:

```bash
cd backend && make dev &
cd frontend && npm run dev
```

Open http://localhost:5173 in a browser. Verify against spec §13 acceptance criteria #1, #3, #4:

- App loads with the empty-state intro card (no runs yet) and the metrics band shows zeros.
- Click "Run all 16" in TopBar. The batch starts; the progress bar in BatchHeader and the LeftRail summary card both advance.
- The BatchTable fills in row by row; clicking the filter/sort dropdowns reorders rows.

Kill both servers (Ctrl-C).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/batch/BatchHeader.tsx frontend/src/pages/BatchPage.tsx
git commit -m "feat(batch): assemble BatchPage with header, progress, table, empty state"
```

---

## Phase 6 — Case File scaffolding

### Task 16: Breadcrumb (context-aware)

**Files:**
- Create: `frontend/src/components/casefile/Breadcrumb.tsx`

- [ ] **Step 1: Build the Breadcrumb**

Create `frontend/src/components/casefile/Breadcrumb.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { Link } from "wouter";
import { listRuns } from "../../api/client.ts";
import { useRunStore } from "../../store/runStore.ts";
import { ArrowLeft } from "../common/Icons.tsx";

export function Breadcrumb({ runId }: { runId: string }) {
  const batch = useRunStore((s) => s.currentBatch);
  const { data: runs } = useQuery({ queryKey: ["runs"], queryFn: listRuns, refetchInterval: 1500 });

  const thisRun = runs?.find((r) => r.run_id === runId);
  const isRetryChild = thisRun?.parent_run_id !== null && thisRun?.parent_run_id !== undefined;
  const parent = isRetryChild
    ? runs?.find((r) => r.run_id === thisRun!.parent_run_id)
    : null;
  const supersededBy = runs?.find((r) => r.parent_run_id === runId);

  if (isRetryChild && parent) {
    return (
      <div className="mb-4 text-sm text-slate-600">
        <Link href={`/runs/${parent.run_id}`} className="inline-flex items-center gap-1 text-slate-500 hover:text-slate-700">
          ↳ Retry of {parent.invoice_number ?? parent.run_id.slice(0, 8)}
        </Link>
      </div>
    );
  }

  if (batch && runs) {
    const done = batch.runIds.filter((rid) => {
      const o = runs.find((r) => r.run_id === rid)?.outcome;
      return o && o !== "running";
    }).length;
    return (
      <div className="mb-4">
        <Link href="/" className="inline-flex items-center gap-1.5 text-sm text-slate-600 hover:text-slate-900">
          <ArrowLeft size={16} /> Back to batch overview · {done}/{batch.runIds.length} done
        </Link>
        {supersededBy && (
          <Link
            href={`/runs/${supersededBy.run_id}`}
            className="block mt-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-1.5 hover:bg-amber-100"
          >
            Superseded by retry · run {supersededBy.run_id.slice(0, 8)}
          </Link>
        )}
      </div>
    );
  }

  return (
    <div className="mb-4">
      <Link href="/" className="inline-flex items-center gap-1.5 text-sm text-slate-600 hover:text-slate-900">
        <ArrowLeft size={16} /> Back to overview
      </Link>
      {supersededBy && (
        <Link
          href={`/runs/${supersededBy.run_id}`}
          className="block mt-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-1.5 hover:bg-amber-100"
        >
          Superseded by retry · run {supersededBy.run_id.slice(0, 8)}
        </Link>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Type-check + build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```
Expected: both succeed.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/casefile/Breadcrumb.tsx
git commit -m "feat(casefile): context-aware Breadcrumb with retry + supersession"
```

---

### Task 17: HeroCard

**Files:**
- Create: `frontend/src/components/casefile/HeroCard.tsx`

- [ ] **Step 1: Build the HeroCard**

Create `frontend/src/components/casefile/HeroCard.tsx`:

```tsx
import type { InvoiceState } from "../../types/state.ts";
import { OutcomeChip } from "../common/OutcomeChip.tsx";

const fmtUSD = (n: number | null | undefined) =>
  n === null || n === undefined
    ? "—"
    : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);

export function HeroCard({ state }: { state: Partial<InvoiceState> }) {
  const inv = state.invoice;
  const decision = state.decision;
  const outcome = decision?.outcome ?? (state.error ? "unprocessable" : "running");

  return (
    <div className="bg-white border border-slate-200 rounded-lg shadow-sm p-6 mb-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Invoice</div>
          <h1 className="text-xl font-semibold">
            {inv?.invoice_number ?? "—"}
            {inv?.vendor && (
              <span className="text-slate-500 font-normal"> · {inv.vendor}</span>
            )}
          </h1>
        </div>
        <OutcomeChip outcome={outcome} large />
      </div>
      <div className="mt-4 flex items-baseline gap-3">
        <span className="font-mono text-3xl font-semibold leading-none">
          {fmtUSD(inv?.total ?? null)}
        </span>
        <span className="text-xs text-slate-500">
          {inv?.date ? `dated ${inv.date}` : ""}
        </span>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Type-check + build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```
Expected: both succeed.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/casefile/HeroCard.tsx
git commit -m "feat(casefile): HeroCard with vendor, amount, outcome chip"
```

---

### Task 18: StageStrip (sticky)

**Files:**
- Create: `frontend/src/components/casefile/StageStrip.tsx`

- [ ] **Step 1: Build the StageStrip**

Create `frontend/src/components/casefile/StageStrip.tsx`:

```tsx
import { useRunStore } from "../../store/runStore.ts";

const STAGES = [
  { key: "ingest", label: "Ingest" },
  { key: "validate", label: "Validate" },
  { key: "approve", label: "Approve" },
  { key: "pay", label: "Pay / Log" },
] as const;

export function StageStrip({ runId }: { runId: string }) {
  const run = useRunStore((s) => s.runs[runId]);
  if (!run) return null;

  return (
    <div className="sticky top-0 z-10 bg-slate-50 -mx-6 px-6 py-3 mb-6 border-b border-slate-200">
      <div className="flex items-center gap-2">
        {STAGES.map((s, i) => {
          const status =
            s.key === "pay"
              ? run.stages.pay.status === "pending"
                ? run.stages.log.status
                : run.stages.pay.status
              : run.stages[s.key].status;
          return (
            <div key={s.key} className="flex items-center gap-2">
              <Pip status={status} />
              <span className="text-xs uppercase tracking-wide text-slate-500">
                {s.label}
              </span>
              {i < STAGES.length - 1 && (
                <span className="w-6 h-px bg-slate-200 mx-1" />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Pip({ status }: { status: string }) {
  if (status === "complete") {
    return <span className="w-2.5 h-2.5 rounded-full bg-emerald-600" />;
  }
  if (status === "running") {
    return <span className="w-2.5 h-2.5 rounded-full bg-indigo-600 animate-pulse" />;
  }
  if (status === "error") {
    return <span className="w-2.5 h-2.5 rounded-full bg-rose-600" />;
  }
  return <span className="w-2.5 h-2.5 rounded-full border border-slate-300" />;
}
```

- [ ] **Step 2: Type-check + build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```
Expected: both succeed.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/casefile/StageStrip.tsx
git commit -m "feat(casefile): sticky StageStrip with pulsing running pip"
```

---

### Task 19: CaseFilePage shell with hydration

**Files:**
- Modify: `frontend/src/pages/CaseFilePage.tsx`

- [ ] **Step 1: Wire hydration on cold load and SSE on running runs**

Replace `frontend/src/pages/CaseFilePage.tsx`:

```tsx
import { useEffect, useRef } from "react";
import { useRoute } from "wouter";
import { getRun } from "../api/client.ts";
import { subscribeToRun } from "../api/sse.ts";
import { Breadcrumb } from "../components/casefile/Breadcrumb.tsx";
import { HeroCard } from "../components/casefile/HeroCard.tsx";
import { StageStrip } from "../components/casefile/StageStrip.tsx";
import { LeftRail } from "../components/layout/LeftRail.tsx";
import { useRunStore } from "../store/runStore.ts";

export function CaseFilePage() {
  const [, params] = useRoute<{ id: string }>("/runs/:id");
  const runId = params?.id ?? null;
  const run = useRunStore((s) => (runId ? s.runs[runId] : null));
  const initializeRun = useRunStore((s) => s.initializeRun);
  const appendEvent = useRunStore((s) => s.appendEvent);
  const hydratedFor = useRef<string | null>(null);
  const sseFor = useRef<{ id: string; close: () => void } | null>(null);

  // Hydrate on cold load.
  useEffect(() => {
    if (!runId) return;
    if (run) return;
    if (hydratedFor.current === runId) return;
    hydratedFor.current = runId;
    initializeRun(runId);
    getRun(runId).then((state) => {
      // Replace the store's state for this run with the server's view.
      useRunStore.setState((s) => {
        const existing = s.runs[runId];
        if (!existing) return s;
        return {
          runs: { ...s.runs, [runId]: { ...existing, state, done: state.decision !== null || state.error !== null } },
        };
      });
    });
  }, [runId, run, initializeRun]);

  // Open SSE if run is in progress.
  useEffect(() => {
    if (!runId || !run) return;
    if (run.done) return;
    if (sseFor.current?.id === runId) return;
    sseFor.current?.close();
    const close = subscribeToRun(runId, (e) => appendEvent(runId, e));
    sseFor.current = { id: runId, close };
    return () => {
      sseFor.current?.close();
      sseFor.current = null;
    };
  }, [runId, run?.done, appendEvent]);

  if (!runId) return null;

  return (
    <div className="flex gap-6">
      <LeftRail />
      <main className="flex-1 min-w-0">
        <Breadcrumb runId={runId} />
        <HeroCard state={run?.state ?? {}} />
        <StageStrip runId={runId} />
        <div className="bg-white border border-slate-200 rounded-lg p-6">
          Case file body (stub — sections coming in Phase 7+)
        </div>
      </main>
    </div>
  );
}
```

- [ ] **Step 2: Type-check + build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```
Expected: both succeed.

- [ ] **Step 3: Manual verification (Phase 6 boundary)**

Start servers:

```bash
cd backend && make dev &
cd frontend && npm run dev
```

1. From the empty state, click an INV-1001 sample button. The Case File loads; the StageStrip pulses as ingest/validate/approve run; the HeroCard fills in vendor/amount/outcome.
2. Refresh the page on a `/runs/{id}` URL. The case file hydrates correctly (HeroCard shows the final state).
3. Click the breadcrumb "← Back to batch overview". The URL changes to `/` and you see the BatchTable.

Kill servers.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/CaseFilePage.tsx
git commit -m "feat(casefile): page shell with cold-load hydration + lazy SSE"
```

---

## Phase 7 — Source / Extraction

### Task 20: Source panel with inline suspicion annotations

**Files:**
- Create: `frontend/src/lib/sourceAnnotation.ts`
- Create: `frontend/src/components/casefile/SourcePanel.tsx`

- [ ] **Step 1: Build the annotation utility**

Create `frontend/src/lib/sourceAnnotation.ts`:

```ts
import type { SuspicionSignal } from "../types/state.ts";

export interface AnnotatedSegment {
  text: string;
  signal: SuspicionSignal | null;
}

export interface AnnotationResult {
  segments: AnnotatedSegment[];
  unplaced: SuspicionSignal[]; // signals whose text_match couldn't be found (or was null)
}

/**
 * Split source text into segments, marking any segments that match a
 * suspicion signal's text_match (case-insensitive, first occurrence).
 * Signals with null text_match or no match in the source are returned
 * in `unplaced` so the UI can render them as fallback chips.
 */
export function annotateSource(
  source: string,
  signals: SuspicionSignal[],
): AnnotationResult {
  if (signals.length === 0) return { segments: [{ text: source, signal: null }], unplaced: [] };

  type Hit = { start: number; end: number; signal: SuspicionSignal };
  const hits: Hit[] = [];
  const unplaced: SuspicionSignal[] = [];
  const lower = source.toLowerCase();
  const usedRanges: Array<[number, number]> = [];

  for (const sig of signals) {
    if (!sig.text_match) {
      unplaced.push(sig);
      continue;
    }
    const phrase = sig.text_match.toLowerCase();
    let idx = lower.indexOf(phrase);
    // Skip indexes that overlap an already-placed hit.
    while (idx !== -1) {
      const end = idx + phrase.length;
      const overlap = usedRanges.some(([s, e]) => idx! < e && end > s);
      if (!overlap) break;
      idx = lower.indexOf(phrase, end);
    }
    if (idx === -1) {
      unplaced.push(sig);
      continue;
    }
    const end = idx + phrase.length;
    hits.push({ start: idx, end, signal: sig });
    usedRanges.push([idx, end]);
  }

  hits.sort((a, b) => a.start - b.start);
  const segments: AnnotatedSegment[] = [];
  let cursor = 0;
  for (const h of hits) {
    if (h.start > cursor) {
      segments.push({ text: source.slice(cursor, h.start), signal: null });
    }
    segments.push({ text: source.slice(h.start, h.end), signal: h.signal });
    cursor = h.end;
  }
  if (cursor < source.length) {
    segments.push({ text: source.slice(cursor), signal: null });
  }
  return { segments, unplaced };
}
```

- [ ] **Step 2: Build the SourcePanel**

Create `frontend/src/components/casefile/SourcePanel.tsx`:

```tsx
import { useEffect, useState } from "react";
import { getSource } from "../../api/client.ts";
import { annotateSource } from "../../lib/sourceAnnotation.ts";
import type { SuspicionSignal } from "../../types/state.ts";
import { Flag } from "../common/Icons.tsx";

export function SourcePanel({
  runId,
  signals,
}: {
  runId: string;
  signals: SuspicionSignal[];
}) {
  const [source, setSource] = useState<string>("");
  useEffect(() => {
    getSource(runId)
      .then((s) => setSource(s.text))
      .catch(() => setSource(""));
  }, [runId]);

  const { segments, unplaced } = annotateSource(source, signals);

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-6">
      <h3 className="text-base font-semibold mb-3">Source</h3>
      {unplaced.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          {unplaced.map((s, i) => (
            <span
              key={i}
              className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-rose-50 text-rose-700 border border-rose-200"
              title={s.detail}
            >
              <Flag size={11} /> {s.kind} ({s.severity})
            </span>
          ))}
        </div>
      )}
      <pre className="font-mono text-xs whitespace-pre-wrap break-words max-h-[480px] overflow-auto text-slate-800">
        {segments.map((seg, i) =>
          seg.signal ? (
            <span
              key={i}
              title={`${seg.signal.kind} (${seg.signal.severity}) — ${seg.signal.detail}`}
              className="underline decoration-rose-400 decoration-1 underline-offset-2 hover:bg-rose-50"
            >
              {seg.text}
            </span>
          ) : (
            <span key={i}>{seg.text}</span>
          ),
        )}
      </pre>
    </div>
  );
}
```

- [ ] **Step 3: Type-check + build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```
Expected: both succeed.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/sourceAnnotation.ts frontend/src/components/casefile/SourcePanel.tsx
git commit -m "feat(casefile): SourcePanel with inline annotations and chip fallback"
```

---

### Task 21: Invoice validation rules utility

**Files:**
- Create: `frontend/src/lib/invoiceValidation.ts`

- [ ] **Step 1: Build the validation utility**

Create `frontend/src/lib/invoiceValidation.ts`:

```ts
import type { InvoiceData, LineItem } from "../types/state.ts";

export type FieldKey =
  | "vendor"
  | "invoice_number"
  | "date"
  | "due_date"
  | "total"
  | `items.${number}.item`
  | `items.${number}.quantity`
  | `items.${number}.unit_price`;

export interface ValidationResult {
  errors: Partial<Record<FieldKey, string>>;
  warnings: Partial<Record<FieldKey, string>>;
}

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export function validateDraft(draft: InvoiceData): ValidationResult {
  const errors: Partial<Record<FieldKey, string>> = {};
  const warnings: Partial<Record<FieldKey, string>> = {};

  if (!draft.vendor || draft.vendor.trim() === "") errors.vendor = "required";
  if (!draft.invoice_number || draft.invoice_number.trim() === "") errors.invoice_number = "required";

  if (draft.date && !DATE_RE.test(draft.date)) errors.date = "use YYYY-MM-DD";
  if (draft.due_date && !DATE_RE.test(draft.due_date)) errors.due_date = "use YYYY-MM-DD";

  if (draft.total === null || draft.total === undefined || isNaN(draft.total) || draft.total < 0) {
    errors.total = "must be ≥ 0";
  }

  draft.line_items.forEach((it, i) => {
    if (!it.item || it.item.trim() === "") errors[`items.${i}.item`] = "required";
    if (!Number.isInteger(it.quantity) || it.quantity < 1) {
      errors[`items.${i}.quantity`] = "must be a positive integer";
    }
    if (it.unit_price !== null && (isNaN(it.unit_price) || it.unit_price < 0)) {
      errors[`items.${i}.unit_price`] = "must be ≥ 0";
    }
  });

  // Soft warning: total mismatch with sum of line items (within 1¢).
  if (draft.total !== null && !errors.total) {
    const sum = draft.line_items.reduce(
      (acc, it) => acc + (it.unit_price ?? 0) * it.quantity,
      0,
    );
    if (Math.abs(sum - draft.total) > 0.01) {
      warnings.total = "doesn't match item total";
    }
  }

  return { errors, warnings };
}

export function hasErrors(result: ValidationResult): boolean {
  return Object.keys(result.errors).length > 0;
}

export function invoicesEqual(a: InvoiceData, b: InvoiceData): boolean {
  if (a.invoice_number !== b.invoice_number) return false;
  if (a.vendor !== b.vendor) return false;
  if (a.date !== b.date) return false;
  if (a.due_date !== b.due_date) return false;
  if (a.total !== b.total) return false;
  if (a.line_items.length !== b.line_items.length) return false;
  for (let i = 0; i < a.line_items.length; i++) {
    const x = a.line_items[i];
    const y = b.line_items[i];
    if (x.item !== y.item || x.quantity !== y.quantity || x.unit_price !== y.unit_price) {
      return false;
    }
  }
  return true;
}
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npx tsc --noEmit
```
Expected: zero errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/invoiceValidation.ts
git commit -m "feat(casefile): pure validation rules for editable invoice draft"
```

---

### Task 22: ExtractionReceipt with editable fields + Save & retry

**Files:**
- Create: `frontend/src/components/casefile/ExtractionReceipt.tsx`

- [ ] **Step 1: Build the ExtractionReceipt**

Create `frontend/src/components/casefile/ExtractionReceipt.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useLocation } from "wouter";
import { retryRun } from "../../api/client.ts";
import { hasErrors, invoicesEqual, validateDraft, type FieldKey } from "../../lib/invoiceValidation.ts";
import type { InvoiceData } from "../../types/state.ts";
import { RotateCcw } from "../common/Icons.tsx";

export function ExtractionReceipt({
  runId,
  invoice,
}: {
  runId: string;
  invoice: InvoiceData;
}) {
  const [, setLocation] = useLocation();
  const [draft, setDraft] = useState<InvoiceData>(invoice);
  const [pending, setPending] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Reset draft when the upstream invoice prop changes (e.g., navigating to a different run).
  useEffect(() => setDraft(invoice), [invoice]);

  const { errors, warnings } = validateDraft(draft);
  const dirty = !invoicesEqual(draft, invoice);
  const canSave = dirty && !hasErrors({ errors, warnings });

  const onSave = async () => {
    setPending(true);
    setErr(null);
    try {
      const { run_id } = await retryRun(runId, draft);
      setLocation(`/runs/${run_id}`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "retry failed");
    } finally {
      setPending(false);
    }
  };

  const setField = <K extends keyof InvoiceData>(key: K, value: InvoiceData[K]) =>
    setDraft({ ...draft, [key]: value });

  const setItemField = (i: number, key: keyof InvoiceData["line_items"][0], value: any) => {
    const items = [...draft.line_items];
    items[i] = { ...items[i], [key]: value };
    setDraft({ ...draft, line_items: items });
  };

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-6">
      <h3 className="text-base font-semibold mb-4">Extraction</h3>
      <dl className="space-y-3">
        <Field
          label="Vendor"
          value={draft.vendor ?? ""}
          onChange={(v) => setField("vendor", v || null)}
          error={errors.vendor}
        />
        <Field
          label="Invoice #"
          value={draft.invoice_number ?? ""}
          onChange={(v) => setField("invoice_number", v || null)}
          error={errors.invoice_number}
          mono
        />
        <Field
          label="Date"
          value={draft.date ?? ""}
          onChange={(v) => setField("date", v || null)}
          placeholder="YYYY-MM-DD"
          error={errors.date}
          mono
        />
        <Field
          label="Due date"
          value={draft.due_date ?? ""}
          onChange={(v) => setField("due_date", v || null)}
          placeholder="YYYY-MM-DD"
          error={errors.due_date}
          mono
        />
      </dl>
      <div className="mt-5">
        <div className="text-xs font-medium uppercase tracking-wide text-slate-500 mb-2">
          Line items
        </div>
        <div className="space-y-2">
          {draft.line_items.map((it, i) => (
            <div key={i} className="grid grid-cols-[1fr_64px_88px] gap-2">
              <FieldInput
                value={it.item}
                onChange={(v) => setItemField(i, "item", v)}
                error={errors[`items.${i}.item` as FieldKey]}
                mono
              />
              <FieldInput
                value={String(it.quantity)}
                onChange={(v) => setItemField(i, "quantity", parseInt(v, 10) || 0)}
                error={errors[`items.${i}.quantity` as FieldKey]}
                mono
              />
              <FieldInput
                value={it.unit_price === null ? "" : String(it.unit_price)}
                onChange={(v) => setItemField(i, "unit_price", v === "" ? null : parseFloat(v))}
                placeholder="0.00"
                error={errors[`items.${i}.unit_price` as FieldKey]}
                mono
              />
            </div>
          ))}
        </div>
      </div>
      <div className="mt-5">
        <Field
          label="Total"
          value={draft.total === null ? "" : String(draft.total)}
          onChange={(v) => setField("total", v === "" ? null : parseFloat(v))}
          error={errors.total}
          warning={warnings.total}
          mono
        />
      </div>
      <div className="mt-6 flex items-center gap-3">
        <button
          type="button"
          onClick={onSave}
          disabled={!canSave || pending}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <RotateCcw size={14} /> {pending ? "Retrying…" : "Save & retry"}
        </button>
        {err && <span className="text-xs text-rose-600">{err}</span>}
      </div>
      <p className="text-xs text-slate-500 mt-2">
        Editing creates a new run. The original stays in the audit trail.
      </p>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  error,
  warning,
  mono,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  error?: string;
  warning?: string;
  mono?: boolean;
}) {
  return (
    <div className="grid grid-cols-[140px_1fr] items-baseline gap-3">
      <dt className="text-xs uppercase tracking-wide text-slate-500">{label}</dt>
      <dd>
        <FieldInput
          value={value}
          onChange={onChange}
          placeholder={placeholder}
          error={error}
          warning={warning}
          mono={mono}
        />
      </dd>
    </div>
  );
}

function FieldInput({
  value,
  onChange,
  placeholder,
  error,
  warning,
  mono,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  error?: string;
  warning?: string;
  mono?: boolean;
}) {
  const borderCls = error
    ? "border-rose-400"
    : warning
      ? "border-amber-400"
      : "border-slate-200";
  return (
    <div>
      <input
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className={`w-full px-2 py-1 text-sm rounded border ${borderCls} focus:outline-none focus:ring-1 focus:ring-indigo-500 ${mono ? "font-mono" : ""}`}
      />
      {error && <p className="text-xs text-rose-600 mt-0.5">{error}</p>}
      {!error && warning && <p className="text-xs text-amber-600 mt-0.5">{warning}</p>}
    </div>
  );
}
```

- [ ] **Step 2: Type-check + build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```
Expected: both succeed.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/casefile/ExtractionReceipt.tsx
git commit -m "feat(casefile): editable ExtractionReceipt with validation and Save & retry"
```

---

## Phase 8 — Validation evidence, agent reasoning, action

### Task 23: ValidationEvidence ledger

**Files:**
- Create: `frontend/src/components/casefile/ValidationEvidence.tsx`

- [ ] **Step 1: Build the ValidationEvidence**

Create `frontend/src/components/casefile/ValidationEvidence.tsx`:

```tsx
import type { ValidationReport } from "../../types/state.ts";
import { AlertTriangle, CheckCircle2, ScrollText, XCircle } from "../common/Icons.tsx";

function SeverityIcon({ severity }: { severity: string }) {
  if (severity === "block") return <XCircle size={14} className="text-rose-600" />;
  if (severity === "warn") return <AlertTriangle size={14} className="text-amber-500" />;
  return <CheckCircle2 size={14} className="text-emerald-600" />;
}

export function ValidationEvidence({ report }: { report: ValidationReport | null }) {
  if (!report) {
    return (
      <div className="bg-white border border-slate-200 rounded-lg p-6">
        <h3 className="text-base font-semibold mb-3 flex items-center gap-2">
          <ScrollText size={18} className="text-slate-400" />
          Validation evidence
        </h3>
        <p className="text-sm text-slate-400">Pending…</p>
      </div>
    );
  }

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-6">
      <h3 className="text-base font-semibold mb-3 flex items-center gap-2">
        <ScrollText size={18} className="text-slate-400" />
        Validation evidence
      </h3>
      <table className="w-full text-sm">
        <tbody>
          {report.vendor_lookup && (
            <tr className="border-b border-slate-100 last:border-0">
              <td className="py-2 pr-3 font-mono text-xs text-slate-500 w-32">vendor.lookup</td>
              <td className="py-2 pr-3 font-mono">{report.vendor_lookup.name}</td>
              <td className="py-2 pr-3 text-slate-600">
                {report.vendor_lookup.found
                  ? `status: ${report.vendor_lookup.status}`
                  : "not found"}
              </td>
              <td className="py-2 text-right">
                {report.vendor_lookup.found && report.vendor_lookup.status === "approved" ? (
                  <CheckCircle2 size={14} className="text-emerald-600 inline" />
                ) : (
                  <XCircle size={14} className="text-rose-600 inline" />
                )}
              </td>
            </tr>
          )}
          {report.inventory_lookups.map((row, i) => (
            <tr key={i} className="border-b border-slate-100 last:border-0">
              <td className="py-2 pr-3 font-mono text-xs text-slate-500 w-32">inventory.find</td>
              <td className="py-2 pr-3 font-mono">{row.item}</td>
              <td className="py-2 pr-3 text-slate-600">
                {row.found
                  ? `stock: ${row.stock}${row.unit_price !== null ? ` · $${row.unit_price.toFixed(2)}` : ""}`
                  : "not found"}
              </td>
              <td className="py-2 text-right">
                {row.found ? (
                  <CheckCircle2 size={14} className="text-emerald-600 inline" />
                ) : (
                  <XCircle size={14} className="text-rose-600 inline" />
                )}
              </td>
            </tr>
          ))}
          {report.issues.map((iss, i) => (
            <tr key={`iss-${i}`} className="border-b border-slate-100 last:border-0">
              <td className="py-2 pr-3 font-mono text-xs text-slate-500 w-32">issue.{iss.kind}</td>
              <td className="py-2 pr-3 font-mono">{iss.item ?? "—"}</td>
              <td className="py-2 pr-3 text-slate-600">{iss.detail}</td>
              <td className="py-2 text-right">
                <SeverityIcon severity={iss.severity} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 2: Type-check + build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```
Expected: both succeed.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/casefile/ValidationEvidence.tsx
git commit -m "feat(casefile): ValidationEvidence ledger with severity icons"
```

---

### Task 24: AgentReasoning with three cards + tool calls

**Files:**
- Create: `frontend/src/components/casefile/AgentReasoning.tsx`

- [ ] **Step 1: Build the AgentReasoning**

Create `frontend/src/components/casefile/AgentReasoning.tsx`:

```tsx
import type { Decision, Proposal, ToolCall } from "../../types/state.ts";
import { Wrench } from "../common/Icons.tsx";
import { OutcomeChip } from "../common/OutcomeChip.tsx";

export function AgentReasoning({ decision }: { decision: Decision | null }) {
  if (!decision) {
    return (
      <div className="bg-white border border-slate-200 rounded-lg p-6">
        <h3 className="text-base font-semibold mb-3">Agent reasoning</h3>
        <p className="text-sm text-slate-400">Pending…</p>
      </div>
    );
  }
  const changed = decision.initial_proposal.outcome !== decision.final_proposal.outcome;
  // Tool calls live on the decision object. For now we attribute all tool calls
  // to the PROPOSE stage since that's where most tool use happens; if events
  // are needed for finer attribution, extend this to read from run.events.
  return (
    <div className="space-y-4">
      <Card stageLabel="Propose" proposal={decision.initial_proposal} toolCalls={decision.tool_calls} />
      <CritiqueCard critique={decision.critique} />
      <Card stageLabel="Finalize" proposal={decision.final_proposal} highlight={changed} />
    </div>
  );
}

function Card({
  stageLabel,
  proposal,
  toolCalls,
  highlight,
}: {
  stageLabel: string;
  proposal: Proposal;
  toolCalls?: ToolCall[];
  highlight?: boolean;
}) {
  return (
    <div
      className={`bg-white border border-slate-200 rounded-lg p-6 ${highlight ? "ring-2 ring-amber-300" : ""}`}
    >
      <div className="flex items-start justify-between mb-3">
        <h4 className="text-xs font-medium uppercase tracking-wide text-slate-500">
          {stageLabel}
        </h4>
        <OutcomeChip outcome={proposal.outcome} />
      </div>
      <p className="text-sm text-slate-800 whitespace-pre-wrap mb-3">{proposal.rationale}</p>
      {proposal.rules_applied.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-3">
          {proposal.rules_applied.map((r, i) => (
            <span
              key={i}
              className="text-xs font-mono px-1.5 py-0.5 rounded bg-slate-100 text-slate-700"
            >
              {r}
            </span>
          ))}
        </div>
      )}
      {toolCalls && toolCalls.length > 0 && (
        <div className="mt-3 border-t border-slate-100 pt-3">
          <div className="text-xs uppercase tracking-wide text-slate-500 mb-1.5 flex items-center gap-1.5">
            <Wrench size={12} /> Tools consulted
          </div>
          <ul className="space-y-1">
            {toolCalls.map((tc, i) => (
              <li key={i} className="font-mono text-xs text-slate-600">
                {tc.tool}({JSON.stringify(tc.arguments)}) → {JSON.stringify(tc.result)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function CritiqueCard({ critique }: { critique: Decision["critique"] }) {
  return (
    <div className="bg-white border border-slate-200 rounded-lg p-6">
      <div className="flex items-start justify-between mb-3">
        <h4 className="text-xs font-medium uppercase tracking-wide text-slate-500">Critique</h4>
        <span
          className={`text-xs px-2 py-0.5 rounded border ${critique.agrees ? "bg-emerald-50 text-emerald-700 border-emerald-200" : "bg-amber-50 text-amber-700 border-amber-200"}`}
        >
          {critique.agrees ? "Agrees" : "Disagrees"}
        </span>
      </div>
      {critique.objections.length > 0 && (
        <List label="Objections" items={critique.objections} />
      )}
      {critique.missed_signals.length > 0 && (
        <List label="Missed signals" items={critique.missed_signals} />
      )}
      {critique.rule_misapplications.length > 0 && (
        <List label="Rule issues" items={critique.rule_misapplications} />
      )}
    </div>
  );
}

function List({ label, items }: { label: string; items: string[] }) {
  return (
    <div className="mb-2 last:mb-0">
      <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">{label}</div>
      <ul className="list-disc list-inside text-sm text-slate-800 space-y-0.5">
        {items.map((x, i) => (
          <li key={i}>{x}</li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 2: Type-check + build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```
Expected: both succeed.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/casefile/AgentReasoning.tsx
git commit -m "feat(casefile): AgentReasoning with three stacked cards and tool calls"
```

---

### Task 25: ActionCard

**Files:**
- Create: `frontend/src/components/casefile/ActionCard.tsx`

- [ ] **Step 1: Build the ActionCard**

Create `frontend/src/components/casefile/ActionCard.tsx`:

```tsx
import type { InvoiceState } from "../../types/state.ts";
import { Receipt } from "../common/Icons.tsx";

export function ActionCard({ state }: { state: Partial<InvoiceState> }) {
  const decision = state.decision;
  const receipt = state.payment_receipt;

  if (state.error) {
    return (
      <div className="bg-white border border-slate-200 rounded-lg p-6">
        <h3 className="text-base font-semibold mb-2 flex items-center gap-2">
          <Receipt size={18} className="text-slate-400" />
          Action
        </h3>
        <p className="text-sm text-slate-700">Could not process — {state.error}</p>
      </div>
    );
  }

  if (!decision) {
    return (
      <div className="bg-white border border-slate-200 rounded-lg p-6">
        <h3 className="text-base font-semibold mb-2 flex items-center gap-2">
          <Receipt size={18} className="text-slate-400" />
          Action
        </h3>
        <p className="text-sm text-slate-400">Pending…</p>
      </div>
    );
  }

  const rulesText = decision.rules_applied.length > 0
    ? decision.rules_applied.join(", ")
    : "—";

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-6">
      <h3 className="text-base font-semibold mb-3 flex items-center gap-2">
        <Receipt size={18} className="text-slate-400" />
        Action
      </h3>
      {decision.outcome === "approved" && (
        <p className="text-sm text-slate-800">
          Approved · paid{receipt ? ` · receipt ${String((receipt as any).receipt_id ?? "")}` : ""}
        </p>
      )}
      {decision.outcome === "rejected" && (
        <p className="text-sm text-slate-800">Rejected · logged · reason: {rulesText}</p>
      )}
      {decision.outcome === "needs_review" && (
        <p className="text-sm text-slate-800">Held for review · {rulesText}</p>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Type-check + build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```
Expected: both succeed.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/casefile/ActionCard.tsx
git commit -m "feat(casefile): ActionCard for approved/rejected/needs_review/error"
```

---

### Task 26: Assemble CaseFilePage

**Files:**
- Modify: `frontend/src/pages/CaseFilePage.tsx`

- [ ] **Step 1: Compose all the case-file sections**

Replace `frontend/src/pages/CaseFilePage.tsx`:

```tsx
import { useEffect, useRef } from "react";
import { useRoute } from "wouter";
import { getRun } from "../api/client.ts";
import { subscribeToRun } from "../api/sse.ts";
import { ActionCard } from "../components/casefile/ActionCard.tsx";
import { AgentReasoning } from "../components/casefile/AgentReasoning.tsx";
import { Breadcrumb } from "../components/casefile/Breadcrumb.tsx";
import { ExtractionReceipt } from "../components/casefile/ExtractionReceipt.tsx";
import { HeroCard } from "../components/casefile/HeroCard.tsx";
import { SourcePanel } from "../components/casefile/SourcePanel.tsx";
import { StageStrip } from "../components/casefile/StageStrip.tsx";
import { ValidationEvidence } from "../components/casefile/ValidationEvidence.tsx";
import { LeftRail } from "../components/layout/LeftRail.tsx";
import { useRunStore } from "../store/runStore.ts";

export function CaseFilePage() {
  const [, params] = useRoute<{ id: string }>("/runs/:id");
  const runId = params?.id ?? null;
  const run = useRunStore((s) => (runId ? s.runs[runId] : null));
  const initializeRun = useRunStore((s) => s.initializeRun);
  const appendEvent = useRunStore((s) => s.appendEvent);
  const hydratedFor = useRef<string | null>(null);
  const sseFor = useRef<{ id: string; close: () => void } | null>(null);

  useEffect(() => {
    if (!runId) return;
    if (run) return;
    if (hydratedFor.current === runId) return;
    hydratedFor.current = runId;
    initializeRun(runId);
    getRun(runId).then((state) => {
      useRunStore.setState((s) => {
        const existing = s.runs[runId];
        if (!existing) return s;
        return {
          runs: {
            ...s.runs,
            [runId]: {
              ...existing,
              state,
              done: state.decision !== null || state.error !== null,
            },
          },
        };
      });
    });
  }, [runId, run, initializeRun]);

  useEffect(() => {
    if (!runId || !run) return;
    if (run.done) return;
    if (sseFor.current?.id === runId) return;
    sseFor.current?.close();
    const close = subscribeToRun(runId, (e) => appendEvent(runId, e));
    sseFor.current = { id: runId, close };
    return () => {
      sseFor.current?.close();
      sseFor.current = null;
    };
  }, [runId, run?.done, appendEvent]);

  if (!runId) return null;
  const state = run?.state ?? {};
  const inv = state.invoice;

  return (
    <div className="flex gap-6">
      <LeftRail />
      <main className="flex-1 min-w-0">
        <Breadcrumb runId={runId} />
        <HeroCard state={state} />
        <StageStrip runId={runId} />
        <div className="grid grid-cols-2 gap-6 mb-6">
          <SourcePanel runId={runId} signals={state.suspicion_signals ?? []} />
          {inv ? (
            <ExtractionReceipt runId={runId} invoice={inv} />
          ) : (
            <div className="bg-white border border-slate-200 rounded-lg p-6">
              <h3 className="text-base font-semibold mb-3">Extraction</h3>
              <p className="text-sm text-slate-400">Pending…</p>
            </div>
          )}
        </div>
        <div className="mb-6">
          <ValidationEvidence report={state.validation ?? null} />
        </div>
        <div className="mb-6">
          <AgentReasoning decision={state.decision ?? null} />
        </div>
        <div className="mb-6">
          <ActionCard state={state} />
        </div>
      </main>
    </div>
  );
}
```

- [ ] **Step 2: Type-check + build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```
Expected: both succeed.

- [ ] **Step 3: Manual verification (Phase 8 boundary — acceptance criteria run-through)**

Start servers:

```bash
cd backend && make dev &
cd frontend && npm run dev
```

Walk through every acceptance criterion from spec §13:

1. **Empty state load** — open `http://localhost:5173`, no runs exist. See zeroed metrics band + intro card with three sample buttons.
2. **Sample click** — click `INV-1003`. Case File loads, stage strip pulses, sections stream in, metrics band increments. ✓
3. **Back to overview** — click `← Back to batch overview`. URL changes to `/`. ✓
4. **Run all 16** — back in top bar, click `Run all 16`. Metrics band counters animate; batch table fills row by row; progress bar in header and rail advance; up to 4 rows show `Loader2`. ✓
5. **Rejected drill** — click a `rejected` row (e.g., INV-1003 again). Source panel underlines the suspicion phrase (or shows chips above source if `text_match` was null). Agent reasoning shows the disagreement with the amber ring on Finalize. Rules are cited. ✓
6. **Edit & retry** — on a Case File for an invoice with a typo, click the vendor name (or any extraction field), edit it, click Save & retry. Navigate to child case file. Original gets the "Superseded by retry" banner. Try entering an invalid date — Save & retry stays disabled. ✓
7. **Left rail** — throughout, the rail shows the session summary and runs list with retries indented under their parents. ✓
8. **Metrics persistence** — all five metrics visible above the fold at every moment. ✓
9. **Deep link** — copy a `/runs/{id}` URL, refresh the page. Case File hydrates correctly without requiring batch state. ✓

If any criterion fails, fix it before committing. Kill servers.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/CaseFilePage.tsx
git commit -m "feat(casefile): assemble full CaseFilePage with all sections"
```

---

## Phase 9 — Cleanup

### Task 27: Delete deprecated components

**Files:**
- Delete: `frontend/src/components/BatchQueue.tsx`
- Delete: `frontend/src/components/CritiquePanel.tsx`
- Delete: `frontend/src/components/DBInspector.tsx`
- Delete: `frontend/src/components/MetricsTile.tsx`
- Delete: `frontend/src/components/RetryButton.tsx`
- Delete: `frontend/src/components/SourceAndExtraction.tsx`
- Delete: `frontend/src/components/StatusBadge.tsx`
- Delete: `frontend/src/components/Timeline.tsx`
- Delete: `frontend/src/components/UploadZone.tsx`

- [ ] **Step 1: Verify no remaining imports of deprecated components**

Run:
```bash
cd frontend && grep -rn "BatchQueue\|CritiquePanel\|DBInspector\|MetricsTile\|RetryButton\|SourceAndExtraction\|StatusBadge\|Timeline\|UploadZone" src/ --include='*.tsx' --include='*.ts'
```
Expected: no results from `src/`. If any are found, they must be the new components in `src/components/layout/`, `src/components/batch/`, `src/components/casefile/`, or `src/components/common/`. Anything pointing to the old flat `src/components/*.tsx` files is a leftover import — fix before deleting.

- [ ] **Step 2: Delete the old components**

```bash
cd frontend && rm \
  src/components/BatchQueue.tsx \
  src/components/CritiquePanel.tsx \
  src/components/DBInspector.tsx \
  src/components/MetricsTile.tsx \
  src/components/RetryButton.tsx \
  src/components/SourceAndExtraction.tsx \
  src/components/StatusBadge.tsx \
  src/components/Timeline.tsx \
  src/components/UploadZone.tsx
```

- [ ] **Step 3: Type-check + build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```
Expected: both succeed.

- [ ] **Step 4: Commit**

```bash
git add -A frontend/src/components
git commit -m "chore(frontend): remove deprecated dashboard components"
```

---

### Task 28: Final manual acceptance walkthrough

**Files:** none (validation only)

- [ ] **Step 1: Start servers**

```bash
cd backend && make dev &
cd frontend && npm run dev
```

- [ ] **Step 2: Demo-script dry run**

Follow the 3-minute demo script from `README.md`:

1. **INV-1001 (clean approve).** Drop the file or click the sample button. The timeline strip lights green; the critique agrees; the action card shows "Approved · paid".
2. **INV-1003 (fraud).** Suspicion phrases like "wire transfer required" are underlined inline in Source. Validation evidence rows show `unknown_vendor` and `out_of_stock`. The Finalize card has an amber ring (changed from initial). Rules cited match the spec.
3. **INV-1012 (OCR typos).** Extraction succeeds despite normalization. Inventory lookups in the evidence table show the resolved items.
4. **Run all 16.** Metrics band animates; batch table fills; progress bar advances; rejected/needs_review rows are visibly different from approved ones.

- [ ] **Step 3: Verify deep-link hydration**

Copy the URL of any case file. Open it in a new browser tab. The case file renders fully — hero card, stage strip, source/extraction, validation evidence, agent reasoning, action card — without requiring batch state to be present in memory.

- [ ] **Step 4: Verify retry flow**

On an invoice with imperfect extraction, edit a field, click Save & retry. The new run appears in the left rail indented under its parent. The original case file (navigate back) shows the "Superseded by retry" banner.

- [ ] **Step 5: Stop servers and confirm clean tree**

```bash
git status
```
Expected: a clean working tree (all changes were committed in previous tasks). If files were modified during manual testing, decide whether to commit them or revert.

- [ ] **Step 6: Run full backend test suite as a final regression check**

```bash
cd backend && pytest -q
```
Expected: all PASS.

- [ ] **Step 7: Run a final frontend build**

```bash
cd frontend && npm run build
```
Expected: clean build.

If everything passes, the implementation is complete.

---

## Self-Review

**Spec coverage check** — every section of the spec maps to a task:

| Spec section | Task(s) |
|---|---|
| §1 Problem & audience | informs everything |
| §2 North-star metaphor | informs everything |
| §3 IA | Tasks 8 (routing), 9 (TopBar), 11 (LeftRail) |
| §4 Metrics band | Task 10 |
| §5 Left rail | Tasks 11, 12 |
| §6 Batch Overview | Tasks 13, 14, 15 |
| §7.1 Breadcrumb | Task 16 |
| §7.2 HeroCard | Task 17 |
| §7.3 Stage strip | Task 18 |
| §7.4 Source + Extraction | Tasks 20, 21, 22 |
| §7.5 Validation evidence | Task 23 |
| §7.6 Agent reasoning | Task 24 |
| §7.7 Action card | Task 25 |
| §8 Visual system | Tasks 5 (fonts/Tailwind), 6 (icons), inlined in component tasks |
| §9 Live behavior & streaming | Tasks 10 (poll), 11 (poll), 15 (poll), 19/26 (SSE), 15 (currentBatch clearance) |
| §10 Routing | Task 8 + URL/store sync verified via Task 19 hydration |
| §11 Out of scope | nothing to implement |
| §12 Component mapping | Task 27 deletes deprecated, all new components are created in Tasks 9-26 |
| §13 Acceptance criteria | Verified in Tasks 15 (#1,3,4), 19 (#9), 26 (#1-9), 28 (full dry run) |
| §14 Backend deltas | Tasks 1, 2, 3 |
| §15 Frontend dependencies | Task 5 |

No gaps.

**Placeholder scan:** Reviewed — every code step has actual code, every command has an expected outcome, no "TBD" / "handle edge cases" / "similar to Task N" markers.

**Type consistency:** Method names checked across tasks. `setActiveRunId`, `startBatch`, `clearBatchIfComplete`, `currentBatch`, `CurrentBatch`, `annotateSource`, `validateDraft`, `invoicesEqual`, `createSampleRun`, `retryRun` are all referenced consistently between definition and use. The `RunSummary` type alias is defined locally in two files (LeftRail.tsx, BatchTable.tsx) via `Awaited<ReturnType<typeof listRuns>>[number]` — this is intentional duplication for locality; if it grows we'd lift it to `types/state.ts`.

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-13-ui-redesign-case-file.md`.**
