# C4 Architecture Diagrams (Structurizr DSL) — Design

**Date:** 2026-05-19
**Status:** Approved (design only — implementation plan to follow)

## Goal

Capture the as-implemented architecture of the invoice-processing prototype in a single, source-controlled Structurizr DSL workspace covering C4 Levels 1–3 (Context, Container, Component), and add a lightweight rule to `CLAUDE.md` so the diagram stays in sync as code evolves.

The diagram is for code reviewers and future contributors — it should answer "what is this system, what runs where, and how does the agent flow fit together" without forcing them to read source.

## Non-goals

- **No C4 Level 4 (Code).** Source is the source of truth at that level; a diagram would rot immediately.
- **No CI gate.** A checklist item in `CLAUDE.md` is enough; we are not adding a hook or workflow check.
- **No rendered PNG/SVG exports.** Adding `structurizr-cli` would pull in a Java/Docker dependency. The DSL is human-readable and the official viewer accepts the raw file.
- **No frontend component-level diagram.** The C2 description plus the existing `frontend/src/` folder structure is enough.

## Deliverables

Three new files plus one edit:

1. `docs/architecture/workspace.dsl` — Structurizr DSL workspace with one Software System in focus, three views (Context, Container, Components-of-Orchestrator), and the styles needed for them to render readably.
2. `docs/architecture/README.md` — short "how to view" guide: open via Structurizr Lite (`docker run -p 8080:8080 structurizr/lite`) pointed at this directory, or paste the DSL into `structurizr.com/dsl`. Lists each container/component and the source path it maps to so reviewers can jump from diagram to code.
3. `CLAUDE.md` — one bullet appended to **Task Lifecycle** requiring `workspace.dsl` updates when architecture-relevant code changes.

## C1 — System Context

**Person**
- `AP Operator` — drags invoices into the UI, reviews case files, retries with edits.

**Software System (in focus)**
- `Acme AP — Invoice Processing` — ingests invoices in six formats, validates against inventory, runs propose/critique/finalize approval, pays or logs.

**External Software Systems**
- `xAI Grok API` — LLM used for extraction, propose, critique, finalize, and tool-use (function calling).
- `Mock Payment API` — represents the simulated payment side-effect performed by the pay agent. Called out at C1 because the brief treats payment as an external dependency, even though it is in-process today.

**Relationships**
- `AP Operator` → `Acme AP` — uses (web UI on `localhost:5173`, CLI via `python -m app.main`)
- `Acme AP` → `xAI Grok API` — HTTPS, chat completions + tool calls
- `Acme AP` → `Mock Payment API` — records payment receipt

## C2 — Containers (inside `Acme AP — Invoice Processing`)

| Container | Technology | Source |
|---|---|---|
| Frontend SPA | React 18 + Vite + TypeScript + Tailwind + zustand + wouter | `frontend/` |
| Backend API | FastAPI on uvicorn, Python 3.11+ | `backend/app/api/` |
| Agent Orchestrator | LangGraph state machine, in-process with Backend API | `backend/app/graph/`, `backend/app/agents/` |
| CLI | Python entry point | `backend/app/main.py` |
| Inventory DB | SQLite file (tables: `inventory`, `vendors`, `paid_invoices`) | `backend/data/inventory.db` |
| Run Registry | In-memory Python object + JSONL log files | `backend/app/api/runs.py`, `backend/logs/<run_id>.jsonl` |
| LLM Gateway | OpenAI SDK pointed at xAI, with retries and structured-output handling | `backend/app/llm/grok_client.py` |

**Relationships**
- Frontend SPA → Backend API — REST under `/api`, plus SSE event stream per run
- Backend API → Agent Orchestrator — in-process; spawns each run via `graph.invoke` on the asyncio thread pool
- Backend API ↔ Run Registry — creates runs, reads summaries, subscribes SSE queues
- CLI → Agent Orchestrator — bypasses the API and Run Registry; same graph
- Agent Orchestrator → LLM Gateway → `xAI Grok API` (external)
- Agent Orchestrator ↔ Inventory DB — reads inventory/vendors, writes `paid_invoices`
- Agent Orchestrator → `Mock Payment API` (external) — via pay agent

**Notes**
- "Agent Orchestrator" shares a Python process with "Backend API" but is split because the agent graph is the architectural centerpiece and worth its own boundary.
- "Run Registry" is documented as in-memory, matching the README's "Known limitations" section.

## C3 — Components of the Agent Orchestrator

| Component | Source | Purpose |
|---|---|---|
| Graph Builder | `graph/builder.py` | Assembles LangGraph: `ingest → validate \| log`, `validate → approve`, `approve → pay \| log` |
| Invoice State | `graph/state.py` | Pydantic state object (`InvoiceState`, `InvoiceData`, `Decision`, `Proposal`, `Critique`, `ToolCall`, `SuspicionSignal`) |
| Ingest Agent | `agents/ingest.py` | One Grok call with structured output; emits suspicion signals; retries on validation failure |
| Homoglyph Check | `agents/homoglyph_check.py` | Detects letter-for-digit substitutions in invoice numbers and dates |
| Validate Agent | `agents/validate.py` | Deterministic SQL checks; surfaces 8 failure modes |
| Approve Agent | `agents/approve.py` | Investigate (tool loop) → propose → critique → finalize |
| Pay Agent | `agents/pay.py` | Records payment, writes `paid_invoices` |
| Log Agent | `agents/log_node.py` | Structured rejection log |
| Rules Engine | `rules/engine.py`, `rules/rules.yaml` | Hard blocks and gate thresholds; LLM cannot override hard blocks |
| LLM Tools | `tools/llm_tools.py`, `tools/inventory_tool.py`, `tools/vendor_tool.py`, `tools/payment_tool.py` | Function-calling tools: `lookup_inventory`, `lookup_vendor`, `recompute_totals` |
| File Loader | `parsers/file_loader.py` | Six-format dispatch (TXT / JSON / CSV / XML / PDF / email) |
| Event Emitter | `logging_/event_emitter.py` | Writes JSONL run logs and feeds the SSE stream |

**Relationships**
- Ingest Agent → File Loader (load raw text per format)
- Ingest Agent → LLM Gateway (Grok extraction with structured output)
- Ingest Agent → Homoglyph Check (annotate extracted invoice number / dates)
- Validate Agent → Inventory DB (SQL reads)
- Approve Agent → LLM Gateway (propose, critique, finalize)
- Approve Agent → Rules Engine (hard blocks, gate thresholds)
- Approve Agent → LLM Tools → Inventory DB / vendors (during investigate phase)
- Pay Agent → Inventory DB (`paid_invoices` insert)
- All agents → Event Emitter → JSONL files / SSE
- Graph Builder owns the Invoice State and wires every node

## CLAUDE.md change

Append one bullet to **Task Lifecycle**:

> 7. **Architecture sync:** if your change adds, removes, or renames a container, agent node, API route, external system, datastore, or LLM tool, update `docs/architecture/workspace.dsl` in the same change. See `docs/architecture/README.md` for what each level covers.

No new section, no hook, no enforcement gate.

## Testing / verification

The DSL is text — verification is "does it parse and render?" Two checks before declaring done:

1. **Parse check.** Paste `docs/architecture/workspace.dsl` into `structurizr.com/dsl` (or run Structurizr Lite locally) and confirm all three views render without errors.
2. **Source map check.** For each container and component listed in the DSL, confirm the documented source path still exists in the repo (one-time grep at write time; the CLAUDE.md rule keeps it true going forward).

## Open questions

None. All four scoping questions were answered up-front; the design above reflects those answers.

## Out of scope (explicitly)

- Deployment view, dynamic view, system landscape view — none of these add value at the prototype stage.
- Per-PR diagram diffs in CI — relying on the CLAUDE.md checklist for now; revisit if the rule is ignored in practice.
- Architecture Decision Records (ADRs) — separate concern; this spec is about the diagram only.
