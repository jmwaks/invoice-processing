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
