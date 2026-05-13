from __future__ import annotations

import json
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable

from app.graph.state import ToolCall

Dispatch = Callable[[str, dict[str, object]], dict[str, object]]


@dataclass
class ToolLoopResult:
    final_content: str
    tool_calls: list[ToolCall]
    tokens_in: int
    tokens_out: int
    latency_ms: int
    model: str


def run_tool_loop(
    *, sdk: Any, model: str, system: str, user: str,
    tools_schema: list[dict[str, object]], dispatch: Dispatch,
    max_iterations: int = 4, timeout: float = 30.0,
) -> ToolLoopResult:
    """Run a chat completion that may invoke tools, looping until a content reply.

    Raises RuntimeError if max_iterations is exceeded without a final content reply.
    """
    messages: list[dict[str, object]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    captured: list[ToolCall] = []
    tokens_in = 0
    tokens_out = 0
    t0 = perf_counter()

    for _ in range(max_iterations + 1):
        kwargs: dict[str, object] = {
            "model": model,
            "messages": messages,
            "timeout": timeout,
        }
        if tools_schema:
            kwargs["tools"] = tools_schema
            kwargs["tool_choice"] = "auto"
        resp = sdk.chat.completions.create(**kwargs)
        usage = getattr(resp, "usage", None)
        if usage is not None:
            tokens_in += getattr(usage, "prompt_tokens", 0) or 0
            tokens_out += getattr(usage, "completion_tokens", 0) or 0
        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []
        if not tool_calls:
            return ToolLoopResult(
                final_content=msg.content or "",
                tool_calls=captured,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                latency_ms=int((perf_counter() - t0) * 1000),
                model=model,
            )
        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in tool_calls
            ],
        })
        for tc in tool_calls:
            args = json.loads(tc.function.arguments or "{}")
            call_t0 = perf_counter()
            result = dispatch(tc.function.name, args)
            captured.append(ToolCall(
                tool=tc.function.name,  # type: ignore[arg-type]  # str from SDK; Pydantic validates Literal at runtime
                arguments=args,
                result=result,
                latency_ms=int((perf_counter() - call_t0) * 1000),
            ))
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, default=str),
            })

    raise RuntimeError(f"tool loop exceeded max_iterations={max_iterations}")
