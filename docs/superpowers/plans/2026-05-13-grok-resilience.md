# Grok Client Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make transient xAI Grok outages survivable: exponential-backoff retry on grok-4, single fallback to grok-3 with today's-date prefix, and a clean human-readable error in the case-file UI when both fail.

**Architecture:** All resilience lives in `GrokClient` (`backend/app/llm/grok_client.py`). Agents call `structured_complete` unchanged. The API layer (`_run_graph` in `routes.py`) gains two narrow `except` clauses that map typed exceptions (`LLMUnavailableError`, `LLMConfigurationError`) to clean strings in `run.state.error`. One new env var (`xai_fallback_model`, default `"grok-3"`, empty disables) configures the fallback.

**Tech Stack:** Python 3.11+, pydantic-settings, openai ≥1.40 SDK, pytest, httpx (for constructing test exceptions), mypy strict, ruff (line-length 100).

**Spec:** `docs/superpowers/specs/2026-05-13-grok-resilience-design.md`

---

## Pre-flight

Before Task 1, confirm you're on `feature/ui-improvement` and the working tree is clean except for untracked plans:

```bash
git status
git branch --show-current
```

Expected: branch `feature/ui-improvement`. Activate the project's Python venv (created in repo root per CLAUDE.md) and verify tests run:

```bash
source .venv/bin/activate
cd backend && pytest tests/test_grok_client.py -v
```

Expected: 3 existing tests pass (`test_grok_client_parses_structured_output`, `test_grok_client_retries_on_validation_error_then_succeeds`, `test_grok_client_raises_when_retries_exhausted`).

---

## Task 1: Add `xai_fallback_model` setting

**Files:**
- Modify: `backend/app/config.py`

- [ ] **Step 1: Add the field**

In `backend/app/config.py`, after the `xai_base_url` line, add:

```python
    xai_fallback_model: str = "grok-3"
```

The full `Settings` class becomes:

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    xai_api_key: str = ""
    xai_model: str = "grok-4"
    xai_base_url: str = "https://api.x.ai/v1"
    xai_fallback_model: str = "grok-3"

    invoice_processing_log_dir: Path = Path("./logs")
    invoice_processing_invoices_dir: Path = Path("./data/invoices")
    invoice_processing_db_path: Path = Path("./data/inventory.db")

    run_live_tests: bool = False

    manual_cost_per_invoice_usd: float = 12.0
```

- [ ] **Step 2: Verify mypy + existing tests still pass**

```bash
cd backend && mypy app && pytest -x -q
```

Expected: mypy clean, all tests pass (settings field has a default so nothing else needs updating).

- [ ] **Step 3: Commit**

```bash
git add backend/app/config.py
git commit -m "feat(config): add xai_fallback_model setting (default grok-3)"
```

---

## Task 2: Add typed exceptions and retry constants

**Files:**
- Modify: `backend/app/llm/grok_client.py`

- [ ] **Step 1: Add module-level constants and exception classes**

In `backend/app/llm/grok_client.py`, after the imports, add the constants and exception classes (before the existing `CallMeta` dataclass):

```python
_MAX_ATTEMPTS = 3
_BASE_DELAY_S = 0.5
_MAX_DELAY_S = 8.0


class LLMUnavailableError(Exception):
    """Transient capacity/connectivity failure after retries and fallback."""

    user_message = "Grok is temporarily at capacity. Please retry in a moment."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.user_message)


class LLMConfigurationError(Exception):
    """Non-transient config error (auth, bad model name). No retry helps."""

    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message
```

- [ ] **Step 2: Verify mypy + existing tests pass**

```bash
cd backend && mypy app && pytest tests/test_grok_client.py -v
```

Expected: 3 existing tests still pass; mypy clean.

- [ ] **Step 3: Commit**

```bash
git add backend/app/llm/grok_client.py
git commit -m "feat(grok): add typed exceptions and retry constants"
```

---

## Task 3: Refactor `structured_complete` to extract `_call_once` (no behavior change)

**Files:**
- Modify: `backend/app/llm/grok_client.py`

This is a pure refactor. The existing single-call body becomes a private method parameterized by `model`. Also adds the unused `fallback_model` constructor arg (wired up in later tasks).

- [ ] **Step 1: Update `__init__` to accept `fallback_model`**

Replace the existing `__init__`:

```python
    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str = "https://api.x.ai/v1",
        model: str = "grok-4",
        fallback_model: str = "",
        sdk: OpenAI | None = None,
    ) -> None:
        self.model = model
        self.fallback_model = fallback_model
        self.sdk = sdk or OpenAI(api_key=api_key, base_url=base_url)
```

- [ ] **Step 2: Extract `_call_once`**

Add the private method on `GrokClient` (the body is the existing `while True:` loop from `structured_complete`, parameterized by `model`):

```python
    def _call_once(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: type[T],
        max_retries: int,
    ) -> tuple[T, CallMeta]:
        """One SDK call with inner Pydantic-validation retry loop."""
        attempts = 0
        last_error: str | None = None
        while True:
            attempts += 1
            t0 = perf_counter()
            messages: list[dict[str, str]] = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
            if last_error is not None:
                messages.append({
                    "role": "user",
                    "content": (
                        "Your previous output failed validation with this error:\n"
                        f"{last_error}\nReturn corrected JSON only."
                    ),
                })
            resp = self.sdk.chat.completions.create(  # type: ignore[call-overload]
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
                timeout=30.0,
            )
            elapsed_ms = int((perf_counter() - t0) * 1000)
            content = resp.choices[0].message.content or "{}"
            usage = resp.usage
            try:
                parsed = schema.model_validate(json.loads(content))
                meta = CallMeta(
                    tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
                    tokens_out=getattr(usage, "completion_tokens", 0) or 0,
                    latency_ms=elapsed_ms,
                    model=model,
                )
                return parsed, meta
            except (ValidationError, json.JSONDecodeError) as e:
                last_error = str(e)
                if attempts > max_retries:
                    raise
```

- [ ] **Step 3: Reduce `structured_complete` to a thin wrapper**

Replace `structured_complete` with:

```python
    def structured_complete(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        max_retries: int = 1,
    ) -> tuple[T, CallMeta]:
        """LLM call with retry on Pydantic validation failure."""
        return self._call_once(
            model=self.model,
            system=system,
            user=user,
            schema=schema,
            max_retries=max_retries,
        )
```

- [ ] **Step 4: Verify all 3 existing tests still pass**

```bash
cd backend && pytest tests/test_grok_client.py -v
```

Expected: 3/3 pass. Behavior is unchanged.

- [ ] **Step 5: Verify mypy clean**

```bash
cd backend && mypy app
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add backend/app/llm/grok_client.py
git commit -m "refactor(grok): extract _call_once, accept fallback_model arg"
```

---

## Task 4: Add retry loop for `RateLimitError` (the core 429 case)

**Files:**
- Modify: `backend/app/llm/grok_client.py`
- Modify: `backend/tests/test_grok_client.py`

- [ ] **Step 1: Add a test helper for constructing real `RateLimitError` instances**

At the top of `backend/tests/test_grok_client.py`, add helper imports and a constructor (after the existing `from app.llm.grok_client import GrokClient` line):

```python
import httpx
from openai import RateLimitError


def _rate_limit_error(retry_after: str | None = None) -> RateLimitError:
    headers = {"retry-after": retry_after} if retry_after is not None else {}
    response = httpx.Response(
        429,
        headers=headers,
        request=httpx.Request("POST", "https://api.x.ai/v1/chat/completions"),
    )
    return RateLimitError(message="capacity exhausted", response=response, body=None)
```

- [ ] **Step 2: Write the failing test `test_retries_succeed_after_429`**

Append to `backend/tests/test_grok_client.py`:

```python
def test_retries_succeed_after_429(monkeypatch):
    """First grok-4 call raises 429, second returns valid JSON. Assert 2 SDK calls."""
    sleeps: list[float] = []
    monkeypatch.setattr("app.llm.grok_client.time.sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr("app.llm.grok_client.random.uniform", lambda a, b: (a + b) / 2)

    good_resp = MagicMock()
    good_resp.choices = [MagicMock(message=MagicMock(content='{"a": 7, "b": "hi"}'))]
    good_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)

    mock_sdk = MagicMock()
    mock_sdk.chat.completions.create.side_effect = [_rate_limit_error(), good_resp]

    client = GrokClient(model="grok-4", sdk=mock_sdk)
    parsed, _ = client.structured_complete(system="extract", user="data", schema=Toy)

    assert parsed == Toy(a=7, b="hi")
    assert mock_sdk.chat.completions.create.call_count == 2
    assert len(sleeps) == 1
```

- [ ] **Step 3: Run the test and confirm it fails**

```bash
cd backend && pytest tests/test_grok_client.py::test_retries_succeed_after_429 -v
```

Expected: FAIL — `RateLimitError` propagates because retry isn't implemented yet (or `time`/`random` modules aren't even imported in `grok_client.py`).

- [ ] **Step 4: Implement the retry loop**

In `backend/app/llm/grok_client.py`:

Add to the imports at the top:

```python
import random
import time

from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError
```

Add a private method on `GrokClient` (place it above `_call_once`):

```python
    def _retry_delay(self, attempt: int, exc: Exception) -> float:
        """Exponential backoff with jitter, capped. Honors Retry-After on 429."""
        if isinstance(exc, RateLimitError) and exc.response is not None:
            retry_after = exc.response.headers.get("retry-after")
            if retry_after is not None:
                try:
                    return min(float(retry_after), _MAX_DELAY_S)
                except ValueError:
                    pass
        base = min(_BASE_DELAY_S * (2 ** (attempt - 1)), _MAX_DELAY_S)
        jitter = random.uniform(-base * 0.25, base * 0.25)
        return max(0.0, base + jitter)

    def _call_with_retry(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: type[T],
        max_retries: int,
    ) -> tuple[T, CallMeta]:
        """grok-4 retry loop. Retries RateLimitError; raises LLMUnavailableError on exhaustion."""
        last_exc: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                return self._call_once(
                    model=model,
                    system=system,
                    user=user,
                    schema=schema,
                    max_retries=max_retries,
                )
            except RateLimitError as e:
                last_exc = e
                if attempt == _MAX_ATTEMPTS:
                    break
                time.sleep(self._retry_delay(attempt, e))
        raise LLMUnavailableError() from last_exc
```

Update `structured_complete` to call `_call_with_retry` instead of `_call_once` directly:

```python
    def structured_complete(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        max_retries: int = 1,
    ) -> tuple[T, CallMeta]:
        """LLM call with HTTP retry on transient errors, then Pydantic validation retry."""
        return self._call_with_retry(
            model=self.model,
            system=system,
            user=user,
            schema=schema,
            max_retries=max_retries,
        )
```

- [ ] **Step 5: Run the test and confirm it passes**

```bash
cd backend && pytest tests/test_grok_client.py::test_retries_succeed_after_429 -v
```

Expected: PASS. Also run the full file to confirm no regression:

```bash
cd backend && pytest tests/test_grok_client.py -v
```

Expected: 4/4 pass.

- [ ] **Step 6: mypy check**

```bash
cd backend && mypy app
```

Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add backend/app/llm/grok_client.py backend/tests/test_grok_client.py
git commit -m "feat(grok): retry on 429 with exponential backoff + jitter"
```

---

## Task 5: Honor `Retry-After` header

**Files:**
- Modify: `backend/tests/test_grok_client.py`

The implementation in Task 4 already reads `Retry-After`. This task locks the behavior with a test.

- [ ] **Step 1: Write the failing test `test_retries_honor_retry_after_header`**

Append to `backend/tests/test_grok_client.py`:

```python
def test_retries_honor_retry_after_header(monkeypatch):
    """RateLimitError with Retry-After: 2 should cause sleep of ~2s (not exponential backoff)."""
    sleeps: list[float] = []
    monkeypatch.setattr("app.llm.grok_client.time.sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr("app.llm.grok_client.random.uniform", lambda a, b: 999.0)  # would dominate if used

    good_resp = MagicMock()
    good_resp.choices = [MagicMock(message=MagicMock(content='{"a": 1, "b": "x"}'))]
    good_resp.usage = MagicMock(prompt_tokens=1, completion_tokens=1)

    mock_sdk = MagicMock()
    mock_sdk.chat.completions.create.side_effect = [_rate_limit_error(retry_after="2"), good_resp]

    client = GrokClient(model="grok-4", sdk=mock_sdk)
    client.structured_complete(system="s", user="u", schema=Toy)

    assert sleeps == [2.0]  # exact header value used, jitter NOT applied
```

- [ ] **Step 2: Run the test**

```bash
cd backend && pytest tests/test_grok_client.py::test_retries_honor_retry_after_header -v
```

Expected: PASS — `_retry_delay` from Task 4 already returns the header value verbatim (capped at `_MAX_DELAY_S`).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_grok_client.py
git commit -m "test(grok): lock Retry-After header behavior"
```

---

## Task 6: Extend retry to connection/timeout/5xx errors

**Files:**
- Modify: `backend/app/llm/grok_client.py`
- Modify: `backend/tests/test_grok_client.py`

- [ ] **Step 1: Write the failing test `test_503_retries_then_raises_unavailable`**

Append to `backend/tests/test_grok_client.py`:

```python
def _api_status_error(status_code: int) -> "APIStatusError":
    from openai import APIStatusError
    response = httpx.Response(
        status_code,
        request=httpx.Request("POST", "https://api.x.ai/v1/chat/completions"),
    )
    return APIStatusError(message=f"http {status_code}", response=response, body=None)


def test_503_retries_then_raises_unavailable(monkeypatch):
    """All 3 grok-4 attempts return 503. Fallback disabled. Assert LLMUnavailableError."""
    monkeypatch.setattr("app.llm.grok_client.time.sleep", lambda s: None)
    monkeypatch.setattr("app.llm.grok_client.random.uniform", lambda a, b: 0.0)

    mock_sdk = MagicMock()
    mock_sdk.chat.completions.create.side_effect = [_api_status_error(503)] * 3

    from app.llm.grok_client import LLMUnavailableError
    client = GrokClient(model="grok-4", fallback_model="", sdk=mock_sdk)
    with pytest.raises(LLMUnavailableError):
        client.structured_complete(system="s", user="u", schema=Toy)
    assert mock_sdk.chat.completions.create.call_count == 3
```

Also `import pytest` if not already at the top of the file (it's currently only imported inside `test_grok_client_raises_when_retries_exhausted` — move it to module level).

- [ ] **Step 2: Run the test and confirm it fails**

```bash
cd backend && pytest tests/test_grok_client.py::test_503_retries_then_raises_unavailable -v
```

Expected: FAIL — current `_call_with_retry` only catches `RateLimitError`.

- [ ] **Step 3: Broaden the retryable exception set**

In `backend/app/llm/grok_client.py`, replace the `except RateLimitError as e:` block in `_call_with_retry` with:

```python
            except (
                RateLimitError,
                APIConnectionError,
                APITimeoutError,
            ) as e:
                last_exc = e
                if attempt == _MAX_ATTEMPTS:
                    break
                time.sleep(self._retry_delay(attempt, e))
            except APIStatusError as e:
                if e.status_code < 500:
                    raise
                last_exc = e
                if attempt == _MAX_ATTEMPTS:
                    break
                time.sleep(self._retry_delay(attempt, e))
```

- [ ] **Step 4: Run the test and confirm it passes**

```bash
cd backend && pytest tests/test_grok_client.py::test_503_retries_then_raises_unavailable -v
```

Expected: PASS. Full file:

```bash
cd backend && pytest tests/test_grok_client.py -v
```

Expected: 6/6 pass (3 original + 3 new).

- [ ] **Step 5: mypy check**

```bash
cd backend && mypy app
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/llm/grok_client.py backend/tests/test_grok_client.py
git commit -m "feat(grok): retry on 5xx, connection, and timeout errors"
```

---

## Task 7: Map non-retryable errors to `LLMConfigurationError`

**Files:**
- Modify: `backend/app/llm/grok_client.py`
- Modify: `backend/tests/test_grok_client.py`

- [ ] **Step 1: Write failing tests for auth and bad-request handling**

Append to `backend/tests/test_grok_client.py`:

```python
def _api_status_subclass_error(cls_name: str, status_code: int) -> Exception:
    """Construct a real openai APIStatusError subclass for the given HTTP status."""
    import openai
    cls = getattr(openai, cls_name)
    response = httpx.Response(
        status_code,
        request=httpx.Request("POST", "https://api.x.ai/v1/chat/completions"),
    )
    return cls(message=f"http {status_code}", response=response, body=None)


def test_auth_error_raises_configuration_error_immediately(monkeypatch):
    """401 -> LLMConfigurationError immediately, no retry, no fallback."""
    monkeypatch.setattr("app.llm.grok_client.time.sleep", lambda s: None)

    mock_sdk = MagicMock()
    mock_sdk.chat.completions.create.side_effect = _api_status_subclass_error(
        "AuthenticationError", 401
    )

    from app.llm.grok_client import LLMConfigurationError
    client = GrokClient(model="grok-4", fallback_model="grok-3", sdk=mock_sdk)
    with pytest.raises(LLMConfigurationError) as exc_info:
        client.structured_complete(system="s", user="u", schema=Toy)

    assert "key" in exc_info.value.user_message.lower()
    assert mock_sdk.chat.completions.create.call_count == 1  # no retry, no fallback


def test_bad_request_re_raised_as_is(monkeypatch):
    """400 -> BadRequestError bubbles up unchanged. No retry."""
    from openai import BadRequestError
    monkeypatch.setattr("app.llm.grok_client.time.sleep", lambda s: None)

    mock_sdk = MagicMock()
    mock_sdk.chat.completions.create.side_effect = _api_status_subclass_error(
        "BadRequestError", 400
    )

    client = GrokClient(model="grok-4", fallback_model="grok-3", sdk=mock_sdk)
    with pytest.raises(BadRequestError):
        client.structured_complete(system="s", user="u", schema=Toy)
    assert mock_sdk.chat.completions.create.call_count == 1
```

- [ ] **Step 2: Run tests and confirm failure**

```bash
cd backend && pytest tests/test_grok_client.py::test_auth_error_raises_configuration_error_immediately tests/test_grok_client.py::test_bad_request_re_raised_as_is -v
```

Expected: FAIL — currently `AuthenticationError` and `BadRequestError` both bubble up unchanged (the auth test fails because it expects `LLMConfigurationError`, not `AuthenticationError`).

- [ ] **Step 3: Add the non-retryable mapping in `_call_with_retry`**

In `backend/app/llm/grok_client.py`, update the imports:

```python
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)
```

Modify `_call_with_retry` to catch the non-retryable subclasses first (place these `except` clauses **before** the generic `APIStatusError` clause, since these are subclasses of it):

```python
    def _call_with_retry(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: type[T],
        max_retries: int,
    ) -> tuple[T, CallMeta]:
        """grok-4 retry loop. Retries transient errors; raises typed exceptions otherwise."""
        last_exc: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                return self._call_once(
                    model=model,
                    system=system,
                    user=user,
                    schema=schema,
                    max_retries=max_retries,
                )
            except AuthenticationError as e:
                raise LLMConfigurationError("Grok API key invalid or missing.") from e
            except PermissionDeniedError as e:
                raise LLMConfigurationError("Grok API access denied.") from e
            except NotFoundError as e:
                raise LLMConfigurationError("Configured Grok model not found.") from e
            except (
                RateLimitError,
                APIConnectionError,
                APITimeoutError,
            ) as e:
                last_exc = e
                if attempt == _MAX_ATTEMPTS:
                    break
                time.sleep(self._retry_delay(attempt, e))
            except APIStatusError as e:
                if e.status_code < 500:
                    raise  # 400 BadRequest and any other unmapped 4xx — re-raise as-is
                last_exc = e
                if attempt == _MAX_ATTEMPTS:
                    break
                time.sleep(self._retry_delay(attempt, e))
        raise LLMUnavailableError() from last_exc
```

- [ ] **Step 4: Run tests and confirm pass**

```bash
cd backend && pytest tests/test_grok_client.py -v
```

Expected: 8/8 pass.

- [ ] **Step 5: mypy check**

```bash
cd backend && mypy app
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/llm/grok_client.py backend/tests/test_grok_client.py
git commit -m "feat(grok): map auth/permission/not-found to LLMConfigurationError"
```

---

## Task 8: Add fallback to grok-3 with today's date prefix

**Files:**
- Modify: `backend/app/llm/grok_client.py`
- Modify: `backend/tests/test_grok_client.py`

- [ ] **Step 1: Write failing test `test_falls_back_to_grok3_after_exhaustion`**

Append to `backend/tests/test_grok_client.py`:

```python
def test_falls_back_to_grok3_after_exhaustion(monkeypatch):
    """3 RateLimitError on grok-4, then grok-3 succeeds. Assert 4th call uses grok-3 + date prefix."""
    monkeypatch.setattr("app.llm.grok_client.time.sleep", lambda s: None)
    monkeypatch.setattr("app.llm.grok_client.random.uniform", lambda a, b: 0.0)

    good_resp = MagicMock()
    good_resp.choices = [MagicMock(message=MagicMock(content='{"a": 9, "b": "ok"}'))]
    good_resp.usage = MagicMock(prompt_tokens=3, completion_tokens=2)

    mock_sdk = MagicMock()
    mock_sdk.chat.completions.create.side_effect = [
        _rate_limit_error(),
        _rate_limit_error(),
        _rate_limit_error(),
        good_resp,
    ]

    client = GrokClient(model="grok-4", fallback_model="grok-3", sdk=mock_sdk)
    parsed, meta = client.structured_complete(
        system="extract things", user="data", schema=Toy,
    )

    assert parsed == Toy(a=9, b="ok")
    assert mock_sdk.chat.completions.create.call_count == 4
    assert meta.model == "grok-3"

    fallback_call = mock_sdk.chat.completions.create.call_args_list[3]
    assert fallback_call.kwargs["model"] == "grok-3"
    system_msg = fallback_call.kwargs["messages"][0]["content"]
    assert system_msg.startswith("Today's date is ")
    assert "extract things" in system_msg
```

- [ ] **Step 2: Run test and confirm failure**

```bash
cd backend && pytest tests/test_grok_client.py::test_falls_back_to_grok3_after_exhaustion -v
```

Expected: FAIL — currently `LLMUnavailableError` is raised after grok-4 exhaustion; no fallback.

- [ ] **Step 3: Implement fallback in `structured_complete`**

In `backend/app/llm/grok_client.py`, add `from datetime import date` to the imports.

Replace `structured_complete` with the fallback-aware version:

```python
    def structured_complete(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        max_retries: int = 1,
    ) -> tuple[T, CallMeta]:
        """LLM call with retry on grok-4, then optional single fallback to grok-3."""
        try:
            return self._call_with_retry(
                model=self.model,
                system=system,
                user=user,
                schema=schema,
                max_retries=max_retries,
            )
        except LLMUnavailableError:
            if not self.fallback_model:
                raise
            prefixed_system = f"Today's date is {date.today().isoformat()}.\n\n{system}"
            return self._call_once(
                model=self.fallback_model,
                system=prefixed_system,
                user=user,
                schema=schema,
                max_retries=max_retries,
            )
```

Note: the fallback uses `_call_once`, **not** `_call_with_retry`, per the spec (single attempt on grok-3). If the fallback raises any transient HTTP error, it propagates raw. We translate that on the next task.

- [ ] **Step 4: Wrap fallback transient errors as `LLMUnavailableError` and configuration errors as `LLMConfigurationError`**

Update the fallback path in `structured_complete`:

```python
        except LLMUnavailableError:
            if not self.fallback_model:
                raise
            prefixed_system = f"Today's date is {date.today().isoformat()}.\n\n{system}"
            try:
                return self._call_once(
                    model=self.fallback_model,
                    system=prefixed_system,
                    user=user,
                    schema=schema,
                    max_retries=max_retries,
                )
            except AuthenticationError as e:
                raise LLMConfigurationError("Grok API key invalid or missing.") from e
            except PermissionDeniedError as e:
                raise LLMConfigurationError("Grok API access denied.") from e
            except NotFoundError as e:
                raise LLMConfigurationError(
                    "Configured Grok fallback model not found."
                ) from e
            except (RateLimitError, APIConnectionError, APITimeoutError) as e:
                raise LLMUnavailableError() from e
            except APIStatusError as e:
                if e.status_code < 500:
                    raise
                raise LLMUnavailableError() from e
```

- [ ] **Step 5: Run the test and confirm it passes**

```bash
cd backend && pytest tests/test_grok_client.py::test_falls_back_to_grok3_after_exhaustion -v
```

Expected: PASS. Full file:

```bash
cd backend && pytest tests/test_grok_client.py -v
```

Expected: 9/9 pass.

- [ ] **Step 6: mypy check**

```bash
cd backend && mypy app
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/llm/grok_client.py backend/tests/test_grok_client.py
git commit -m "feat(grok): fallback to grok-3 with today's-date prefix after retries"
```

---

## Task 9: Disable fallback when `fallback_model` is empty

**Files:**
- Modify: `backend/tests/test_grok_client.py`

The disable path already exists in Task 8's `if not self.fallback_model: raise`. This task locks it with a test.

- [ ] **Step 1: Write the test `test_fallback_disabled_raises_when_empty`**

Append to `backend/tests/test_grok_client.py`:

```python
def test_fallback_disabled_raises_when_empty(monkeypatch):
    """Empty fallback_model means no grok-3 attempt; LLMUnavailableError after 3 grok-4 fails."""
    monkeypatch.setattr("app.llm.grok_client.time.sleep", lambda s: None)
    monkeypatch.setattr("app.llm.grok_client.random.uniform", lambda a, b: 0.0)

    mock_sdk = MagicMock()
    mock_sdk.chat.completions.create.side_effect = [_rate_limit_error()] * 3

    from app.llm.grok_client import LLMUnavailableError
    client = GrokClient(model="grok-4", fallback_model="", sdk=mock_sdk)
    with pytest.raises(LLMUnavailableError):
        client.structured_complete(system="s", user="u", schema=Toy)
    assert mock_sdk.chat.completions.create.call_count == 3  # 3 grok-4 only, no grok-3
```

- [ ] **Step 2: Run the test**

```bash
cd backend && pytest tests/test_grok_client.py::test_fallback_disabled_raises_when_empty -v
```

Expected: PASS — no implementation change needed.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_grok_client.py
git commit -m "test(grok): lock fallback-disabled behavior when xai_fallback_model is empty"
```

---

## Task 10: Lock the total-attempt budget

**Files:**
- Modify: `backend/tests/test_grok_client.py`

- [ ] **Step 1: Write the test `test_total_attempt_budget_is_bounded`**

Append to `backend/tests/test_grok_client.py`:

```python
def test_total_attempt_budget_is_bounded(monkeypatch):
    """All 4 calls (3 grok-4 + 1 grok-3) raise 429. Assert exactly 4 SDK calls, LLMUnavailableError."""
    monkeypatch.setattr("app.llm.grok_client.time.sleep", lambda s: None)
    monkeypatch.setattr("app.llm.grok_client.random.uniform", lambda a, b: 0.0)

    mock_sdk = MagicMock()
    mock_sdk.chat.completions.create.side_effect = [_rate_limit_error()] * 10  # plenty

    from app.llm.grok_client import LLMUnavailableError
    client = GrokClient(model="grok-4", fallback_model="grok-3", sdk=mock_sdk)
    with pytest.raises(LLMUnavailableError):
        client.structured_complete(system="s", user="u", schema=Toy)
    assert mock_sdk.chat.completions.create.call_count == 4
```

- [ ] **Step 2: Run the test**

```bash
cd backend && pytest tests/test_grok_client.py::test_total_attempt_budget_is_bounded -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_grok_client.py
git commit -m "test(grok): bound total SDK attempts to 4 (3 grok-4 + 1 grok-3 fallback)"
```

---

## Task 11: Regression — validation retry behavior unchanged

**Files:**
- Modify: `backend/tests/test_grok_client.py`

- [ ] **Step 1: Write the regression test**

Append to `backend/tests/test_grok_client.py`:

```python
def test_validation_retry_still_works_with_fallback_enabled(monkeypatch):
    """Pydantic validation retry must not trigger fallback. One invalid-shape then valid on grok-4."""
    monkeypatch.setattr("app.llm.grok_client.time.sleep", lambda s: None)

    bad_resp = MagicMock()
    bad_resp.choices = [MagicMock(message=MagicMock(content='{"a": "not_an_int", "b": "hi"}'))]
    bad_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
    good_resp = MagicMock()
    good_resp.choices = [MagicMock(message=MagicMock(content='{"a": 7, "b": "hi"}'))]
    good_resp.usage = MagicMock(prompt_tokens=12, completion_tokens=6)

    mock_sdk = MagicMock()
    mock_sdk.chat.completions.create.side_effect = [bad_resp, good_resp]

    client = GrokClient(model="grok-4", fallback_model="grok-3", sdk=mock_sdk)
    parsed, meta = client.structured_complete(
        system="extract", user="data", schema=Toy, max_retries=1,
    )

    assert parsed == Toy(a=7, b="hi")
    assert mock_sdk.chat.completions.create.call_count == 2
    assert meta.model == "grok-4"  # NOT fallback
    # The retry was a validation retry (extra user message appended), not a fallback.
    second_call_messages = mock_sdk.chat.completions.create.call_args_list[1].kwargs["messages"]
    assert "failed validation" in second_call_messages[-1]["content"]
```

- [ ] **Step 2: Run the test**

```bash
cd backend && pytest tests/test_grok_client.py::test_validation_retry_still_works_with_fallback_enabled -v
```

Expected: PASS — the validation-retry loop lives in `_call_once`, separate from the fallback path.

- [ ] **Step 3: Run the entire file once more**

```bash
cd backend && pytest tests/test_grok_client.py -v
```

Expected: all tests pass (3 original + 9 new = 12 total).

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_grok_client.py
git commit -m "test(grok): regression guard for validation-retry independence from fallback"
```

---

## Task 12: Wire `fallback_model` through `create_app`

**Files:**
- Modify: `backend/app/api/app.py`

- [ ] **Step 1: Pass `fallback_model` when constructing `GrokClient`**

In `backend/app/api/app.py`, update the `GrokClient(...)` call inside `create_app` to include the new arg:

```python
        llm = GrokClient(
            api_key=api_key,
            base_url=settings.xai_base_url,
            model=settings.xai_model,
            fallback_model=settings.xai_fallback_model,
        )
```

The complete updated block (lines 30-33 of the original file):

```python
        api_key = settings.xai_api_key or "not-configured"
        llm = GrokClient(
            api_key=api_key,
            base_url=settings.xai_base_url,
            model=settings.xai_model,
            fallback_model=settings.xai_fallback_model,
        )
```

- [ ] **Step 2: Verify mypy and existing tests still pass**

```bash
cd backend && mypy app && pytest -x -q
```

Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/app.py
git commit -m "feat(api): wire xai_fallback_model from settings into GrokClient"
```

---

## Task 13: Map typed exceptions in `_run_graph` to clean `state.error`

**Files:**
- Modify: `backend/app/api/routes.py`
- Modify: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing integration test**

Append to `backend/tests/test_api.py`:

```python
def test_run_graph_surfaces_clean_message_on_llm_unavailable(tmp_path: Path):
    """When the graph raises LLMUnavailableError, run.state.error is the clean message."""
    from app.llm.grok_client import LLMUnavailableError

    db = tmp_path / "api.db"
    init_db(db, seed_path=SEED, reset=True)

    fake_llm = MagicMock()
    fake_llm.structured_complete.side_effect = LLMUnavailableError()
    app = create_app(llm=fake_llm, db_path=db, log_dir=tmp_path / "logs")
    client = TestClient(app)

    with INVOICE_1001.open("rb") as f:
        resp = client.post("/api/runs", files={"file": (INVOICE_1001.name, f, "text/plain")})
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]

    # Poll briefly until the run completes; in-test runs are fast.
    import time as _time
    for _ in range(50):
        run_resp = client.get(f"/api/runs/{run_id}")
        body = run_resp.json()
        if body.get("error") is not None:
            break
        _time.sleep(0.02)

    assert body["error"] == "Grok is temporarily at capacity. Please retry in a moment."
    assert "graph crashed" not in body["error"]
```

- [ ] **Step 2: Run the test and confirm failure**

```bash
cd backend && pytest tests/test_api.py::test_run_graph_surfaces_clean_message_on_llm_unavailable -v
```

Expected: FAIL — current `_run_graph` catches the exception under the generic `Exception` branch and prepends `"graph crashed: "`.

- [ ] **Step 3: Add typed exception branches in `_run_graph`**

In `backend/app/api/routes.py`, update the imports at the top of the file:

```python
from app.llm.grok_client import LLMConfigurationError, LLMUnavailableError
```

Modify `_run_graph` (currently `routes.py:30-45`):

```python
    async def _run_graph(run_id: str) -> None:
        run = registry.get(run_id)
        if run is None:
            return
        loop = asyncio.get_event_loop()
        try:
            final = await loop.run_in_executor(None, graph.invoke, run.state)
            # LangGraph returns the final state as a dict; sync it back so
            # /api/runs summaries reflect the actual outcome instead of "running".
            run.state = InvoiceState.model_validate(final)
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

- [ ] **Step 4: Run the test and confirm it passes**

```bash
cd backend && pytest tests/test_api.py::test_run_graph_surfaces_clean_message_on_llm_unavailable -v
```

Expected: PASS.

- [ ] **Step 5: Full suite + mypy + ruff**

```bash
cd backend && mypy app && ruff check . && pytest -x -q
```

Expected: clean across the board.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes.py backend/tests/test_api.py
git commit -m "feat(api): map LLMUnavailableError / LLMConfigurationError to clean state.error"
```

---

## Task 14: Manual smoke + tasks/lessons update

**Files:**
- Modify (if exists, otherwise create): `tasks/todo.md` review section
- Modify (if applicable): `tasks/lessons.md`

- [ ] **Step 1: Manual smoke against a local backend**

If a local dev backend can be started, run it and trigger an invoice flow with a temporarily-broken API key to see the friendlier error in the UI:

```bash
# In one terminal:
cd backend && uvicorn app.api.app:app --reload --port 8000

# In another:
cd frontend && npm run dev
```

Set `XAI_API_KEY="invalid"` in `.env`, upload a sample invoice via the UI, and confirm the case-file action card shows
"Could not process — Grok API key invalid or missing." (rather than an OpenAI traceback).

If a smoke run is not possible (no local secrets, no network), skip — the integration test in Task 13 is the primary safety net.

- [ ] **Step 2: Add a review section to `tasks/todo.md`**

Per `CLAUDE.md` workflow ("Add a review section to tasks/todo.md when done"), append a short note:

```markdown
## 2026-05-13 — Grok client resilience

- Added retry + grok-3 fallback + typed exceptions in `GrokClient`
- API layer maps typed exceptions to clean strings (no "graph crashed:" prefix)
- Spec: `docs/superpowers/specs/2026-05-13-grok-resilience-design.md`
- Plan: `docs/superpowers/plans/2026-05-13-grok-resilience.md`
- 9 new unit tests in `test_grok_client.py`, 1 new integration test in `test_api.py`
```

If `tasks/todo.md` does not exist, create it with just this section.

- [ ] **Step 3: Final commit**

```bash
git add tasks/todo.md
git commit -m "docs(tasks): grok resilience completion notes"
```

---

## Self-Review

After all tasks complete:

1. **Spec coverage check:** every section of `docs/superpowers/specs/2026-05-13-grok-resilience-design.md` maps to one or more tasks here. Specifically:
   - Typed exceptions → Task 2
   - Retry policy + Retry-After → Tasks 4, 5
   - 5xx/connection/timeout retry → Task 6
   - Error taxonomy (auth/permission/not-found/bad-request) → Task 7
   - Fallback to grok-3 with date prefix → Task 8
   - Config (`xai_fallback_model`) → Tasks 1, 12
   - `_run_graph` error mapping → Task 13
   - All 10 tests from the spec → Tasks 4–13 (note: spec test 1 → Task 4, test 2 → Task 5, test 5 → Task 7, test 6 → Task 7, test 3 → Task 8, test 4 → Task 9, test 7 → covered by Task 6's 503 test + Task 8's pattern, test 8 → Task 10, test 9 → Task 11, test 10 → Task 13)

2. **Type consistency check:** `LLMUnavailableError.user_message` (class attribute, default) and `LLMConfigurationError.user_message` (instance attribute, init-set) are deliberately different — see Task 2. Both are read uniformly via `e.user_message` in Task 13. `fallback_model` parameter name is consistent across Tasks 3, 8, 12.

3. **No placeholders:** every step contains the exact code/command/expected output.

---

## Execution notes

- All retry/fallback delays are mocked in tests (`time.sleep` patched to a no-op or recorder, `random.uniform` patched to a deterministic value). The test suite stays fast.
- After Task 7, the order of `except` clauses in `_call_with_retry` matters: subclass exceptions (`AuthenticationError`, `PermissionDeniedError`, `NotFoundError`) must come before the generic `APIStatusError` because they inherit from it.
- `_call_once` deliberately uses `_call_once` (not `_call_with_retry`) on the fallback path — fallback is one attempt by design.
- The fallback path wraps its own SDK errors so callers always see typed exceptions, never raw OpenAI types.
