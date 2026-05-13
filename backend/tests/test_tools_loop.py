from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.llm.tools_loop import ToolLoopResult, run_tool_loop


@dataclass
class _FakeMessage:
    content: str | None
    tool_calls: list[Any] | None = None


@dataclass
class _FakeChoice:
    message: _FakeMessage


@dataclass
class _FakeUsage:
    prompt_tokens: int = 10
    completion_tokens: int = 5


@dataclass
class _FakeResp:
    choices: list[_FakeChoice]
    usage: _FakeUsage = field(default_factory=_FakeUsage)


class _FakeToolCall:
    def __init__(self, call_id: str, name: str, args: dict):
        self.id = call_id
        self.type = "function"
        self.function = type("F", (), {"name": name, "arguments": json.dumps(args)})()


class _FakeSDK:
    def __init__(self, scripted: list[_FakeResp]):
        self._scripted = list(scripted)
        self.calls: list[dict] = []
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._scripted.pop(0)


def _dispatch(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "lookup_inventory":
        return {"found": True, "item": args["item"], "stock": 7}
    raise ValueError(name)


def test_loop_returns_immediately_when_no_tool_calls():
    sdk = _FakeSDK([_FakeResp([_FakeChoice(_FakeMessage(content='{"ok": true}'))])])
    result = run_tool_loop(
        sdk=sdk, model="grok-x", system="s", user="u",
        tools_schema=[], dispatch=_dispatch, max_iterations=3,
    )
    assert isinstance(result, ToolLoopResult)
    assert result.final_content == '{"ok": true}'
    assert result.tool_calls == []


def test_loop_executes_one_tool_call_then_returns():
    sdk = _FakeSDK([
        _FakeResp([_FakeChoice(_FakeMessage(
            content=None,
            tool_calls=[_FakeToolCall("c1", "lookup_inventory", {"item": "WidgetA"})],
        ))]),
        _FakeResp([_FakeChoice(_FakeMessage(content='{"done": true}'))]),
    ])
    result = run_tool_loop(
        sdk=sdk, model="grok-x", system="s", user="u",
        tools_schema=[{"type": "function"}], dispatch=_dispatch, max_iterations=3,
    )
    assert result.final_content == '{"done": true}'
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].tool == "lookup_inventory"
    assert result.tool_calls[0].result["stock"] == 7


def test_loop_respects_max_iterations():
    looping = _FakeResp([_FakeChoice(_FakeMessage(
        content=None,
        tool_calls=[_FakeToolCall("c1", "lookup_inventory", {"item": "X"})],
    ))])
    sdk = _FakeSDK([looping, looping, looping, looping, looping])
    with pytest.raises(RuntimeError, match="max_iterations"):
        run_tool_loop(
            sdk=sdk, model="grok-x", system="s", user="u",
            tools_schema=[{"type": "function"}], dispatch=_dispatch, max_iterations=2,
        )
