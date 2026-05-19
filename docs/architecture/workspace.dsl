workspace "Acme AP — Invoice Processing" "C4 model for the invoice-processing prototype. See docs/architecture/README.md for how to view." {

    model {
        apOperator = person "AP Operator" "Drags invoices into the UI, reviews case files, retries with edits."

        acmeAp = softwareSystem "Acme AP — Invoice Processing" "Ingests invoices in six formats, validates against inventory, runs propose/critique/finalize approval, pays or logs." {
            frontendSpa = container "Frontend SPA" "Batch dashboard and Case File pages. Talks to Backend API via REST and SSE." "React 18, Vite, TypeScript, Tailwind, zustand, wouter" "WebApp"
            backendApi = container "Backend API" "REST endpoints under /api plus an SSE event stream per run." "FastAPI on uvicorn, Python 3.11+" "API"
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
            cli = container "CLI" "Alternative entrypoint that uses the same Orchestrator and LLM Gateway but skips the API layer." "Python (python -m app.main)"
            inventoryDb = container "Inventory DB" "Tables: inventory, vendors, paid_invoices. Persistent." "SQLite file (backend/data/inventory.db)" "Database"
            runRegistry = container "Run Registry" "In-memory run state plus per-run JSONL event logs. Cleared on restart (documented limitation)." "Python object + JSONL files"
            llmGateway = container "LLM Gateway" "Single seam to Grok with retries, structured output, and tool calls." "OpenAI SDK pointed at xAI"
        }

        grok = softwareSystem "xAI Grok API" "Hosted LLM used for invoice extraction, approval proposer, adversarial critic, finalizer, and tool-use (function calling)." "External"
        mockPayment = softwareSystem "Mock Payment API" "Simulated payment side-effect performed by the pay agent. Records a receipt; no real money moves." "External"
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
    }

    views {
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
    }
}
