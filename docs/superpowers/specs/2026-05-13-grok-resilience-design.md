# Grok Client Resilience: Retry, Fallback, Friendly Errors

**Status:** Approved, ready for implementation plan
**Date:** 2026-05-13
**Branch:** `feature/ui-improvement`

## Problem

When xAI's shared Grok capacity is exhausted, the API returns HTTP 429 with
`{"code": "Some resource has been exhausted", "error": "The model is
currently at capacity due to high demand..."}`. Today this error path is
unhandled:

1. `openai` SDK raises `openai.RateLimitError` inside
   `GrokClient.structured_complete` (`backend/app/llm/grok_client.py:49`)
   — the existing retry loop only catches `ValidationError` /
   `JSONDecodeError`, not HTTP errors.
2. The exception propagates through `run_ingest`
   (`backend/app/agents/ingest.py:90`) and `_run_propose / _critique /
   _final` (`backend/app/agents/approve.py:111,129,154`).
3. `_run_graph` (`backend/app/api/routes.py:40`) catches it as a generic
   `Exception` and sets `run.state.error = f"graph crashed: {e}"`.
4. `ActionCard` (`frontend/src/components/casefile/ActionCard.tsx:15`)
   renders the raw OpenAI exception string verbatim:
   `"Could not process — graph crashed: Error code: 429 - {'code': 'Some
   resource has been exhausted', ...}"`.

The user sees provider JSON. A single sub-second xAI capacity dip kills
the entire invoice run with an opaque error.

## Goal

Make a transient Grok outage survivable:

- Retry `grok-4` with exponential backoff + jitter on transient errors
  (429, 5xx, connection/timeout), honoring xAI's `Retry-After` header.
- If retries are exhausted, fall back **once** to `grok-3` with today's
  date injected into the system prompt to compensate for the documented
  grok-3 date-awareness gap ([[llm_grok3_constraints]]).
- If everything fails, surface a clean human-readable message in
  `state.error` — no `"graph crashed:"` prefix, no raw provider JSON.
- Non-transient errors (auth, 400, 404) raise immediately with clean
  config-error messages — no pointless retry, no useless fallback.

## Non-Goals

- Frontend changes. `ActionCard` already renders `state.error` and is
  untouched. No new `error_code` field on `InvoiceState` or SSE events.
- Per-call retry tuning via environment variables. Constants live in
  `grok_client.py`; only the fallback model name is env-configurable
  (YAGNI on the rest until we have a reason to tune).
- Provisioned Throughput integration — out of scope; that's an xAI
  contract decision, not a code change.
- Changes to the existing Pydantic-validation retry loop. It is
  orthogonal and keeps its current semantics.
- Backfilling stored runs in `backend/data/batch_results/runs/` whose
  prior errors contain the ugly string. Logs are immutable; only
  future runs benefit.

## Design

### File-level summary

| File | Change |
| --- | --- |
| `backend/app/llm/grok_client.py` | Add typed exceptions, retry loop, fallback path |
| `backend/app/config.py` | Add `xai_fallback_model: str = "grok-3"` |
| `backend/app/api/app.py` | Pass `fallback_model=` when constructing `GrokClient` |
| `backend/app/api/routes.py` | Catch typed exceptions in `_run_graph`, use clean message |
| `backend/tests/test_grok_client.py` | New tests (see Tests section) |
| `backend/tests/test_api.py` | One new test for `_run_graph` mapping |

### Typed exceptions

In `backend/app/llm/grok_client.py`:

```python
class LLMUnavailableError(Exception):
    """Transient capacity/connectivity failure after retries and fallback."""
    user_message = "Grok is temporarily at capacity. Please retry in a moment."

class LLMConfigurationError(Exception):
    """Non-transient config error (auth, bad model name). No retry helps."""
    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message
```

### Retry policy (grok-4)

Module-private constants:

```python
_MAX_ATTEMPTS = 3        # initial + 2 retries
_BASE_DELAY_S = 0.5
_MAX_DELAY_S = 8.0
```

Delay sequence: `0.5s, 1s, 2s` (capped at `_MAX_DELAY_S`), each with
±25% random jitter. If the `RateLimitError` exposes a `Retry-After`
header (via `response.headers`), honor it instead, capped at
`_MAX_DELAY_S`.

Retried OpenAI SDK exception classes:

| Class | Why |
| --- | --- |
| `openai.RateLimitError` (429) | Capacity dip — usually clears in seconds |
| `openai.APIConnectionError` | Network blip |
| `openai.APITimeoutError` | Server slow, not down |
| `openai.APIStatusError` if `status_code >= 500` | Server error, transient |

`time.sleep` is used between attempts; tests monkey-patch it for
determinism.

### Fallback (grok-3)

After `_MAX_ATTEMPTS` failures on grok-4, **if** `fallback_model` is
non-empty, make exactly one call to the fallback model with a modified
system prompt:

```python
prefixed_system = f"Today's date is {date.today().isoformat()}.\n\n{system}"
```

This compensates for the [[llm_grok3_constraints]] note: grok-3 has no
current-date awareness, so temporal claims (overdue, age) would be
silently wrong otherwise. The injection is unconditional on the
fallback path — even if the original system prompt already mentions a
date, prepending today's date is correct and harmless.

If the fallback call also fails with a retryable error, raise
`LLMUnavailableError`. If it succeeds, return its result transparently.
Callers don't need to know a fallback occurred.

### Error taxonomy

| OpenAI SDK exception | grok-4 retry | grok-3 fallback | Final exception |
| --- | --- | --- | --- |
| `RateLimitError` (429) | yes | yes | `LLMUnavailableError` |
| `APIConnectionError` | yes | yes | `LLMUnavailableError` |
| `APITimeoutError` | yes | yes | `LLMUnavailableError` |
| `APIStatusError` (≥500) | yes | yes | `LLMUnavailableError` |
| `AuthenticationError` (401) | no | no | `LLMConfigurationError("Grok API key invalid or missing.")` |
| `PermissionDeniedError` (403) | no | no | `LLMConfigurationError("Grok API access denied.")` |
| `NotFoundError` (404) | no | no | `LLMConfigurationError("Configured Grok model not found.")` |
| `BadRequestError` (400) | no | no | re-raised as-is — this is our bug |
| `ValidationError` / `JSONDecodeError` | (unchanged) | (unchanged) | (unchanged) — existing inner loop handles |

### Control flow

`structured_complete` is restructured into three private helpers:

```
structured_complete(system, user, schema, max_retries)
  └─ _call_with_retry(model=self.model, system, user, schema, max_retries)
        ├─ for attempt in range(_MAX_ATTEMPTS):
        │     try: return _call_once(model, system, user, schema, max_retries)
        │     except non-retryable: raise (wrapped LLMConfigurationError)
        │     except retryable: sleep and continue
        └─ if exhausted and self.fallback_model:
              try: return _call_once(self.fallback_model, _date_prefixed(system), user, schema, max_retries)
              except retryable: raise LLMUnavailableError
              except non-retryable: raise (wrapped LLMConfigurationError)
        └─ raise LLMUnavailableError
```

`_call_once` is the existing inner Pydantic-validation retry loop,
parameterized by `model`. Validation-retry semantics are unchanged.

### Configuration

`backend/app/config.py` gains one field:

```python
xai_fallback_model: str = "grok-3"
```

Empty string disables fallback. `create_app`
(`backend/app/api/app.py:31-33`) passes it to `GrokClient`:

```python
llm = GrokClient(
    api_key=api_key,
    base_url=settings.xai_base_url,
    model=settings.xai_model,
    fallback_model=settings.xai_fallback_model,
)
```

### Error surface mapping

In `backend/app/api/routes.py`, `_run_graph` (currently lines 30-45)
gains two specific `except` clauses before the generic one:

```python
except LLMUnavailableError as e:
    _logger.warning("LLM unavailable for run %s: %s", run_id, e)
    run.state.error = e.user_message
    run.emitter.emit("run.error", error=e.user_message)
except LLMConfigurationError as e:
    _logger.error("LLM configuration error for run %s: %s", run_id, e)
    run.state.error = e.user_message
    run.emitter.emit("run.error", error=e.user_message)
except Exception as e:
    _logger.exception("graph run failed for %s", run_id)
    run.state.error = f"graph crashed: {e}"
    run.emitter.emit("run.error", error=str(e))
finally:
    registry.mark_done(run_id)
```

The clean messages flow through SSE → `runStore` → `ActionCard` with
zero frontend change.

## Why this approach

**Alternative A: rely on the OpenAI SDK's built-in `max_retries`.** The
SDK supports retry-on-429 natively. Rejected because (1) it doesn't
support model fallback, (2) it doesn't let us inject the date prefix
for grok-3, (3) it would swallow `Retry-After` decisions inside the
SDK where we can't observe them, and (4) we'd still need our own
typed-exception layer for the `_run_graph` boundary.

**Alternative B: handle 429 at the agent layer (`ingest`, `approve`).**
Rejected: three call sites, all doing the same thing. Single
responsibility says the LLM client owns LLM-transport concerns. Agents
shouldn't import `openai` exception types.

**Alternative C: catch + remap inline in `_run_graph`.** Rejected: the
API layer would need to know about `openai.RateLimitError`, which leaks
the SDK choice into FastAPI handler code. The typed-exception layer
draws a clean boundary.

## Tests

### `backend/tests/test_grok_client.py`

Mock the OpenAI SDK with `MagicMock`, use `side_effect` for sequenced
behavior, monkey-patch `time.sleep` for determinism, monkey-patch
`random.uniform` to return midpoint for jitter determinism.

1. **`test_retries_succeed_after_429`** — first call raises
   `RateLimitError`, second returns valid JSON. Assert success, 2 SDK
   calls, `time.sleep` called once.
2. **`test_retries_honor_retry_after_header`** — `RateLimitError` with
   `response.headers = {"Retry-After": "0"}`; assert sleep delay used
   the header value, not the exponential backoff default.
3. **`test_falls_back_to_grok3_after_exhaustion`** — 3 consecutive
   `RateLimitError`s on grok-4 then valid JSON on grok-3. Assert: 4th
   SDK call uses `model="grok-3"`, system prompt starts with `"Today's
   date is "`, returns the grok-3 result successfully.
4. **`test_fallback_disabled_raises_when_empty`** — `fallback_model=""`,
   3 consecutive `RateLimitError`s. Assert `LLMUnavailableError` raised,
   exactly 3 SDK calls (no grok-3 attempt).
5. **`test_auth_error_raises_configuration_error_immediately`** —
   `AuthenticationError` on first call. Assert `LLMConfigurationError`
   with `"key invalid"` in message, exactly 1 SDK call, no fallback.
6. **`test_bad_request_re_raised_as_is`** — `BadRequestError` on first
   call. Assert `BadRequestError` (or its parent) bubbles up unchanged,
   exactly 1 SDK call.
7. **`test_500_error_retries_then_falls_back`** — three `APIStatusError`
   with `status_code=503`, then grok-3 succeeds. Assert successful
   return via grok-3.
8. **`test_total_attempt_budget_is_bounded`** — all calls (including
   grok-3) raise `RateLimitError`. Assert exactly 4 SDK calls total (3
   grok-4 + 1 grok-3), `LLMUnavailableError` raised.
9. **`test_validation_retry_still_works`** — existing-behavior
   regression guard: grok-4 returns invalid-shape JSON once then valid;
   assert single `model="grok-4"` call sequence (no fallback triggered),
   matches the pre-existing
   `test_grok_client_retries_on_validation_error_then_succeeds` shape.

Plus retain the three existing tests in `test_grok_client.py`
unchanged.

### `backend/tests/test_api.py`

10. **`test_run_graph_surfaces_clean_message_on_llm_unavailable`** —
    build a graph whose first node raises `LLMUnavailableError`, run
    it through `_run_graph`, assert `run.state.error == "Grok is
    temporarily at capacity. Please retry in a moment."` (exact
    string, no `"graph crashed:"` prefix), and the SSE `run.error`
    event carries the same string.

## Risk & Rollout

- **Behavioral risk:** the fallback path silently uses a different
  model. Logged at INFO level (`"falling back to %s after grok-4
  exhaustion"`) so it's visible in `logs/` but doesn't alarm. The
  date-prefix injection is the documented mitigation for grok-3's
  weakness; if extraction quality degrades materially during a real
  outage, that's accepted — worse than grok-4, better than a crashed
  run.
- **Latency risk:** worst case adds ~3-4s of backoff before a final
  failure or fallback. Acceptable for an async invoice pipeline.
- **Test determinism:** any test that exercises the retry loop must
  patch `time.sleep` (so suite stays fast) and `random.uniform` (so
  jitter doesn't make assertions flaky). Captured in test guidance
  above.
- **Rollout:** purely additive, no migrations, no API contract change.
  Default config keeps fallback enabled. Operators who want the prior
  behavior can set `XAI_FALLBACK_MODEL=""`.
