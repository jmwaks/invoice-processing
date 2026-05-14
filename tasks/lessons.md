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

## Plan pre-flight patterns (UI redesign session, 2026-05-13)

Patterns that paid off when running 9 bundles end-to-end:

- **Filename mismatches between plan and disk.** Plan EmptyState referenced `INV-1001.txt`/`INV-1003.json`/`INV-1012.pdf` but real files are `invoice_1001.txt`/`invoice_1003.txt`/`invoice_1012.pdf`. Without pre-flight catch, all three demo sample buttons would 404. Pre-flight: `ls` the referenced directory before approving the bundle.
- **`noUnusedLocals` catches planted-but-unused imports.** Plan's BatchTable imports `Flag` but the Signals column is empty per plan comment — would fail tsc. Plan's `invoiceValidation.ts` imports `LineItem` but only uses it via indexed-access type (`InvoiceData["line_items"][0]`), which doesn't reference the identifier — also fails. Pre-flight: scan plan code for imports vs. usages.
- **Plan code can have its own bugs that pass review.** Plan's CaseFilePage `getRun(...).then(...).finally(...)` had no `.catch` — unhandled rejection on network failure. Caught by quality-review subagent, fixed inline with one-line `.catch(pushToast)`. Pre-flight: when reviewing plan code for promise chains, demand a catch.
- **Subagent prompts must preserve prior inline fixes when a later task re-writes the same file.** Task 27 rewrote CaseFilePage from scratch; without an explicit "preserve `.catch`" instruction, the fix would have been reverted. When a later task replaces a file you've patched, the prompt must list each patch to keep.

## Subagent efficiency patterns

- **Bundle aggressively when plan code is fully prescribed.** 29 tasks → 9 bundles. Per-bundle: one implementer + one (or two) reviewers, vs. 29 × 3 = 87 dispatches. ~3× fewer dispatches at the same quality bar.
- **Collapse dual review → single combined review for scaffolding / pure-utility / display-only bundles.** Keep dual review (spec then quality) for state machines (CaseFilePage hydration + SSE), API surfaces (sample endpoint), and full-page assembly.
- **Skip `npm run build` in intermediate task commits within a bundle.** `tsc --noEmit` catches the issues that matter; reserve the full Vite build for the end of each bundle (or end of the whole project). Cuts subagent wall-time noticeably.
- **One-line fixes go inline.** Don't dispatch a fix-subagent for a single Edit. Per `tasks/lessons.md` predecessors.
- **Defer manual dev-server walkthroughs to one consolidated pass at the end.** Subagents can't drive browsers; phase-boundary manual checks in the plan are for the human. Mention this in each implementer prompt so they don't try.

## Strict-mypy / strict-ruff retrofit

When introducing `mypy --strict` to a codebase not written for it, expect ~50-200 errors at first run. Fix the easy ones (missing return annotations, `dict[str, Any]` substitutions, `Optional` narrowing). For third-party gaps (openai overloads, pyyaml/fitz untyped), use targeted `# type: ignore[code]` instead of fighting them.

## Subagent-driven plan execution (2026-05-13, secondary-gaps session)

Patterns from running 10 bundles → 11 commits via subagent-driven-development:

- **Pre-flight: commit prior dirty work before dispatching task implementers that touch the same files.** When `validate.py` had uncommitted currency_mismatch + split-line work and Task 1 also touched `validate.py`, the implementer's `git add backend/app/agents/validate.py` staged the whole working-tree state — bundling 100+ lines of prior work into a "fix(validate): price drift boundary" commit. Fix retroactively: `git reset --mixed HEAD~1`, manually revert the task-specific changes from working tree (one operator + one test), commit the prior work, re-apply the task changes, commit again. ~5 minutes of git surgery. Cheaper: pre-flight scan for `git status` dirty files in files the bundle will touch; commit them first.
- **Bundle aggressively when the plan groups commits.** The plan had 16 numbered tasks but they collapsed into 10 commits (Tasks 2-5 → one homoglyph commit, Tasks 6-7 → one DB-layer commit, Tasks 8-9 → one validate-check commit, Tasks 12-13 → one decisions/API commit). Following the plan's commit boundaries instead of dispatching per checkbox cut implementer dispatches by ~37%.
- **Parallelize independent bundles in one round.** Bundles D (validate.py), E (pay.py), G (decisions.py/routes.py) touch disjoint files — dispatched concurrently via three `Agent` calls in a single message. ~3× wall-time savings vs. serial. Caveat: `git status` shows other bundles' dirty files to each subagent; spell out in the prompt which files to stage so they don't accidentally include cross-bundle work.
- **Inline trivial bundles instead of dispatching.** Bundles H (one new test in test_replay.py) and I (one YAML edit) were small enough that the controller did them directly. Each subagent dispatch has fixed overhead (prompt + report parsing); skip it when the work is <30 lines and fully prescribed.
- **Right-size models per bundle.** Haiku for mechanical transcription (Task 1: one operator + one test). Sonnet for integration logic and multi-file assembly (most bundles). Opus for the final cross-branch review (payment-adjacent paths need senior judgment). Don't waste opus on transcription, don't trust haiku with design.
- **Skip per-bundle code-quality review on highly-prescribed bundles.** Spec-compliance review still required for business-logic bundles (D pay-check, E pay-persist, F retroactive, G API contract), but a final cross-branch review at the end catches what per-bundle reviews would. Final review costs one opus dispatch vs. ~10 per-bundle quality reviews. Quality floor: never skip spec-compliance for payment or contract surfaces.
- **Trust subagent-reported SHAs; don't `git log` to verify.** Each subagent that returns DONE + a SHA has already verified the commit landed. Re-verifying is dispatch overhead with zero new signal.

## Composite-key migration foot-guns (paid_invoices registry)

- **`set[str]` as in-process dedup becomes wrong the moment the persistent key becomes composite.** `if invoice_number in paid_invoices` was correct under the single-column dedup; after switching to `(vendor_normalized, invoice_number)` PK, the set would false-positive on two vendors using the same invoice_number. Remove the read-from-set; keep the write only for back-compat with existing test signatures. **Or just delete the parameter** — the SQL registry is the only correct source of truth after the migration.
- **"Best-effort, never raises" file writes need explicit try/except OSError.** Spec language alone doesn't enforce it; the implementer wrote the writes as plain `with path.open("a") as f: f.write(...)`, which propagates `OSError` on disk-full / permission. The review caught it; the fix wraps the writes and emits a `..._skipped` event with `reason=f"io_error:{e}"` on failure. Pre-flight: any spec phrase like "best-effort" or "never raises" is a signal to scan the implementation for unguarded I/O.
- **`effective_outcome` composer needs a `base_outcome` parameter for in-flight runs.** Reading `approve.decision` from the jsonl returns `"unprocessable"` for runs that haven't reached approve yet — conflicting with `run.state.decision is None`. Fix: route passes the in-memory `Decision.outcome` (or `None`) as `base_outcome`; composer prefers it over re-deriving from the log. Pattern: composers that fall back to log-scanning should always accept an in-memory hint to short-circuit.

## Append-only sidecar pattern for retroactive overrides

When a later event needs to amend a prior record without mutating its append-only event log, write to a sidecar (`decision_updates.jsonl`) and compose at read time via an `effective_outcome`-style helper. Avoids breaking replay semantics on the source log. The composer reads the sidecar linearly and the latest matching row wins. Document the chronological-latest-wins semantics in the composer docstring — future maintainers will assume hash-map semantics otherwise.

## Subagent "helpful improvement" defects (2026-05-13, extraction-tax session)

Even cheap/Haiku implementers will *interpret* prompts and add things you didn't ask for. Two failure modes hit in a 6-task plan, both during fix-loops where the implementer felt licensed to reason:

- **"Dead code" deletion of an about-to-be-used symbol.** Asked a fix subagent to remove an erroneous `export` keyword from `const TOTAL_TOLERANCE = 1.0`. It deleted the whole constant, reasoning that the constant was unused yet — ignoring that the next plan task (already in the plan I gave it the path to) consumes it three times. Cost: one extra round-trip (`restore TOTAL_TOLERANCE`) plus a polluted commit history (`remove → restore` adjacent commits).
- **Uninstructed `@ts-ignore`.** The restore subagent added `// @ts-ignore TS6133 - used in relationship checks added in next plan task` above the declaration to "suppress the unused-variable warning." I never asked for it; the build didn't need it (`noUnusedLocals` is not on, or wasn't tripping); and once the next task added the consumer the ignore became dead weight. Cost: had to fold the `@ts-ignore` removal into the next task's prompt.

Rules to bake into fix-subagent prompts:

- **Negative-instruction blocklist.** Explicitly list things the subagent must NOT do: "do not delete code outside the explicit deletion list", "do not add `@ts-ignore` / `@ts-expect-error` / eslint-disable", "do not add justification comments", "do not 'improve' anything outside the diff", "do not make dead-code judgment calls — the plan is authoritative".
- **Surgical fix prompts read like patches.** For a one-character fix, the prompt should be "delete the word `export` on line X. Touch nothing else." Anything more discursive invites interpretation. Quote the before/after exactly and end with "report yes/no per: only the targeted change, nothing else."
- **Show the upcoming task's consumer.** If the symbol the subagent is fixing is used in the next bundle, paste the consuming snippet into the prompt. Removes the "is this used?" judgment call entirely.
