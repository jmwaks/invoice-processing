# C4 Architecture Diagrams Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Document the as-implemented architecture as a single Structurizr DSL workspace covering C4 Context, Container, and Component views, and add one CLAUDE.md rule so the diagram stays in sync as code evolves.

**Architecture:** Three new docs files (`docs/architecture/workspace.dsl`, `docs/architecture/README.md`) plus one bullet appended to `CLAUDE.md`'s Task Lifecycle section. The DSL describes one Software System in focus (`Acme AP — Invoice Processing`) with one Person (`AP Operator`), two external systems (`xAI Grok API`, `Mock Payment API`), seven containers, and twelve components inside the Agent Orchestrator. No CI gate, no rendered exports, no Java/Docker dependency required to use the repo.

**Tech Stack:** Structurizr DSL (text format, viewable via Structurizr Lite Docker image or the online `structurizr.com/dsl` editor). No code changes to backend or frontend.

---

## File Structure

| Path | Status | Responsibility |
|---|---|---|
| `docs/architecture/workspace.dsl` | Create | Single Structurizr workspace: model + 3 views + styles |
| `docs/architecture/README.md` | Create | "How to view" guide + container/component → source-path map |
| `CLAUDE.md` | Modify | Append one bullet to Task Lifecycle (architecture sync rule) |

The reference spec is `docs/superpowers/specs/2026-05-19-c4-architecture-diagrams-design.md` — task descriptions below reference it.

---

### Task 1: Create the docs/architecture directory and stub workspace.dsl

**Files:**
- Create: `docs/architecture/workspace.dsl`

This task creates a minimal valid Structurizr workspace with just the Person and the Software System in focus, no relationships yet. Subsequent tasks add containers, components, views, and styles.

The DSL grammar reference is https://docs.structurizr.com/dsl. Key facts for this plan:
- A workspace has a `model { }` block and a `views { }` block.
- Identifiers (e.g., `apOperator`, `acmeAp`) are lowercase camelCase and used to reference elements when defining relationships and views.
- Strings use double quotes. Comments use `//` or `/* ... */`.
- Relationships use `source -> destination "description" "technology"`.

- [ ] **Step 1: Create the directory and stub file**

Run:
```bash
mkdir -p docs/architecture
```

Write `docs/architecture/workspace.dsl` with exactly this content:

```dsl
workspace "Acme AP — Invoice Processing" "C4 model for the invoice-processing prototype. See docs/architecture/README.md for how to view." {

    model {
        apOperator = person "AP Operator" "Drags invoices into the UI, reviews case files, retries with edits."

        acmeAp = softwareSystem "Acme AP — Invoice Processing" "Ingests invoices in six formats, validates against inventory, runs propose/critique/finalize approval, pays or logs." {
            // containers added in Task 2
        }

        // external systems added in Task 2
        // relationships added in Task 3
    }

    views {
        // views added in Task 5
        theme default
    }
}
```

- [ ] **Step 2: Verify the file parses**

Open `https://structurizr.com/dsl` in a browser and paste the contents of `docs/architecture/workspace.dsl` into the left panel. The right panel should show "No views defined" without any parse errors. (No views are defined yet — that's Task 5.)

Expected: no red error banner. If the parser reports an error, fix the DSL before continuing.

- [ ] **Step 3: Commit**

```bash
git add docs/architecture/workspace.dsl
git commit -m "docs(architecture): stub Structurizr workspace"
```

---

### Task 2: Add containers and external systems to the model

**Files:**
- Modify: `docs/architecture/workspace.dsl`

Add the seven containers inside `acmeAp` and the two external software systems (`xAI Grok API`, `Mock Payment API`). No relationships yet — those are Task 3.

The container list and source paths come from the spec's C2 table. Match those exactly.

- [ ] **Step 1: Add the containers**

Replace the `// containers added in Task 2` comment inside the `acmeAp { ... }` block with:

```dsl
            frontendSpa = container "Frontend SPA" "Batch dashboard and Case File pages. Talks to Backend API via REST and SSE." "React 18, Vite, TypeScript, Tailwind, zustand, wouter" "WebApp"
            backendApi = container "Backend API" "REST endpoints under /api plus an SSE event stream per run." "FastAPI on uvicorn, Python 3.11+" "API"
            orchestrator = container "Agent Orchestrator" "LangGraph state machine driving ingest -> validate -> approve -> pay/log. Shares the Backend API process." "Python, LangGraph"
            cli = container "CLI" "Alternative entrypoint that uses the same Orchestrator and LLM Gateway but skips the API layer." "Python (python -m app.main)"
            inventoryDb = container "Inventory DB" "Tables: inventory, vendors, paid_invoices. Persistent." "SQLite file (backend/data/inventory.db)" "Database"
            runRegistry = container "Run Registry" "In-memory run state plus per-run JSONL event logs. Cleared on restart (documented limitation)." "Python object + JSONL files"
            llmGateway = container "LLM Gateway" "Single seam to Grok with retries, structured output, and tool calls." "OpenAI SDK pointed at xAI"
```

- [ ] **Step 2: Add the external systems**

Replace the `// external systems added in Task 2` comment (which sits outside the `acmeAp { ... }` block, still inside `model { ... }`) with:

```dsl
        grok = softwareSystem "xAI Grok API" "Hosted LLM used for invoice extraction, approval proposer, adversarial critic, finalizer, and tool-use (function calling)." "External"
        mockPayment = softwareSystem "Mock Payment API" "Simulated payment side-effect performed by the pay agent. Records a receipt; no real money moves." "External"
```

- [ ] **Step 3: Verify the file still parses**

Paste the current `workspace.dsl` into `https://structurizr.com/dsl`. Expected: still "No views defined", no parse errors.

- [ ] **Step 4: Commit**

```bash
git add docs/architecture/workspace.dsl
git commit -m "docs(architecture): add containers and external systems"
```

---

### Task 3: Add system-level and container-level relationships

**Files:**
- Modify: `docs/architecture/workspace.dsl`

Relationships in Structurizr DSL live anywhere inside the `model { }` block. By convention they go at the bottom of the model, after all elements are declared.

- [ ] **Step 1: Add the relationships**

Replace the `// relationships added in Task 3` comment with:

```dsl
        // System-level (C1) relationships
        apOperator -> acmeAp "Uses (web UI on localhost:5173, CLI)"
        acmeAp -> grok "Chat completions and tool calls" "HTTPS"
        acmeAp -> mockPayment "Records payment receipt"

        // Container-level (C2) relationships
        apOperator -> frontendSpa "Drags invoices, reviews case files" "HTTPS"
        apOperator -> cli "Runs invoices one-off or in batch" "shell"
        frontendSpa -> backendApi "REST calls + SSE event stream" "JSON/HTTPS, text/event-stream"
        backendApi -> orchestrator "Invokes graph per run (asyncio thread pool)" "in-process"
        backendApi -> runRegistry "Creates runs, reads summaries, subscribes SSE queues" "in-process"
        cli -> orchestrator "Invokes graph directly (no registry, no SSE)" "in-process"
        orchestrator -> llmGateway "Extract / propose / critique / finalize / tool-use" "in-process"
        orchestrator -> inventoryDb "Reads inventory and vendors; writes paid_invoices" "SQL"
        orchestrator -> mockPayment "Records payment receipt" "in-process"
        llmGateway -> grok "Chat completions, structured output, function calls" "HTTPS"
```

- [ ] **Step 2: Verify the file still parses**

Paste the current `workspace.dsl` into `https://structurizr.com/dsl`. Expected: still no parse errors. The DSL editor's "Explorer" tab on the right should now list the relationships under each element.

- [ ] **Step 3: Commit**

```bash
git add docs/architecture/workspace.dsl
git commit -m "docs(architecture): add C1 and C2 relationships"
```

---

### Task 4: Add components inside the Agent Orchestrator

**Files:**
- Modify: `docs/architecture/workspace.dsl`

Components in Structurizr DSL are nested inside a container's `{ }` block. We need to convert the orchestrator declaration to use the block form, then add eleven components and their relationships.

The component list and source paths come from the spec's C3 table. Match those exactly.

- [ ] **Step 1: Convert orchestrator to block form and add components**

Replace this line:

```dsl
            orchestrator = container "Agent Orchestrator" "LangGraph state machine driving ingest -> validate -> approve -> pay/log. Shares the Backend API process." "Python, LangGraph"
```

with:

```dsl
            orchestrator = container "Agent Orchestrator" "LangGraph state machine driving ingest -> validate -> approve -> pay/log. Shares the Backend API process." "Python, LangGraph" {
                graphBuilder    = component "Graph Builder"    "Assembles LangGraph: ingest -> validate|log, validate -> approve, approve -> pay|log." "backend/app/graph/builder.py"
                invoiceState    = component "Invoice State"    "Pydantic state passed between nodes: InvoiceState, InvoiceData, Decision, Proposal, Critique, ToolCall, SuspicionSignal." "backend/app/graph/state.py"
                fileLoader      = component "File Loader"      "Six-format dispatch: TXT / JSON / CSV / XML / PDF / email." "backend/app/parsers/file_loader.py"
                ingestAgent     = component "Ingest Agent"     "One Grok call with structured output; emits suspicion signals; retries once on validation failure." "backend/app/agents/ingest.py"
                homoglyphCheck  = component "Homoglyph Check"  "Detects letter-for-digit substitutions in invoice numbers and dates." "backend/app/agents/homoglyph_check.py"
                validateAgent   = component "Validate Agent"   "Deterministic SQL checks; surfaces 8 failure modes (missing vendor, unknown item, etc.)." "backend/app/agents/validate.py"
                approveAgent    = component "Approve Agent"    "Investigate (tool loop) -> propose -> critique -> finalize." "backend/app/agents/approve.py"
                payAgent        = component "Pay Agent"        "Records payment, writes paid_invoices." "backend/app/agents/pay.py"
                logAgent        = component "Log Agent"        "Structured rejection log." "backend/app/agents/log_node.py"
                rulesEngine     = component "Rules Engine"     "Hard blocks and gate thresholds; LLM cannot override hard blocks." "backend/app/rules/engine.py + rules.yaml"
                llmTools        = component "LLM Tools"        "Function-calling tools: lookup_inventory, lookup_vendor, recompute_totals." "backend/app/tools/"
                eventEmitter    = component "Event Emitter"    "Writes JSONL run logs and feeds the SSE stream." "backend/app/logging_/event_emitter.py"
            }
```

- [ ] **Step 2: Add component-level relationships**

Components-to-components or components-to-other-containers/systems can be declared in the same place as container relationships. Append these lines immediately after the existing container-level relationships block from Task 3:

```dsl

        // Component-level (C3) relationships (inside Agent Orchestrator)
        graphBuilder    -> ingestAgent    "Wires as entry node"
        graphBuilder    -> validateAgent  "Wires after ingest"
        graphBuilder    -> approveAgent   "Wires after validate"
        graphBuilder    -> payAgent       "Wires on approved"
        graphBuilder    -> logAgent       "Wires on rejected/needs_review/error"
        ingestAgent     -> fileLoader     "Loads raw text per format"
        ingestAgent     -> llmGateway     "Grok extraction with structured output"
        ingestAgent     -> homoglyphCheck "Annotate invoice number / dates"
        validateAgent   -> inventoryDb    "SQL reads"
        approveAgent    -> llmGateway     "Propose / critique / finalize"
        approveAgent    -> rulesEngine    "Hard blocks and gate thresholds"
        approveAgent    -> llmTools       "Investigate phase (tool loop)"
        llmTools        -> inventoryDb    "lookup_inventory / lookup_vendor"
        payAgent        -> inventoryDb    "Insert into paid_invoices"
        payAgent        -> mockPayment    "Record receipt"
        ingestAgent     -> eventEmitter   "Emit progress events"
        validateAgent   -> eventEmitter   "Emit progress events"
        approveAgent    -> eventEmitter   "Emit progress events"
        payAgent        -> eventEmitter   "Emit progress events"
        logAgent        -> eventEmitter   "Emit progress events"
        eventEmitter    -> runRegistry    "JSONL writes; SSE queue feed"
```

- [ ] **Step 3: Verify the file still parses**

Paste the current `workspace.dsl` into `https://structurizr.com/dsl`. Expected: no parse errors. The Explorer should now show the orchestrator container with twelve nested components.

- [ ] **Step 4: Commit**

```bash
git add docs/architecture/workspace.dsl
git commit -m "docs(architecture): add orchestrator components and C3 relationships"
```

---

### Task 5: Add the three views and styles

**Files:**
- Modify: `docs/architecture/workspace.dsl`

Without `views`, Structurizr won't render anything. Add one `systemContext`, one `container`, and one `component` view, plus minimal styling so external systems and databases are visually distinct.

- [ ] **Step 1: Add the views**

Replace the `// views added in Task 5` comment with:

```dsl
        systemContext acmeAp "SystemContext" {
            include *
            autolayout lr
            description "C1 — System Context. AP Operator interacts with the invoice processing system, which calls xAI Grok for LLM work and a mock payment API for the payment side-effect."
        }

        container acmeAp "Containers" {
            include *
            autolayout lr
            description "C2 — Containers. The Backend API and Agent Orchestrator share a Python process; the CLI is an alternative entrypoint that bypasses the API."
        }

        component orchestrator "OrchestratorComponents" {
            include *
            autolayout lr
            description "C3 — Components of the Agent Orchestrator. The LangGraph nodes (ingest, validate, approve, pay, log) plus supporting components (rules engine, LLM tools, file loader, event emitter)."
        }
```

- [ ] **Step 2: Add styles**

Replace the existing `theme default` line with:

```dsl
        styles {
            element "Person" {
                shape Person
                background "#1f3a5f"
                color "#ffffff"
            }
            element "Software System" {
                background "#2563eb"
                color "#ffffff"
            }
            element "External" {
                background "#94a3b8"
                color "#ffffff"
            }
            element "Container" {
                background "#3b82f6"
                color "#ffffff"
            }
            element "Database" {
                shape Cylinder
                background "#0f766e"
                color "#ffffff"
            }
            element "WebApp" {
                shape WebBrowser
            }
            element "API" {
                shape Hexagon
            }
            element "Component" {
                background "#60a5fa"
                color "#0f172a"
            }
        }

        theme default
```

- [ ] **Step 3: Verify all three views render**

Paste the current `workspace.dsl` into `https://structurizr.com/dsl`. Expected:
- A "Diagrams" dropdown appears on the right showing three options: `SystemContext`, `Containers`, `OrchestratorComponents`.
- Each one renders without errors. The Person uses the person shape, the Inventory DB uses a cylinder, the SPA uses a browser shape, external systems are grey, internal containers blue.
- If any view shows overlapping or unreadable boxes, switch the affected view's `autolayout lr` to `autolayout tb` (top-to-bottom) and re-verify.

- [ ] **Step 4: Commit**

```bash
git add docs/architecture/workspace.dsl
git commit -m "docs(architecture): add Context/Container/Component views and styles"
```

---

### Task 6: Verify every documented source path exists

**Files:**
- Read-only checks against `docs/architecture/workspace.dsl`

The DSL embeds source paths in component descriptions and in the README's source-map table (Task 7). If any path is wrong on day one, the rule in CLAUDE.md is built on a lie. Verify them now.

- [ ] **Step 1: Run the path-existence check**

Run from the repo root:

```bash
for p in \
  backend/app/graph/builder.py \
  backend/app/graph/state.py \
  backend/app/parsers/file_loader.py \
  backend/app/agents/ingest.py \
  backend/app/agents/homoglyph_check.py \
  backend/app/agents/validate.py \
  backend/app/agents/approve.py \
  backend/app/agents/pay.py \
  backend/app/agents/log_node.py \
  backend/app/rules/engine.py \
  backend/app/rules/rules.yaml \
  backend/app/tools/llm_tools.py \
  backend/app/tools/inventory_tool.py \
  backend/app/tools/vendor_tool.py \
  backend/app/tools/payment_tool.py \
  backend/app/logging_/event_emitter.py \
  backend/app/api/runs.py \
  backend/app/api/app.py \
  backend/app/api/routes.py \
  backend/app/main.py \
  backend/app/llm/grok_client.py \
  backend/data/inventory.db \
  frontend/src ; do
  if [ -e "$p" ]; then echo "OK  $p"; else echo "MISSING  $p"; fi
done
```

Expected: every line prints `OK`. (`backend/data/inventory.db` may legitimately be missing if seed hasn't run — that's fine, it's still the correct documented path.)

- [ ] **Step 2: Fix any mismatch**

If any path prints `MISSING` and it isn't `inventory.db`, fix the path in `docs/architecture/workspace.dsl` to match where the file actually lives, and re-run Step 1 until clean.

- [ ] **Step 3: Commit only if fixes were needed**

If Step 2 changed anything:

```bash
git add docs/architecture/workspace.dsl
git commit -m "docs(architecture): correct source paths"
```

Otherwise skip the commit.

---

### Task 7: Write the architecture README

**Files:**
- Create: `docs/architecture/README.md`

A short guide that tells a reader (a) how to view the diagram and (b) which source files each container and component maps to. Keep it scannable.

- [ ] **Step 1: Create the README**

Write `docs/architecture/README.md` with exactly this content:

````markdown
# Architecture Diagrams

C4 model for the invoice-processing prototype, written in [Structurizr DSL](https://docs.structurizr.com/dsl). One workspace, three views: System Context (C1), Containers (C2), and Components of the Agent Orchestrator (C3).

## How to view

**Option 1 — online viewer (zero setup):**

1. Open https://structurizr.com/dsl in a browser.
2. Paste the contents of `workspace.dsl` into the left panel.
3. Pick a view from the "Diagrams" dropdown on the right: `SystemContext`, `Containers`, or `OrchestratorComponents`.

**Option 2 — Structurizr Lite (Docker, local):**

```bash
docker run -it --rm -p 8080:8080 -v "$PWD/docs/architecture:/usr/local/structurizr" structurizr/lite
```

Open http://localhost:8080. Edits to `workspace.dsl` reload on refresh.

## Views

| View | Level | What it shows |
|---|---|---|
| `SystemContext` | C1 | AP Operator → Acme AP → (xAI Grok, Mock Payment API) |
| `Containers` | C2 | Frontend SPA, Backend API, Agent Orchestrator, CLI, Inventory DB, Run Registry, LLM Gateway |
| `OrchestratorComponents` | C3 | Twelve components inside the Agent Orchestrator (the LangGraph nodes plus rules engine, LLM tools, file loader, event emitter) |

## Source-path map

Use this when a diagram element raises "where does this live?"

### Containers

| Container | Source |
|---|---|
| Frontend SPA | `frontend/` |
| Backend API | `backend/app/api/` (`app.py`, `routes.py`, `runs.py`, `sse.py`, `decisions.py`) |
| Agent Orchestrator | `backend/app/graph/`, `backend/app/agents/` |
| CLI | `backend/app/main.py` |
| Inventory DB | `backend/data/inventory.db` (schema in `backend/app/db/seed.yaml`) |
| Run Registry | `backend/app/api/runs.py` + `backend/logs/<run_id>.jsonl` |
| LLM Gateway | `backend/app/llm/grok_client.py` |

### Components (Agent Orchestrator)

| Component | Source |
|---|---|
| Graph Builder | `backend/app/graph/builder.py` |
| Invoice State | `backend/app/graph/state.py` |
| File Loader | `backend/app/parsers/file_loader.py` |
| Ingest Agent | `backend/app/agents/ingest.py` |
| Homoglyph Check | `backend/app/agents/homoglyph_check.py` |
| Validate Agent | `backend/app/agents/validate.py` |
| Approve Agent | `backend/app/agents/approve.py` |
| Pay Agent | `backend/app/agents/pay.py` |
| Log Agent | `backend/app/agents/log_node.py` |
| Rules Engine | `backend/app/rules/engine.py` + `backend/app/rules/rules.yaml` |
| LLM Tools | `backend/app/tools/llm_tools.py` + `inventory_tool.py` + `vendor_tool.py` + `payment_tool.py` |
| Event Emitter | `backend/app/logging_/event_emitter.py` |

## Keeping diagrams in sync

`CLAUDE.md` has a Task Lifecycle bullet requiring `workspace.dsl` updates when architecture-relevant code changes (new container, agent node, API route, external system, datastore, or LLM tool). Treat the DSL as part of the change, not as a follow-up.
````

- [ ] **Step 2: Verify the file renders in a Markdown viewer**

Either preview in your editor or:

```bash
cat docs/architecture/README.md | head -40
```

Expected: clean Markdown, tables present, no stray backticks or broken fences.

- [ ] **Step 3: Commit**

```bash
git add docs/architecture/README.md
git commit -m "docs(architecture): add README with view instructions and source map"
```

---

### Task 8: Append the architecture-sync bullet to CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` (the existing Task Lifecycle section ends at line 41)

The existing Task Lifecycle is a numbered list 1–6 (lines 36–41 of the current CLAUDE.md). Append a 7th bullet.

- [ ] **Step 1: Read the current Task Lifecycle section to confirm line numbers**

Run:
```bash
sed -n '35,42p' CLAUDE.md
```

Expected:
```
## Task Lifecycle
1. Write plan to `tasks/todo.md` with checkable items
2. Check in before implementing
3. Mark items complete as you go
4. Summarize changes at each step
5. Add a review section to `tasks/todo.md` when done
6. Update `tasks/lessons.md` after any corrections
```

If the section has drifted (more than 6 items, different wording), stop and re-read `CLAUDE.md` before continuing — the Edit anchor in Step 2 may need adjusting.

- [ ] **Step 2: Append the new bullet**

Use the Edit tool to replace:

```
6. Update `tasks/lessons.md` after any corrections
```

with:

```
6. Update `tasks/lessons.md` after any corrections
7. **Architecture sync:** if your change adds, removes, or renames a container, agent node, API route, external system, datastore, or LLM tool, update `docs/architecture/workspace.dsl` in the same change. See `docs/architecture/README.md` for what each level covers.
```

- [ ] **Step 3: Verify the change**

Run:
```bash
sed -n '35,43p' CLAUDE.md
```

Expected: items 1–7 listed, item 7 is the architecture sync bullet.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: require workspace.dsl updates when architecture changes"
```

---

### Task 9: Final end-to-end verification

**Files:**
- Read-only checks across the three deliverables.

A last pass to make sure the artifacts work together before declaring done.

- [ ] **Step 1: Re-parse the DSL and walk all three views**

Paste `docs/architecture/workspace.dsl` into `https://structurizr.com/dsl` one more time. Walk each of the three views in order: `SystemContext` → `Containers` → `OrchestratorComponents`. For each, confirm:
- All elements render and labels are readable.
- No element is missing relationships it should have (e.g., Approve Agent should show edges to LLM Gateway, Rules Engine, and LLM Tools).
- Database elements use the cylinder shape; external systems are grey.

If any view is too cramped, change that view's `autolayout` from `lr` to `tb` (top-to-bottom), re-verify, and add a single small commit:

```bash
git add docs/architecture/workspace.dsl
git commit -m "docs(architecture): adjust autolayout for readability"
```

- [ ] **Step 2: Confirm the CLAUDE.md bullet is discoverable**

Run:
```bash
grep -n "workspace.dsl" CLAUDE.md
```

Expected: one match in the Task Lifecycle section. If zero matches, Task 8 did not apply — re-do it.

- [ ] **Step 3: Confirm git history shows clean atomic commits**

Run:
```bash
git log --oneline -n 10
```

Expected: a series of `docs(architecture): ...` and `docs: ...` commits, one per task, no fixup or merge noise.

- [ ] **Step 4: No final commit**

This task is verification-only — nothing new to commit. If Steps 1–3 all pass, the work is complete.

---

## Self-review

Spec coverage:

- C1 actors and systems → Task 2 (containers/externals) + Task 3 (relationships). ✓
- C2 containers → Task 2 + Task 3. ✓
- C3 components → Task 4. ✓
- Views → Task 5. ✓
- Styles for visual distinction → Task 5. ✓
- `docs/architecture/README.md` with how-to-view and source map → Task 7. ✓
- CLAUDE.md sync rule → Task 8. ✓
- Verification: parse check → Tasks 1/2/3/4/5 (each ends with a paste-into-DSL check) + Task 9. Source-map check → Task 6. ✓
- Non-goals (no C4 Level 4, no CI gate, no PNG/SVG export, no frontend component view) are honored: nothing in the plan introduces them. ✓

No placeholders found. Type/name consistency checked: identifiers (`acmeAp`, `grok`, `mockPayment`, `frontendSpa`, `backendApi`, `orchestrator`, `cli`, `inventoryDb`, `runRegistry`, `llmGateway`, plus the twelve component identifiers) are referenced consistently across Tasks 2–5.
