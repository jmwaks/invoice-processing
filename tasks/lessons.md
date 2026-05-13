# Lessons learned

Patterns we hit during subagent-driven implementation. Future sessions should bake these into prompts before dispatching.

## Test path resolution

Test files that reference data on disk must use absolute paths derived from `__file__`, not CWD-relative ones.

- **Wrong:** `Path("app/db/seed.yaml")` or `Path("data/invoices/invoice_1001.txt")`
- **Right:** `SEED = Path(__file__).resolve().parents[1] / "app" / "db" / "seed.yaml"`
- The CWD assumption breaks the moment tests run from somewhere other than `backend/`.

This applied to: `test_db_init.py`, `test_tools.py`, `test_validate_agent.py`, `test_file_loader.py` (PDF sample), `test_integration.py`, `test_api.py`, `test_cli.py`, `test_graph_builder.py`.

## Settings caching

`get_settings()` is called via FastAPI `Depends(...)` per request. Without `@lru_cache(maxsize=1)`, every request re-reads `.env` from disk. Always cache.

Same pattern: `_load_rules` in `rules/engine.py` reads `rules.yaml` per evaluation; `@lru_cache(maxsize=4)` keeps it static.

## External API safety

- All network calls need `timeout=`. We pinned `timeout=30.0` on `GrokClient.structured_complete`'s SDK call.
- Empty `xai_api_key` triggers a constructor reject in `openai>=1.52`. Substitute a placeholder string (`"not-configured"`) when the real key is empty — the SDK then constructs fine, real calls still fail with auth.

## Resource management

- PyMuPDF: `with fitz.open(path) as doc:` — `fitz.open()` holds a file handle and must be closed explicitly.
- SQLite: `try/finally: conn.close()` is the codebase convention. `with sqlite3.connect()` works too but be consistent.

## Error handling

CLAUDE.md mandates "no swallowed errors." In `except` blocks, call `_logger.exception(...)` BEFORE storing the error or returning. Even when state.error captures the string, the traceback should still be logged.

Same with `asyncio.QueueFull`: silent `pass` is a violation. Log a warning that includes the run_id and event kind.

## Pydantic at boundaries

`dict | None` for `vendor_lookup` and `list[dict]` for `inventory_lookups` is a CLAUDE.md violation. Introduce typed result models (`InventoryLookupResult`, `VendorLookupResult`) — the lookup tools return these instead of bare dicts.

For event emissions through the SSE/JSONL pipeline, `result=lookup.model_dump()` so the data is serializable.

## Avoid falsy-collapse in numeric chains

`(inv.subtotal or inv.total)` silently drops a legitimate `0.0` subtotal. Use `inv.subtotal if inv.subtotal is not None else inv.total`. This was a real correctness bug in the validation total-math check.

## Module-level mutable state

`_PAID_INVOICES: set[str]` at module level fails in FastAPI multi-worker mode — each worker has its own copy. Inject the idempotency store as a parameter on `build_graph` and the pay node. Same principle for any "remember across calls" state.

## Function-scoped fixtures over module-scoped

`@pytest.fixture(scope="module")` on a graph fixture means all parametrized tests share the same `paid_invoices` set. Files like `invoice_1011.pdf` and `invoice_1011.txt` both produce `INV-1011`, so the second one silently skips payment. Use `scope="function"` unless the fixture is truly stateless.

## Plan inconsistencies we hit

The plan is mostly clean but had a few authored-once-not-tested bugs:

- `backend/Makefile` recipes had `cd backend && ...` but the Makefile lives at `backend/Makefile`, so the cd descended into `backend/backend/`. Fix: drop the prefix.
- `main.py::_format_summary` used `inv.get('vendor')` on what is actually a Pydantic model after `graph.invoke`. Use attribute access.
- `routes.py` batch endpoint scheduled tasks that mutated `run_ids` inside the task; the endpoint returned an empty list. Fix: create runs synchronously, schedule the graph invoke separately.
- `test_graph_builder` invoice had `line_items=[]` and `total=250.0`, but validate emits `no_line_items` block → hard_block → rejected, contradicting the assertion. Add a real line item.
- Plan code emits `node.complete` events but the test asserted `ingest.complete`. Emit both (or change the test; we chose to emit both to preserve the spec).
- Plan creates a Task 1.3 commit but forgets to `git add` the `__init__.py` and `rules.yaml`. Always include the full file list in the `git add` command.

## Frontend specifics

- `tsconfig.node.json` is needed alongside `tsconfig.json` for `tsc -b` to resolve `vite.config.ts`.
- `noUnusedLocals`/`noUnusedParameters` are strict in our tsconfig — remove unused imports, especially after refactors.
- SSE connections need cleanup tracking via `useRef<Map<>>` + a `useEffect` cleanup. Without it, navigating away from a long-running run leaks the EventSource.
- `handleBatch` must wrap `runBatch()` in `try/finally` so the button isn't permanently disabled on network errors.

## Subagent dispatch patterns

- Bundle related sub-tasks into one implementer prompt (Phase 1's 4 sub-tasks = 1 implementer). Saves dispatch overhead.
- Parallelize independent tasks (Task 7 + Task 8 ran concurrently; they share no files — but you may need to decouple test-file imports between them with local mocks).
- Pre-flight every prompt for: CWD paths, missing `__init__.py` in `git add` commands, plan inconsistencies. Fixing in the prompt is cheaper than fixing in a follow-up.
- One-line fixes (e.g., `scope="module"` → `"function"`, adding `timeout=30.0`) — Edit directly instead of dispatching a fix subagent.
- Collapse to single combined review for scaffolding/config/pure-function tasks. Keep dual review (spec then quality) for state machines, API surfaces, graph wiring, payment paths, multi-module touches.
- Model selection: haiku for mechanical scaffolding with fully-specified content (README, basic file creation); sonnet for integration logic; opus for graph wiring and approval prompts.

## Strict-mypy / strict-ruff retrofit

When introducing `mypy --strict` to a codebase not written for it, expect ~50-200 errors at first run. Fix the easy ones (missing return annotations, `dict[str, Any]` substitutions, `Optional` narrowing). For third-party gaps (openai overloads, pyyaml/fitz untyped), use targeted `# type: ignore[code]` instead of fighting them.
