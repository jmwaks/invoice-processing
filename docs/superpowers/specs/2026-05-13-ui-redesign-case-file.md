# UI Redesign — Case File

**Date:** 2026-05-13
**Status:** Design approved, ready for implementation planning
**Branch:** feature/ui-improvement

## 1. Problem & audience

The current UI works mechanically (multi-agent pipeline, live SSE, batch processing, metrics) but reads as an engineering observability dashboard: raw JSON dumps, dense `text-xs` everywhere, 8-character hash run IDs, disconnected panels stacked under each other. The README, however, pitches the product as a stakeholder demo — a 3-minute walkthrough that lands with CFOs, AP managers, and prospects.

This redesign optimizes for that audience.

- **Primary audience:** demo / stakeholder pitch (CFO, AP manager, prospect).
- **Hero moment:** end-to-end transparency — "every dollar auditable." Every decision shows source → extraction → rules → rationale → action.
- **Scope:** full frontend redesign, plus two small backend additions (one optional field on `SuspicionSignal`, one new sample-invoice route) — see §14.
- **Aesthetic:** modern fintech (Stripe / Ramp / Mercury). Light theme, generous whitespace, restrained color, big tabular numbers, evidence-forward presentation.

## 2. North-star metaphor

A single invoice is a **case file**: a document a CFO or auditor can read top-to-bottom and trust. The UI's job is to render each invoice as that case file, and to present a batch of invoices as a portfolio of case files with a running scoreboard at the top.

Everything else (panel arrangement, typography, color, motion) follows from this metaphor.

## 3. Information architecture

Single page. One persistent left rail. One main pane with two modes.

```
┌─────────────────────────────────────────────────────────────────┐
│ Acme AP                                  [upload]   [run all]   │  top bar (thin, brand + actions)
├─────────────────────────────────────────────────────────────────┤
│  METRICS BAND  ·  always visible  ·  5 stats                    │  session scoreboard
├────────────┬────────────────────────────────────────────────────┤
│ Session    │                                                    │
│ summary    │                                                    │
│            │            MAIN PANE                               │
│ Runs list  │     (Batch Overview  OR  Case File)                │
│  · INV-1001│                                                    │
│  · INV-1003│                                                    │
│   ↳ retry  │                                                    │
│  · INV-1012│                                                    │
│  ...       │                                                    │
└────────────┴────────────────────────────────────────────────────┘
```

**Top bar** (48px tall): brand mark on the left, primary actions on the right (`Upload invoice`, `Run all 16`). Nothing else.

**Metrics band** (always visible, ~96px tall): the five session stats from `GET /api/metrics`. Sits above everything and never collapses — it is the running CFO scoreboard. See §4.

**Left rail** (280px, sticky): session summary card + runs list. See §5.

**Main pane**: one of two modes:
- **Batch Overview** (§6) — portfolio table for a batch, default when "Run all 16" is invoked.
- **Case File** (§7) — single-invoice deep dive, default when one invoice is uploaded or any run row is clicked.

Mode is implicit (no tabs). Clicking the session summary card or any non-row affordance routes to Batch Overview; clicking a run row routes to that invoice's Case File. Browser back/forward works.

## 4. Metrics band (session scoreboard)

Backed by `GET /api/metrics`. Refetched on the same 1.5s polling tick that drives the runs list (see §9), and on the `run.complete` event from the active SSE stream when a Case File is open.

Five stats in a single row, equal weight, monospace-numeric values:

| Stat | Source field | Display | Subtitle |
|---|---|---|---|
| Runs processed | `total_runs` | `12` | — |
| Auto-approved | `approved_count` + ratio | `9 (75%)` | — |
| Avg processing time | `avg_run_seconds` | `4.2s` | `vs. ~5 days manual` |
| Total approved | `total_dollars_approved` | `$24,310` | — |
| Simulated savings | `simulated_dollars_saved` | `$8,400` | `@ $700/invoice manual cost` |

**Behavior:**
- Numbers animate (counter-up) when the band first mounts and when a value changes by more than 5%. Subtle, ~400ms ease-out. Otherwise update silently.
- When a batch is mid-flight, the band stays mounted — values tick up as runs land. This is the "Run all 16" drama moment.
- On error from `/api/metrics`, the band shows a calm inline message ("Metrics unavailable — retrying") and retries on the next run completion.

**Visual:** white surface, 1px slate-200 border, 24px padding, no shadow. Labels use the Caption token (12px, slate-500, uppercase, tracked). Values use the Display token (§8) with JetBrains Mono for the numeric portion (Inter for non-numeric like `(75%)`). Subtitles use the Caption token, slate-500.

## 5. Left rail

```
┌──────────────────────────┐
│  Session                 │
│  ──────────────────────  │
│  ▶ Batch overview        │   ← clickable; takes main pane to Batch Overview
│                          │
│  Runs                    │
│  ────                    │
│  ● INV-1001  $1,240  ✓   │   ← outcome chip on the right
│  ● INV-1003  $8,400  ✗   │
│  ● INV-1012  $3,500  ⚠   │
│    ↳ retry  $3,500  ✓    │   ← child runs indented under parent
│  ● INV-1014  $920   ✓    │
│  …                       │
└──────────────────────────┘
```

**Session summary card** at the top of the rail:
- Heading: "Session"
- One-line summary: "12 runs · 9 approved · $24.3k approved"
- Below it, a single text link "▶ Batch overview" that switches the main pane to the portfolio view.
- When a batch is mid-flight, the card grows a slim progress bar and a "8 / 16 done" caption.

**Runs list** below:
- Each row: status dot (color = outcome), invoice number, total in muted mono, outcome icon on the right.
- Active row gets a left-edge accent (3px indigo bar) and `bg-slate-50`.
- **Child runs (retries) are indented and prefixed with `↳`** — visualizes the parent/child lineage from `parent_run_id`.
- A run row shows a spinner-dot if its state is still `running`.
- Click a row → main pane switches to that run's Case File.
- The list is scrollable inside the rail; no pagination (16 invoices fits trivially).

**No search/filter in v1.** A single demo session won't have enough rows to need it. Out of scope.

## 6. Main pane — Batch Overview

The portfolio view. Reached by clicking "▶ Batch overview" in the left rail, or by default after clicking "Run all 16."

```
┌────────────────────────────────────────────────────────────────┐
│  Batch overview                                                │
│                                                                │
│  16 invoices · processing in 4-way parallel                    │
│  ████████████░░░░  12 / 16 done                                │
│                                                                │
│  ┌─ Filter: [ All ▾ ]  Sort: [ Time ▾ ]  ─────────────────────┐│
│  │ INV-1001  Acme Supply        $1,240  ● approved   4.1s     ││
│  │ INV-1003  Quik Vendor LLC    $8,400  ✗ rejected   5.8s 🚩  ││
│  │ INV-1012  Bolt & Co          $3,500  ⚠ needs rev  4.7s     ││
│  │   ↳ retry of 1012            $3,500  ● approved   3.9s     ││
│  │ INV-1014  Acme Supply          $920  ● approved   3.2s     ││
│  │ INV-1015  …                                                ││
│  │ …                                                          ││
│  └────────────────────────────────────────────────────────────┘│
└────────────────────────────────────────────────────────────────┘
```

**Header strip:**
- "Batch overview" h2.
- Sub-line: total count, "processing in 4-way parallel" (calls out the backend's `Semaphore(4)`).
- Linear progress bar with `done / total` caption. Tracks **the most recent batch invocation only**, not the cumulative session. State shape: `currentBatch: { runIds: string[], startedAt: number } | null`. `done` = count of `runIds` whose outcome is no longer `running`. Bar appears when `currentBatch` is non-null, dissolves when `done === runIds.length`. Uploading a single invoice does not affect the bar; triggering a new "Run all" replaces the prior batch.

**Table** (one row per run, no nesting except retry indentation):
- Columns: Invoice #, Vendor, Total $, Outcome chip, Processing time, Signal flag (🚩 if `suspicion_signals` non-empty).
- Outcome chips use the same semantic palette as the rest of the UI (emerald / rose / amber / slate).
- Rows arrive live with a subtle 150ms fade-in as each run completes. Sort order is stable (default: by completion time).
- Filter: `All / Approved / Rejected / Needs review / Unprocessable`. Sort: `Time / Vendor / Amount / Outcome`.
- Click a row → swap main pane to Case File for that run.

**Drama choreography for "Run all 16":**
1. Top metrics band counters start ticking up.
2. Progress bar fills.
3. Table rows fade in. Rejected/needs-review rows briefly highlight (subtle amber/rose wash for 600ms).
4. When done, progress bar dissolves; sub-line collapses to "16 invoices · 4.2s avg."

**Empty state** (no runs in session): a friendly intro card replaces the table. Big drop zone + three "Try a sample invoice" buttons preloaded with `INV-1001.txt`, `INV-1003.json`, and `INV-1012.pdf`. Each button calls `POST /api/runs/sample/{filename}` (new endpoint — see §14) and navigates to the resulting Case File. This is the demo opener.

## 7. Main pane — Case File

The deep dive for one invoice. Reached by uploading a single file, clicking a row anywhere, or clicking a left-rail run.

```
┌────────────────────────────────────────────────────────────────┐
│  ← Back to batch overview  ·  12 / 16 done                     │   breadcrumb
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ INV-1003 · Quik Vendor LLC                  ✗ REJECTED   │ │   HERO
│  │ $8,400.00 · processed in 5.8s · 2026-05-13 14:22         │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                │
│  ●━━●━━●━━●━━●   ingest · validate · approve · pay/log         │   stage progress
│                                                                │
│  ┌─ Source ──────────────┬─ Extraction ──────────────────────┐│
│  │  raw PDF/text         │  styled receipt (editable)        ││
│  │  …                    │  Vendor: Quik Vendor LLC          ││
│  │  [suspicion inline]   │  Date:   2026-05-12               ││
│  │                       │  Items:  Widget A × 24            ││
│  │                       │  Total:  $8,400                   ││
│  │                       │  ┌────────────────────┐           ││
│  │                       │  │ [Save & retry]     │           ││
│  │                       │  └────────────────────┘           ││
│  └───────────────────────┴───────────────────────────────────┘│
│                                                                │
│  ┌─ Validation evidence ────────────────────────────────────┐ │
│  │  vendor.lookup  → Quik Vendor LLC    unknown_vendor  ✗   │ │
│  │  inventory.find → Widget A           stock 12 of 24  ✗   │ │
│  │  price.check    → $350 vs $300                       ⚠   │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                │
│  ┌─ Agent reasoning ────────────────────────────────────────┐ │
│  │  PROPOSE  ●━━━━  needs_review                            │ │
│  │  "Item discrepancy + unknown vendor. Hold for human."    │ │
│  │  rules: stock_shortfall · vendor_unknown                 │ │
│  │  tools: rules.check_threshold({amount: 8400}) → ok       │ │
│  │                                                          │ │
│  │  CRITIQUE ━●━━━  disagrees                               │ │
│  │  Objections:                                             │ │
│  │    · "Wire transfer demand is a hard block."             │ │
│  │  Missed signals:                                         │ │
│  │    · urgency_pressure                                    │ │
│  │                                                          │ │
│  │  FINALIZE ━━●━━  rejected      ← changed (highlighted)   │ │
│  │  "Forced rejection: wire-transfer + unknown_vendor."     │ │
│  │  rules: hard_block_wire · vendor_unknown                 │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                │
│  ┌─ Action ─────────────────────────────────────────────────┐ │
│  │  Rejected · logged 2026-05-13 14:22                      │ │
│  │  Reason cited: hard_block_wire, vendor_unknown           │ │
│  └──────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

### 7.1 Breadcrumb
- When the user arrived from Batch Overview: `← Back to batch overview · {done}/{total} done`.
- When arrived from a child-run navigation: `↳ Retry of INV-1012 · 4 fields corrected by user`.
- When this run was superseded by a child retry: a small banner above the hero — `Superseded by retry · run abc12345`. Click goes to the child case file.

### 7.2 Hero card
- Vendor name + invoice number on the left, outcome chip on the right (large variant: 32px height, the chip color is the loudest thing on the page for this run).
- Below: amount in JetBrains Mono at the Display token (§8), then `processed in {time}s · {timestamp}` in the Caption token.
- Background: white; 1px slate-200 border; subtle shadow (the only shadow on the page) to lift it.

### 7.3 Stage progress strip
- Four pips connected by 1px lines: `ingest → validate → approve → pay|log`.
- Pip states: pending (slate-200 ring), running (indigo-600 filled, gentle pulse), done (emerald-600 filled), failed (rose-600 filled).
- The strip is sticky to the top of the main pane while scrolling the case file.
- Replaces the existing `Timeline` component as the live-status surface; the dense timeline detail is folded into Agent reasoning (tool calls) and Validation evidence (per-check rows).

### 7.4 Source / Extraction (two columns, equal width)

**Source (left):**
- Raw file rendered as text in a monospace block with line-numbered gutters.
- **Suspicion signals as inline annotations.** Each `SuspicionSignal` carries an optional `text_match: str | None` (new backend field — see §14). When present, the frontend finds the first case-insensitive occurrence of `text_match` in the source and wraps it with a rose-300 1px underline and a rose-50 hover background; the hover tooltip shows `kind · severity · detail`. When `text_match` is null or not found in the source, the signal falls back to a chip strip rendered **above** the source panel (one chip per signal, same `kind (severity)` format as today). This guarantees the signals are always visible even when offsets can't be located.
- For PDFs, render the extracted text (existing behavior); PDF rendering is out of scope.

**Extraction (right):**
- Renders the `InvoiceData` as a **styled receipt**, not JSON: labeled rows (Vendor, Invoice #, Date, Items, Total). JetBrains Mono for the values.
- Every field is **inline-editable** (click to edit, blur to commit to a local `draft: InvoiceData`). Editing does not auto-submit.
- **Validation** happens on blur against a per-field rules table. Errors are tracked in a local `errors: Record<string, string>` map. Invalid fields get a 1px rose-400 border and a Caption-token error message below the field.

  | Field | Rule | Error message |
  |---|---|---|
  | `vendor` | non-empty after trim | "required" |
  | `invoice_number` | non-empty after trim | "required" |
  | `invoice_date` | matches `^\d{4}-\d{2}-\d{2}$` | "use YYYY-MM-DD" |
  | `items[].name` | non-empty after trim | "required" |
  | `items[].quantity` | parses as integer ≥ 1 | "must be a positive integer" |
  | `items[].unit_price` | parses as number ≥ 0 | "must be ≥ 0" |
  | `total` | parses as number ≥ 0 | "must be ≥ 0" |
  | `total` (soft) | within 1¢ of `sum(items[].quantity × unit_price)` | (amber warning) "doesn't match item total" — non-blocking |

- A `Save & retry` button at the bottom (the existing `RetryButton`, restyled). **Disabled** when the draft equals the original invoice (no edits) or when `errors` is non-empty. The soft total-mismatch warning does NOT block. On click, POSTs the validated `draft` to `/api/runs/{id}/retry`, then navigates to the new child run's case file.
- A small caption below the button: `Editing creates a new run. The original stays in the audit trail.`

### 7.5 Validation evidence
- A compact ledger, one row per check. Columns: `check name · subject · result · status icon`.
- Renders directly from `state.validation` (`inventory_lookups`, `vendor_lookup`, `price_checks`, etc.).
- Tabular, monospace, evidence-feel. No JSON.

### 7.6 Agent reasoning
- Three stacked cards: `PROPOSE`, `CRITIQUE`, `FINALIZE`. Each card has:
  - A horizontal mini-progress indicator showing position in the chain.
  - The card's outcome chip.
  - Rationale rendered as prose (the `rationale` string, not the JSON).
  - Rules cited as small chips along the bottom.
  - **Tools consulted** as a sub-list inside the card that invoked them — one line per `tool.call` event: `tool_name(args) → result`. Monospace, muted slate.
- The `FINALIZE` card gets a 2px amber ring if its outcome differs from `PROPOSE` (existing `changed` logic, restyled). The critique's objections/missed-signals are listed inside the CRITIQUE card.

### 7.7 Action card
- For approved: "Approved · paid 2026-05-13 14:22 · receipt #abc123."
- For rejected: "Rejected · logged 2026-05-13 14:22 · reason: {rules}."
- For needs_review: "Held for review · {rule_or_reason}."
- For unprocessable: error message in a neutral slate card, not rose-red (the error is operational, not financial).

## 8. Visual system

### Type
- **Inter** for all UI text.
- **JetBrains Mono** for amounts, run IDs, invoice numbers, tool calls, source text.
- Type scale:
  - **Display** 30px / 600 (Tailwind `text-3xl`) — metrics band values, Case File hero amount.
  - **Heading** 16px / 600 — section titles ("Agent reasoning", "Validation evidence", etc.).
  - **Body** 14px / 400 — default text.
  - **Caption** 12px / 500, uppercase tracked for labels; 12px / 400 normal for timestamps/sub-text — both in slate-500.
- No 10px/11px text anywhere except the existing rule-chip pattern in Agent reasoning.

### Color
- **Neutral foundation:** slate-50 page background, white surfaces, slate-200 borders, slate-900 primary text, slate-500 secondary text.
- **Brand accent:** indigo-600. Used for the active-row left-edge bar, the running stage pip, primary buttons, focus rings. Used sparingly — fewer than five indigo elements per screen.
- **Semantic status:** emerald-600 (approved / passed), rose-600 (rejected / failed / suspicion), amber-500 (needs review / changed / warning), slate-400 (pending / unknown).
- **Suspicion inline annotations:** rose-300 underline (1px), rose-50 background on hover.
- No gradients. No shadows except on the Case File hero card.

### Spacing
- Tokens: 4 / 8 / 12 / 16 / 24 / 32.
- Card padding: 24px. Section-to-section gap: 32px. Inside-card row gap: 12px.

### Surfaces
- White cards on slate-50 page, 1px slate-200 border, 8px border-radius. No shadows (financial-document feel) — except the hero card.

### Motion
- All transitions: 150ms ease-out, except number counter-up (400ms ease-out).
- Row arrival: 8px upward translate + opacity 0 → 1.
- Stage pip "running" state: 1.4s gentle pulse on the indigo fill.
- No spinners on the page; absence is the loading state. The one exception is the per-row spinner-dot on running batch rows, which uses a small animated `Loader2` icon (see Iconography).

### Iconography
- Library: **lucide-react** (MIT, ~1 KB per icon, ships as React SVG components). Add as a frontend dependency.
- Icon mapping:
  - **Status:** `CheckCircle2` (approved), `XCircle` (rejected), `AlertTriangle` (needs review), `Circle` (pending), `Loader2` (running — animated via Tailwind `animate-spin`).
  - **Actions:** `Upload` (top-bar upload), `Play` ("Run all 16"), `RotateCcw` ("Save & retry"), `ArrowLeft` (back breadcrumb).
  - **Section affordances:** `Flag` (suspicion signal chip), `Wrench` (tool-call sub-list), `ScrollText` (validation evidence heading), `Receipt` (action card heading), `FileSearch` (DB lookup citation).
- Sizes: 16px inside body text, 20px in section headings, 24px in the hero card outcome chip.
- All icons inherit `currentColor`; semantic color comes from the parent text class.

## 9. Live behavior & states

### Streaming strategy (split between polling and SSE)

Browsers cap HTTP/1.1 connections at ~6 per origin, so we cannot open one SSE stream per batch row. The existing app already navigates this — we inherit the pattern and state it explicitly:

- **Batch Overview** (the runs table and the left-rail runs list) **polls** `GET /api/runs` every 1.5s via TanStack Query. Row outcomes, totals, and the parent/child lineage all come from this poll. No SSE.
- **Case File** (the currently-open single run) opens **one SSE stream** to `GET /api/runs/{id}/events`. Stage transitions, validation rows, agent reasoning cards, and tool-call sub-entries all mount from events on that stream. The stream is closed on navigation away or component unmount.
- **Metrics band** refetches on the 1.5s poll tick, and additionally on the `run.complete` event from the active SSE stream when a Case File is open.

Absence of a section is its loading state; we never render a spinner on a section header. The one allowed spinner is the per-row `Loader2` on still-running batch rows.

### Other state behavior

- **Empty state** (no runs in session): Batch Overview slot shows the intro card with the three sample-invoice buttons. The metrics band shows zeros with labels still visible — it remains anchored.
- **Stage progress strip** in Case File mode is sticky to the top of the main pane.
- **Errors:** unprocessable invoices show a calm slate card in the Action slot ("Could not process — {reason}") with the partial extraction still visible above. No giant red banner.
- **Concurrency:** with the backend's `Semaphore(4)`, up to 4 batch rows display the spinner-dot at once. The progress bar reflects completed runs only.
- **Browser back/forward:** wouter's history integration handles this — back from a Case File returns to Batch Overview, forward replays.

### Session lifecycle

The session is **ephemeral by design**. Frontend zustand store and backend `RunRegistry` are both in-memory. A page refresh clears the frontend store; a backend restart wipes the registry; they are consistent only because they go together. Persistence (LocalStorage, DB-backed run history, cross-tab sync) is **out of scope** for v1 — see §11. The demo script never refreshes mid-flow.

## 10. Routing model

URL-driven, with a small router. URL is the source of truth for mode and active run; the zustand store treats `activeRunId` as a derived projection.

- `/` — Batch Overview (or the empty-state intro card when no runs exist).
- `/runs/{run_id}` — Case File for that run.

Navigation:
- Session summary card and "▶ Batch overview" rail link → `/`.
- Any runs-list row, batch-overview row, or sample-invoice button → `/runs/{run_id}`.
- Retry creates a new run server-side, then navigates to `/runs/{new_run_id}`.

**Library: `wouter`** (~1.5 KB). Chosen over `react-router-dom` (~12 KB) because we have two routes and one URL param; over manual `pushState`/`popstate` because deep-link refresh (`/runs/{id}` on a cold load) needs to drive store hydration cleanly. Sync pattern:

```ts
// In App.tsx
const [match, params] = useRoute("/runs/:id");
const setActiveRunId = useRunStore((s) => s.setActiveRunId);
useEffect(() => {
  setActiveRunId(match ? params.id : null);
}, [match, params?.id]);
```

When `/runs/{id}` loads cold, the Case File component sees `activeRunId` set and the run absent from the store; it calls `getRun(id)` once to hydrate, then opens the SSE stream if the run is still running.

## 11. Out of scope

- Auth, multi-user, RBAC.
- Mobile / responsive layouts (demo on a laptop).
- Dark mode.
- Settings page, rule editor, admin views.
- Real payment integration (the mock receipt stays).
- **Session persistence** — no LocalStorage, no DB-backed run history, no cross-tab sync. A page refresh clears the session; a backend restart clears the registry. They go together.
- Historical search across sessions (the runs list is the session).
- PDF page rendering (we keep the existing extracted-text fallback).
- Search/filter on the left rail.
- Internationalization.
- Character-offset locators on `SuspicionSignal` — we use a literal `text_match` phrase instead (see §14). LLMs are unreliable at counting characters.

## 12. Components — proposed mapping from current to new

| Current component | New role |
|---|---|
| `Dashboard.tsx` | Replaced. New top-level shell with top bar, metrics band, rail, mode-driven main pane. |
| `UploadZone.tsx` | Moved into top bar as an `Upload invoice` button; used in the empty-state intro card. |
| `Timeline.tsx` | Replaced by the **Stage progress strip** (live status) + content moves into Agent reasoning (tool calls) and Validation evidence (per-check rows). |
| `SourceAndExtraction.tsx` | Replaced by **Source + Extraction (editable receipt)** in the Case File. |
| `CritiquePanel.tsx` | Replaced by **Agent reasoning** (3 stacked cards) in the Case File. |
| `DBInspector.tsx` | Removed from the demo flow. Its content (inventory + vendors) is implicitly cited inside Validation evidence rows. (Keeping it as a hidden `/admin` view is acceptable but not in scope for v1.) |
| `BatchQueue.tsx` | Split: the runs list moves into the **left rail**; the "Run all 16" button moves into the top bar; the `OutcomeChip` helper stays. |
| `MetricsTile.tsx` | Lifted to the **permanent metrics band** at top. Stat styles upgraded to the new type/color system. |
| `RetryButton.tsx` | Reused inside the Extraction receipt. Restyled to the new button system. |
| `StatusBadge.tsx` | Reused / restyled for outcome chips. |

## 13. Acceptance criteria

A demo session should let the user:

1. Open the app with no runs and see the metrics band (zeroed) plus the empty-state intro card with three sample-invoice buttons.
2. Click a sample → Case File renders; stage strip pulses; sections stream in; the metrics band ticks `Runs processed: 0 → 1` with a 400ms counter animation.
3. From any case file, click "← Back to batch overview" → see the portfolio table for the session.
4. Click "Run all 16" → metrics band counters animate continuously as runs complete; the table fills in; progress bar advances; up to 4 rows show the spinner-dot at once.
5. Click any rejected row → drop into its Case File; see suspicion signals inline-annotated on the source (or chip-stripped above when `text_match` is null/not found); see the critique → finalize disagreement; see the rules cited.
6. Click any row whose extraction has a typo, edit a field on the receipt (with inline validation; bad values block "Save & retry"), click "Save & retry" → navigate to the child case file; the original gets a "Superseded by retry" banner.
7. The left rail throughout shows the session summary on top, runs list below, retries indented under parents.
8. All five metrics (Runs processed, Auto-approved, Avg time, Total approved, Simulated savings) are visible above the fold at every moment.
9. Deep-linking works: pasting `/runs/{id}` into the address bar and refreshing loads the Case File directly, with state hydrated via `getRun(id)`.

## 14. Backend deltas

Two small additions to the backend. Both are demo-flow critical; both are localized.

### 14.1 `SuspicionSignal.text_match` (optional field)

**File:** `backend/app/graph/state.py`

Add an optional field:

```python
class SuspicionSignal(BaseModel):
    kind: str
    detail: str
    severity: Literal["low", "medium", "high"]
    text_match: str | None = None  # NEW: literal phrase from the source to underline
```

**Prompt update:** the ingest agent's structured-output prompt for suspicion signals should be updated to also emit `text_match` — a verbatim phrase copied from the source that triggered the signal (e.g., `"wire transfer required within 24 hours"`). When the agent can't isolate a single phrase, it omits the field (returns null).

**Frontend behavior:** see §7.4. Case-insensitive first-occurrence match; fallback to chip strip above the source when null or unfound.

**Why not character offsets:** LLMs do not reliably count characters, and indices drift on whitespace/newline normalization. A literal substring is robust and matches how the agent already reasons about the source.

### 14.2 `POST /api/runs/sample/{filename}`

**File:** `backend/app/api/routes.py`

New route:

```python
@router.post("/runs/sample/{filename}")
async def create_run_from_sample(filename: str) -> dict[str, str]:
    invoices_dir = get_settings().invoice_processing_invoices_dir.resolve()
    # Reject path traversal: filename must be a single component
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

The path-traversal guard matches the project guideline "Validate all paths."

**Used by:** the three sample-invoice buttons in the empty-state intro card (§6).

## 15. Frontend dependencies

New `package.json` dependencies:

| Package | Version constraint | Purpose | Size |
|---|---|---|---|
| `wouter` | `^3.0.0` | Two-route URL-driven navigation with deep-link support (see §10) | ~1.5 KB |
| `lucide-react` | `^0.400.0` | Icon system (see §8 Iconography) | tree-shaken; ~1 KB per icon used |

No other new dependencies. Existing stack (`react`, `react-dom`, `zustand`, `@tanstack/react-query`, `tailwindcss`, `vite`) remains unchanged.

Font additions to `index.html` or a Tailwind config update: load **Inter** and **JetBrains Mono** from `fonts.googleapis.com` (or self-host) and wire them into `tailwind.config.js` `theme.extend.fontFamily.{sans, mono}`.
