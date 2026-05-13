from __future__ import annotations
import json
from dataclasses import dataclass
from time import perf_counter
from typing import Type, TypeVar
from openai import OpenAI
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


@dataclass
class CallMeta:
    tokens_in: int
    tokens_out: int
    latency_ms: int
    model: str


class GrokClient:
    def __init__(self, *, api_key: str = "", base_url: str = "https://api.x.ai/v1",
                 model: str = "grok-4", sdk: OpenAI | None = None) -> None:
        self.model = model
        self.sdk = sdk or OpenAI(api_key=api_key, base_url=base_url)

    def structured_complete(
        self, *, system: str, user: str, schema: Type[T], max_retries: int = 1,
    ) -> tuple[T, CallMeta]:
        """One LLM call with one retry on Pydantic validation failure."""
        attempts = 0
        last_error: str | None = None
        while True:
            attempts += 1
            t0 = perf_counter()
            messages = [
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
            resp = self.sdk.chat.completions.create(
                model=self.model,
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
                    model=self.model,
                )
                return parsed, meta
            except (ValidationError, json.JSONDecodeError) as e:
                last_error = str(e)
                if attempts > max_retries:
                    raise
