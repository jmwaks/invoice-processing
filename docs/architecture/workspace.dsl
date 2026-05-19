workspace "Acme AP — Invoice Processing" "C4 model for the invoice-processing prototype. See docs/architecture/README.md for how to view." {

    model {
        apOperator = person "AP Operator" "Drags invoices into the UI, reviews case files, retries with edits."

        acmeAp = softwareSystem "Acme AP — Invoice Processing" "Ingests invoices in six formats, validates against inventory, runs propose/critique/finalize approval, pays or logs." {
            frontendSpa = container "Frontend SPA" "Batch dashboard and Case File pages. Talks to Backend API via REST and SSE." "React 18, Vite, TypeScript, Tailwind, zustand, wouter" "WebApp"
            backendApi = container "Backend API" "REST endpoints under /api plus an SSE event stream per run." "FastAPI on uvicorn, Python 3.11+" "API"
            orchestrator = container "Agent Orchestrator" "LangGraph state machine driving ingest -> validate -> approve -> pay/log. Shares the Backend API process." "Python, LangGraph"
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
    }

    views {
        // views added in Task 5
        theme default
    }
}
