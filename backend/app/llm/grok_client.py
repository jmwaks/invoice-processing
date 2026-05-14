from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from time import perf_counter
from typing import TypeVar, cast

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    NotFoundError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

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


@dataclass
class CallMeta:
    tokens_in: int
    tokens_out: int
    latency_ms: int
    model: str


class GrokClient:
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
        return cast(float, max(0.0, base + jitter))

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
