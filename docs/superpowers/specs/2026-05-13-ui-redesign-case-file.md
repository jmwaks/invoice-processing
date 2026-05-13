# UI Redesign — Case File

**Date:** 2026-05-13
**Status:** Design approved, ready for implementation planning
**Branch:** feature/ui-improvement

## 1. Problem & audience

The current UI works mechanically (multi-agent pipeline, live SSE, batch processing, metrics) but reads as an engineering observability dashboard: raw JSON dumps, dense `text-xs` everywhere, 8-character hash run IDs, disconnected panels stacked under each other. The README, however, pitches the product as a stakeholder demo — a 3-minute walkthrough that lands with CFOs, AP managers, and prospects.

This redesign optimizes for that audience.

- **Primary audience:** demo / stakeholder pitch (CFO, AP manager, prospect).
- **Hero moment:** end-to-end transparency — "every dollar auditable." Every decision shows source → extraction → rules → rationale → action.
- **Scope:** full frontend redesign. Backend API stays unchanged; we consume what's already shipped.
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

Backed by `GET /api/metrics`. Refetched whenever a run completes (the existing `refreshKey` pattern works).

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
- Linear progress bar with `done / total` caption. Disappears when batch completes.

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

**Empty state** (no runs in session): a friendly intro card replaces the table. Big drop zone + three "Try a sample invoice" buttons preloaded with INV-1001 / INV-1003 / INV-1012. This is the demo opener.

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
- Suspicion signals are inline annotations on the source: a small rose-tinted underline on the suspicious phrase with a hover tooltip giving `kind + severity + detail`. This is the upgrade over the current chip-strip-at-the-bottom approach.
- For PDFs, render the extracted text (existing behavior); PDF rendering is out of scope.

**Extraction (right):**
- Renders the `InvoiceData` as a **styled receipt**, not JSON: labeled rows (Vendor, Invoice #, Date, Items, Total). JetBrains Mono for the values.
- Every field is **inline-editable** (click to edit, blur to commit to local state). Editing does not auto-submit.
- A `Save & retry` button at the bottom of the receipt (the existing `RetryButton` component, restyled). Disabled until the user actually edits a field. On click, POSTs to `/api/runs/{id}/retry` with the edited invoice, then navigates to the new child run's case file.
- A small caption: `Editing creates a new run. The original stays in the audit trail.`

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
- No spinners on the page; absence is the loading state.

## 9. Live behavior & states

- **Streaming:** stages, validation rows, agent reasoning cards, batch table rows all mount via SSE-driven state changes. Absence of a section is its loading state; we never render a spinner on a section header.
- **Empty state** (no runs in session): Batch Overview slot shows the intro card with the three sample-invoice buttons. The metrics band shows zeros with the labels still visible — it remains anchored.
- **Stage progress strip** in Case File mode is sticky to the top of the main pane.
- **Errors:** unprocessable invoices show a calm slate card in the Action slot ("Could not process — {reason}") with the partial extraction still visible above. No giant red banner.
- **Concurrency:** with the backend's `Semaphore(4)`, up to 4 batch rows display the spinner-dot at once. The progress bar reflects completed runs only.
- **Browser back/forward:** navigating between Batch Overview and a Case File pushes history state; back returns to the previous view.

## 10. Routing model

URL-driven, simple:
- `/` — Batch Overview (or the empty-state intro card).
- `/runs/{run_id}` — Case File for that run.

The session summary card and "▶ Batch overview" rail link route to `/`. Run rows route to `/runs/{run_id}`. Retry navigates to `/runs/{new_run_id}`.

No client-side router library required; React state + `history.pushState` is sufficient for this scope.

## 11. Out of scope

- Auth, multi-user, RBAC.
- Mobile / responsive layouts (demo on a laptop).
- Dark mode.
- Settings page, rule editor, admin views.
- Real payment integration (the mock receipt stays).
- Historical search across sessions (the runs list is the session).
- PDF page rendering (we keep the existing extracted-text fallback).
- Search/filter on the left rail.
- Internationalization.

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
5. Click any rejected row → drop into its Case File; see suspicion signals inline-annotated on the source; see the critique → finalize disagreement; see the rules cited.
6. Click any row whose extraction has a typo, edit a field on the receipt, click "Save & retry" → navigate to the child case file; the original gets a "Superseded by retry" banner.
7. The left rail throughout shows the session summary on top, runs list below, retries indented under parents.
8. All five metrics (Runs processed, Auto-approved, Avg time, Total approved, Simulated savings) are visible above the fold at every moment.
