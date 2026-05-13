# Project Guidelines

## Workflow

### 1. Planning
- Enter plan mode for any non-trivial task (3+ steps or architectural decisions)
- Write a plan using superpowers plugin with checkable items before implementing
- Check in before starting implementation
- If something goes sideways, stop and re-plan — don't keep pushing

### 2. Subagents
- Use subagents to keep the main context window clean
- Offload research, exploration, and parallel analysis to subagents
- One task per subagent for focused execution

### 3. Verification
- Never mark a task complete without proving it works
- Run tests, check logs, demonstrate correctness
- Ask yourself: "Would a staff engineer approve this?"

### 4. Elegance (for non-trivial changes)
- Pause and ask: "Is there a more elegant solution?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip for simple, obvious fixes — don't over-engineer

### 5. Bug Fixing
- When given a bug report: just fix it — no hand-holding needed
- Use logs, errors, and failing tests to guide resolution
- Fix failing CI tests without being asked

### 6. Self-Improvement
- After any correction: update `tasks/lessons.md` with the pattern and a rule to prevent recurrence
- Review lessons at the start of each session

## Task Lifecycle
1. Write plan to `tasks/todo.md` with checkable items
2. Check in before implementing
3. Mark items complete as you go
4. Summarize changes at each step
5. Add a review section to `tasks/todo.md` when done
6. Update `tasks/lessons.md` after any corrections

## Core Principles
- **Simplicity first**: Make every change as simple as possible; minimize code impact
- **No laziness**: Find root causes, no temporary fixes, senior developer standards
- **Minimal footprint**: Only touch what's necessary; avoid introducing new bugs
- **No unsolicited files**: Don't create markdown files unless explicitly asked

## Code Style
- Python: always use a virtual environment in the project root (create one if missing)
- Place all scripts in the `scripts` directory

## Systems Programming Principles

These principles apply to ALL code in ALL repositories. They are non-negotiable.

### Error Handling & Reliability
- **No swallowed errors.** Every catch/except block must log, handle, or re-raise. Never write bare `except:`, empty `catch {}`, or `_ = err`.
- **Fail fast at boundaries.** Validate all external input (API requests, user input, third-party responses, file contents) at the point of entry. Internal code trusts validated data.
- **Explicit error states.** APIs return structured error responses with correct status codes. Functions return typed errors or throw — never return ambiguous nulls to signal failure.
- **External calls are unreliable.** All network calls (APIs, databases, LLMs, queues) must handle timeouts, malformed responses, and transient failures. Use retries with backoff where appropriate.

### Resource Management
- **Use language-native resource management.** Context managers (Python), `defer` (Go), `try-with-resources` (Java), `using` (C#), RAII (C++/Rust). No manual open/close pairs.
- **Manage connection lifecycles explicitly.** Database pools, HTTP clients, and background workers must be initialized at startup and torn down at shutdown — not created ad-hoc or left as module-level globals.
- **Bound all queues and buffers.** Any in-memory cache, queue, or buffer must have a max size. Unbounded growth is a production incident.

### Type Safety & Contracts
- **Full type annotations on all function signatures.** No untyped public functions. Use the language's type system to make invalid states unrepresentable.
- **Structured types at boundaries.** Use schemas/models (Pydantic, Zod, protobuf, TypeScript interfaces) for data crossing system boundaries. Never pass raw dicts/objects/maps between functions.
- **API contracts are sacred.** Changing a request/response model is a breaking change — treat it as one. Version or migrate, don't silently mutate.
- **No `any`, no `object`, no `interface{}` as a crutch.** Use generics, unions, or discriminated types instead.

### Data Integrity
- **Immutable by default.** Use frozen/readonly data structures where mutation isn't required. Mutability is opt-in, not the default.
- **No global mutable state.** Use dependency injection, context objects, or framework-provided state management. Module-level mutable variables are bugs waiting to happen.
- **Idempotent write operations.** Endpoints and functions that create or modify resources should handle duplicate calls gracefully.

### Performance & Efficiency
- **Respect the runtime's concurrency model.** Never block an async event loop with sync I/O. Never mix threading models carelessly. Use the framework's prescribed patterns.
- **No N+1 patterns.** When fetching related data, batch the query. One loop iteration should not trigger one network or database call.
- **Minimize external call overhead.** Cache deterministic results. Batch where APIs support it. Be aware of payload sizes.

### Security
- **Never log secrets.** API keys, tokens, passwords, and sensitive user data must not appear in log output or error messages.
- **Validate all paths.** Any file path constructed from user input must be sanitized against directory traversal.
- **Secrets live in environment variables.** All keys and credentials come from env vars or a secrets manager. Never hardcode. Never commit secrets files.
- **Sanitize output.** Any user-provided data rendered in HTML, SQL, shell commands, or templates must be escaped/parameterized.

### Testing
- **Every bug fix requires a regression test** that fails before the fix and passes after.
- **Every new endpoint/function with side effects requires an integration test** covering the happy path and at least one error case.
- **Tests must be deterministic.** Mock external services, use fixed seeds for randomness, don't depend on wall-clock time.
- **Test coverage must not decrease.** Verify before marking work complete.

### Code Hygiene
- **One responsibility per function.** If it does parsing AND business logic AND I/O, split it.
- **No dead code.** Remove unused imports, variables, and functions. Don't comment them out "for later."
- **Consistent naming.** Follow the language's conventions (snake_case for Python/Rust, camelCase for JS/TS/Go, PascalCase for classes/components everywhere).
- **Max function length: ~40 lines.** Longer means it's doing too much — extract well-named helpers.