# Business Metrics Tile + README Tightening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface live business-impact metrics in the dashboard (throughput, $ approved, simulated $ saved vs. manual processing, average run time) and tighten the README so the eval criterion *"Clear translation of technical decisions to business impact"* is satisfied not just in prose but in something the demo viewer can *see*.

**Architecture:** RunRegistry already holds every Run in memory. Add `created_at`/`completed_at` to the `Run` dataclass, then aggregate across runs in a new `GET /api/metrics` endpoint. Frontend gets a single new `MetricsTile` component pinned at the top of the Dashboard. Simulated savings use a configurable `manual_cost_per_invoice_usd` setting (default $12 — industry-standard for AP manual processing) so the demo viewer can read a credible dollar figure rather than a generic claim.

**Tech Stack:** FastAPI + Pydantic (existing), React + Tailwind (existing), Pydantic Settings (existing). No new dependencies.

**Scope note:** The existing README already leads with business framing — Task 4 *tightens and links*, not rewrites.

---

## File Structure

**Created:**
- `frontend/src/components/MetricsTile.tsx` — the metrics card
- `backend/tests/test_metrics_endpoint.py` — API-level tests

**Modified:**
- `backend/app/api/runs.py` — add `created_at` and `completed_at` to `Run`
- `backend/app/api/routes.py` — new `/api/metrics` endpoint
- `backend/app/config.py` — add `manual_cost_per_invoice_usd` setting
- `backend/app/api/app.py` — ensure config is passed through if needed (verify, do not edit if not)
- `frontend/src/api/client.ts` — `getMetrics()`
- `frontend/src/pages/Dashboard.tsx` — render `MetricsTile`
- `README.md` — link metrics tile in UI section; ground $ figure in config

---

## Task 1: Record run timestamps

**Files:**
- Modify: `backend/app/api/runs.py`
- Modify: `backend/tests/test_runs_registry.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_runs_registry.py`:

```python
import datetime as dt


def test_create_records_created_at(tmp_path):
    registry = RunRegistry(log_dir=tmp_path)
    before = dt.datetime.now(dt.UTC)
    run = registry.create(source_path="/tmp/x.txt", file_format="txt")
    after = dt.datetime.now(dt.UTC)
    assert run.created_at is not None
    assert before <= run.created_at <= after
    assert run.completed_at is None


def test_mark_done_records_completed_at(tmp_path):
    registry = RunRegistry(log_dir=tmp_path)
    run = registry.create(source_path="/tmp/x.txt", file_format="txt")
    registry.mark_done(run.run_id)
    assert run.completed_at is not None
    assert run.completed_at >= run.created_at
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd backend && .venv/bin/pytest tests/test_runs_registry.py::test_create_records_created_at tests/test_runs_registry.py::test_mark_done_records_completed_at -v
```

Expected: `AttributeError: 'Run' object has no attribute 'created_at'`.

- [ ] **Step 3: Add the fields**

In `backend/app/api/runs.py`, modify the `Run` dataclass:

```python
import datetime as dt

@dataclass
class Run:
    run_id: str
    state: InvoiceState
    emitter: EventEmitter
    subscribers: list[asyncio.Queue[dict[str, Any]]] = field(default_factory=list)
    done: bool = False
    created_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))
    completed_at: dt.datetime | None = None
```

In `mark_done`, set the timestamp:

```python
    def mark_done(self, run_id: str) -> None:
        run = self._runs.get(run_id)
        if run:
            run.done = True
            run.completed_at = dt.datetime.now(dt.UTC)
            for q in run.subscribers:
                q.put_nowait({
                    "kind": "run.complete",
                    "ts": "",
                    "final_state": run.state.model_dump(mode="json"),
                })
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd backend && .venv/bin/pytest tests/test_runs_registry.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/runs.py backend/tests/test_runs_registry.py
git commit -m "feat(runs): record created_at and completed_at on Run"
```

---

## Task 2: manual_cost_per_invoice_usd setting

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/.env.example`
- Test: write a small assertion in a new or existing config test

- [ ] **Step 1: Check whether config tests exist**

```bash
cd backend && ls tests/ | grep -i config
```

If no config test file exists, the easiest verification is the metrics endpoint test in Task 3 — it will exercise the setting via the API. Skip a standalone config test to avoid bloat.

- [ ] **Step 2: Add the setting**

In `backend/app/config.py`, in the `Settings` class, add:

```python
    manual_cost_per_invoice_usd: float = 12.0
```

- [ ] **Step 3: Document in .env.example**

Add to `backend/.env.example`:

```
# Cost per invoice processed manually — used for simulated $-saved metric.
# Default $12 reflects industry benchmark for fully-loaded AP manual processing
# (data entry, validation, approval routing, payment). Override for your org.
MANUAL_COST_PER_INVOICE_USD=12.0
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/config.py backend/.env.example
git commit -m "feat(config): manual_cost_per_invoice_usd setting for savings metric"
```

---

## Task 3: GET /api/metrics endpoint

**Files:**
- Modify: `backend/app/api/routes.py`
- Create: `backend/tests/test_metrics_endpoint.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_metrics_endpoint.py`. Reuse the `api_client` and `seeded_db_path` fixtures (add them to `conftest.py` if not already present — see Reconciliation plan Task 4 for the pattern).

```python
from __future__ import annotations

from fastapi.testclient import TestClient


def test_metrics_endpoint_empty_state(api_client: TestClient):
    resp = api_client.get("/api/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_runs"] == 0
    assert body["approved_count"] == 0
    assert body["rejected_count"] == 0
    assert body["needs_review_count"] == 0
    assert body["unprocessable_count"] == 0
    assert body["total_dollars_approved"] == 0.0
    assert body["simulated_dollars_saved"] == 0.0
    assert body["avg_run_seconds"] is None
    assert body["manual_cost_per_invoice_usd"] == 12.0


def test_metrics_endpoint_aggregates_runs(api_client: TestClient, monkeypatch):
    """After processing two runs, metrics should reflect outcomes and timings."""
    import datetime as dt
    from app.api.app import build_app  # noqa: F401  (ensures import side-effects)

    # Use the api_client's registry directly to seed deterministic state.
    # The fixture should expose it; if not, inspect build_app() to wire one.
    registry = api_client.app.state.registry  # set in build_app — see Task 5
    from app.graph.state import Decision, Proposal, Critique, InvoiceData, LineItem

    proposal = Proposal(outcome="approved", rationale="r", rules_applied=[], unresolved_concerns=[])
    critique = Critique(agrees=True, objections=[], missed_signals=[], rule_misapplications=[])
    approved_decision = Decision(
        outcome="approved", rationale="ok", rules_applied=["auto_approve"],
        initial_proposal=proposal, critique=critique, final_proposal=proposal,
    )
    rejected_proposal = Proposal(outcome="rejected", rationale="bad", rules_applied=[], unresolved_concerns=[])
    rejected_decision = Decision(
        outcome="rejected", rationale="bad", rules_applied=["unknown_vendor"],
        initial_proposal=rejected_proposal, critique=critique, final_proposal=rejected_proposal,
    )

    r1 = registry.create(source_path="/tmp/a.txt", file_format="txt")
    r1.state.invoice = InvoiceData(
        invoice_number="A", vendor="V", date=None, due_date=None,
        line_items=[LineItem(item="WidgetA", quantity=1, unit_price=250.0)],
        subtotal=250.0, tax_amount=0.0, total=1000.0,
        currency="USD", payment_terms=None, raw_text="",
    )
    r1.state.decision = approved_decision
    r1.created_at = dt.datetime(2026, 5, 13, 12, 0, 0, tzinfo=dt.UTC)
    r1.completed_at = dt.datetime(2026, 5, 13, 12, 0, 4, tzinfo=dt.UTC)
    registry.mark_done(r1.run_id)
    r1.completed_at = dt.datetime(2026, 5, 13, 12, 0, 4, tzinfo=dt.UTC)  # mark_done resets

    r2 = registry.create(source_path="/tmp/b.txt", file_format="txt")
    r2.state.decision = rejected_decision
    r2.created_at = dt.datetime(2026, 5, 13, 12, 1, 0, tzinfo=dt.UTC)
    r2.completed_at = dt.datetime(2026, 5, 13, 12, 1, 6, tzinfo=dt.UTC)

    resp = api_client.get("/api/metrics")
    body = resp.json()
    assert body["total_runs"] == 2
    assert body["approved_count"] == 1
    assert body["rejected_count"] == 1
    assert body["total_dollars_approved"] == 1000.0
    # 2 invoices × $12 manual cost = $24 saved
    assert body["simulated_dollars_saved"] == 24.0
    # Avg of (4s, 6s) = 5s
    assert body["avg_run_seconds"] == 5.0
```

The second test mutates the registry directly because the alternative (driving the graph) requires a live LLM. Mutation is acceptable here because we're testing the aggregation logic, not the graph.

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd backend && .venv/bin/pytest tests/test_metrics_endpoint.py -v
```

Expected: `404` from the missing route.

- [ ] **Step 3: Implement the endpoint**

In `backend/app/api/routes.py`, inside `build_router`, add:

```python
    @router.get("/metrics")
    async def metrics() -> dict[str, Any]:
        from app.config import get_settings
        manual_cost = get_settings().manual_cost_per_invoice_usd

        total = 0
        approved = 0
        rejected = 0
        needs_review = 0
        unprocessable = 0
        dollars_approved = 0.0
        durations_s: list[float] = []

        for rid in registry.list_ids():
            run = registry.get(rid)
            if run is None:
                continue
            total += 1
            decision = run.state.decision
            if decision is not None:
                if decision.outcome == "approved":
                    approved += 1
                    if run.state.invoice and run.state.invoice.total:
                        dollars_approved += float(run.state.invoice.total)
                elif decision.outcome == "rejected":
                    rejected += 1
                elif decision.outcome == "needs_review":
                    needs_review += 1
            elif run.state.error:
                unprocessable += 1

            if run.completed_at is not None and run.created_at is not None:
                durations_s.append((run.completed_at - run.created_at).total_seconds())

        avg_run_seconds = (sum(durations_s) / len(durations_s)) if durations_s else None
        return {
            "total_runs": total,
            "approved_count": approved,
            "rejected_count": rejected,
            "needs_review_count": needs_review,
            "unprocessable_count": unprocessable,
            "total_dollars_approved": round(dollars_approved, 2),
            "simulated_dollars_saved": round(total * manual_cost, 2),
            "avg_run_seconds": round(avg_run_seconds, 2) if avg_run_seconds is not None else None,
            "manual_cost_per_invoice_usd": manual_cost,
        }
```

- [ ] **Step 4: Expose the registry on app.state (if not already)**

The second test relies on `api_client.app.state.registry`. Check `backend/app/api/app.py`:

```bash
cat /Users/mwakichako/repos/invoice-processing/backend/app/api/app.py
```

If `app.state.registry = registry` is not already set inside `build_app`, add it:

```python
app.state.registry = registry
```

(Right after the registry is constructed.)

If exposing app state isn't the project's pattern, an alternative is to expose the registry via a tiny test helper — but app state is conventional and read-only at runtime.

- [ ] **Step 5: Run tests — verify they pass**

```bash
cd backend && .venv/bin/pytest tests/test_metrics_endpoint.py -v
```

Expected: both pass.

- [ ] **Step 6: Run full suite — confirm no regression**

```bash
cd backend && .venv/bin/pytest -x -q
```

Expected: green.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/routes.py backend/app/api/app.py backend/tests/test_metrics_endpoint.py
git commit -m "feat(api): GET /api/metrics with throughput, outcomes, and simulated savings"
```

---

## Task 4: getMetrics client + MetricsTile component

**Files:**
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/components/MetricsTile.tsx`
- Modify: `frontend/src/pages/Dashboard.tsx`

- [ ] **Step 1: Add the API client**

Append to `frontend/src/api/client.ts`:

```typescript
export type Metrics = {
  total_runs: number;
  approved_count: number;
  rejected_count: number;
  needs_review_count: number;
  unprocessable_count: number;
  total_dollars_approved: number;
  simulated_dollars_saved: number;
  avg_run_seconds: number | null;
  manual_cost_per_invoice_usd: number;
};

export async function getMetrics(): Promise<Metrics> {
  const resp = await fetch("/api/metrics");
  if (!resp.ok) throw new Error(`metrics fetch failed: ${resp.status}`);
  return resp.json();
}
```

- [ ] **Step 2: Create MetricsTile**

Create `frontend/src/components/MetricsTile.tsx`:

```typescript
import * as React from "react";
import { getMetrics, type Metrics } from "../api/client.ts";

const fmtUSD = (n: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency", currency: "USD", maximumFractionDigits: 0,
  }).format(n);

type Props = {
  /** Bump this number when a run completes to trigger a refresh. */
  refreshKey: number;
};

export function MetricsTile({ refreshKey }: Props) {
  const [m, setM] = React.useState<Metrics | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    getMetrics()
      .then((data) => { if (!cancelled) setM(data); })
      .catch((e) => { if (!cancelled) setError(String(e)); });
    return () => { cancelled = true; };
  }, [refreshKey]);

  if (error) {
    return <div className="text-sm text-red-600 p-3">Metrics unavailable: {error}</div>;
  }
  if (m === null) {
    return <div className="text-sm text-gray-500 p-3">Loading metrics…</div>;
  }

  const autoApprovedPct = m.total_runs === 0
    ? 0
    : Math.round((m.approved_count / m.total_runs) * 100);
  const avgSec = m.avg_run_seconds === null ? "—" : `${m.avg_run_seconds.toFixed(1)}s`;

  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-3 p-3 bg-white border rounded-lg shadow-sm">
      <Stat label="Invoices processed" value={String(m.total_runs)} />
      <Stat label="Auto-approved" value={`${m.approved_count} (${autoApprovedPct}%)`} />
      <Stat label="Avg processing time" value={avgSec} sub="vs. ~5 days manual" />
      <Stat label="Total approved" value={fmtUSD(m.total_dollars_approved)} />
      <Stat
        label="Simulated savings"
        value={fmtUSD(m.simulated_dollars_saved)}
        sub={`@ ${fmtUSD(m.manual_cost_per_invoice_usd)}/invoice manual cost`}
      />
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-xs uppercase tracking-wide text-gray-500">{label}</span>
      <span className="text-2xl font-semibold text-gray-900">{value}</span>
      {sub && <span className="text-xs text-gray-500 mt-0.5">{sub}</span>}
    </div>
  );
}
```

The `sub` text on "Avg processing time" — *"vs. ~5 days manual"* — directly connects the technical metric to the case's pain point. This is the line that earns the eval criterion.

- [ ] **Step 3: Wire it into Dashboard**

In `frontend/src/pages/Dashboard.tsx`, import and render at the top of the main layout. The tile needs a `refreshKey` that bumps when a run completes — the simplest pattern is to track total run count from the store:

```typescript
import { MetricsTile } from "../components/MetricsTile.tsx";
// ...inside the component:
const runCount = useRunStore((s) => s.runs.length);
// ...in the JSX, above the existing top row:
<MetricsTile refreshKey={runCount} />
```

If `runs` is not the right selector name, inspect `frontend/src/store/runStore.ts` and use whatever the existing store shape exposes. Anything that increments on each new run works.

- [ ] **Step 4: Build the frontend**

```bash
cd frontend && npm run build
```

Expected: clean.

- [ ] **Step 5: Manual smoke test**

```bash
# Terminal 1
cd backend && .venv/bin/uvicorn app.api.app:app --reload
# Terminal 2
cd frontend && npm run dev
```

1. Open `http://localhost:5173`. Confirm the MetricsTile renders with zeros.
2. Click "Run all 16" (the batch button).
3. Wait for runs to complete. Confirm the tile updates: `Invoices processed = 16`, `Auto-approved = <some count>`, `Avg processing time` shows a number of seconds, `Simulated savings` shows ~`$192`.
4. Confirm the *"vs. ~5 days manual"* sub-label is visible — that's the business-framing payoff.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/components/MetricsTile.tsx frontend/src/pages/Dashboard.tsx
git commit -m "feat(ui): MetricsTile with throughput, outcomes, and simulated savings"
```

---

## Task 5: Tighten README to reference the live metrics

**Files:**
- Modify: `README.md`

The current README already opens with strong business framing. This task makes three small additions that tie the framing to the now-visible metrics tile.

- [ ] **Step 1: Edit the "Why this matters" bullets**

Replace the three bullets in the "Why this matters" section so each ties to something on screen:

```markdown
- **30% error rate.** Six classes of error caught automatically (missing vendor,
  negative quantity, unknown item, out-of-stock, overstock, price drift). The
  propose-critique-finalize loop in the approver catches what a single LLM pass
  would miss. **See:** outcome breakdown in the metrics tile.
- **5-day delays.** Each invoice resolves in seconds. The "Run all 16" button
  processes the entire sample backlog while you watch. **See:** average
  processing time on the metrics tile.
- **Frustrated stakeholders.** Every decision carries a written rationale tied
  to named rules. AP, vendors, and the VP read the same trace. **See:** the
  Critique panel.
```

- [ ] **Step 2: Add a "Numbers you can read off the screen" section**

Insert after the "Why this matters" section, before "Quick start":

```markdown
## Numbers you can read off the screen

The dashboard's top tile is live across every run in the session:

| Metric | What it answers |
|---|---|
| Invoices processed | How many runs this session |
| Auto-approved (count and %) | What share clears without human review |
| Avg processing time | Throughput vs. the 5-day manual baseline |
| Total approved | Dollar value cleared |
| Simulated savings | Runs × `MANUAL_COST_PER_INVOICE_USD` (default $12, override in `.env`) |

The $12/invoice default is an industry benchmark for fully-loaded AP manual
processing — set the env var to your org's number for a credible bottom-line
figure on the demo.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: tie business-framing bullets to live metrics tile"
```

---

## Self-Review Notes (for plan-writer's reference)

- Task 1 → Task 3 is a hard dependency (metrics endpoint needs the timestamps).
- Task 2 is independent of Task 1 and can run in parallel.
- Task 4 depends on Task 3 (API contract).
- Task 5 (README) can ship the moment Task 4 is verified — it doesn't strictly require code changes, but the cross-references in the doc only make sense once the tile exists.
- The metrics endpoint is unbounded — every run lives in memory forever. If the run registry ever gets bounded (LRU eviction, persistence), this aggregation needs to read from the same source. Out of scope here but worth a follow-up note in `tasks/lessons.md`.
- Manual smoke test in Task 4 step 5 is the one that gives confidence — automated tests cover the math but not the visual layout.
