# Approve Agent Tool-Use Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace pre-baked validation results in the approve agent with on-demand LLM tool calls so the LLM demonstrates real function-calling capability per the case spec's "Function calling / tool use" requirement.

**Architecture:** Add an "investigate" pass before propose. The investigate pass runs an OpenAI-compatible tool loop where the LLM may call `lookup_inventory`, `lookup_vendor`, or `recompute_totals` zero or more times before producing a `Proposal`. Tools share implementations with existing validate-stage code (no duplication). All tool calls are captured on `Decision.tool_calls` for the audit trail and UI timeline.

**Tech Stack:** OpenAI Python SDK (already used by GrokClient), xAI Grok tool calling (OpenAI-compatible), Pydantic schemas, existing FastAPI + React frontend.

---

## File Structure

**Created:**
- `backend/app/llm/tools_loop.py` — generic tool-calling loop helper used by any agent
- `backend/app/tools/llm_tools.py` — JSON schemas + dispatchers for the three exposed tools
- `backend/tests/test_llm_tools.py` — unit tests for the schema/dispatcher registry
- `backend/tests/test_tools_loop.py` — unit tests for the tool loop with a fake SDK

**Modified:**
- `backend/app/llm/grok_client.py` — add `tools_complete` method
- `backend/app/agents/approve.py` — insert investigate pass before propose
- `backend/app/graph/state.py` — add `ToolCall` model; add `tool_calls` field to `Decision`
- `backend/tests/test_approve_agent.py` — assert tool calls captured on ambiguous cases
- `frontend/src/types/state.ts` — mirror `ToolCall` and `Decision.tool_calls`
- `frontend/src/components/Timeline.tsx` — render `tool.call` events
- `frontend/src/components/CritiquePanel.tsx` — list tool calls in the audit trail

Each file has one responsibility: the loop helper knows nothing about invoices, the tools module knows nothing about LLM mechanics, the agent wires them together.

---

## Task 1: Add ToolCall model and Decision.tool_calls

**Files:**
- Modify: `backend/app/graph/state.py`
- Test: `backend/tests/test_state_models.py` (extend existing)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_state_models.py`:

```python
from app.graph.state import ToolCall, Decision, Proposal, Critique


def test_tool_call_round_trip():
    tc = ToolCall(
        tool="lookup_inventory",
        arguments={"item": "WidgetA"},
        result={"found": True, "item": "WidgetA", "stock": 15, "unit_price": 250.0},
        latency_ms=12,
    )
    dumped = tc.model_dump()
    restored = ToolCall.model_validate(dumped)
    assert restored == tc


def test_decision_defaults_tool_calls_to_empty_list():
    proposal = Proposal(outcome="approved", rationale="r", rules_applied=[], unresolved_concerns=[])
    critique = Critique(agrees=True, objections=[], missed_signals=[], rule_misapplications=[])
    decision = Decision(
        outcome="approved", rationale="r", rules_applied=[],
        initial_proposal=proposal, critique=critique, final_proposal=proposal,
    )
    assert decision.tool_calls == []
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd backend && .venv/bin/pytest tests/test_state_models.py::test_tool_call_round_trip tests/test_state_models.py::test_decision_defaults_tool_calls_to_empty_list -v
```

Expected: `ImportError: cannot import name 'ToolCall'`.

- [ ] **Step 3: Add ToolCall and extend Decision**

In `backend/app/graph/state.py`, add after the `VendorLookupResult` class and before `ValidationReport`:

```python
class ToolCall(BaseModel):
    tool: Literal["lookup_inventory", "lookup_vendor", "recompute_totals"]
    arguments: dict[str, Any]
    result: dict[str, Any]
    latency_ms: int
```

In the same file, extend `Decision`:

```python
class Decision(BaseModel):
    outcome: Literal["approved", "rejected", "needs_review"]
    rationale: str
    rules_applied: list[str]
    initial_proposal: Proposal
    critique: Critique
    final_proposal: Proposal
    tool_calls: list[ToolCall] = []
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd backend && .venv/bin/pytest tests/test_state_models.py -v
```

Expected: all tests pass (existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add backend/app/graph/state.py backend/tests/test_state_models.py
git commit -m "feat(state): add ToolCall model and Decision.tool_calls"
```

---

## Task 2: Tool registry with JSON schemas

**Files:**
- Create: `backend/app/tools/llm_tools.py`
- Create: `backend/tests/test_llm_tools.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_llm_tools.py`:

```python
from __future__ import annotations

import pytest

from app.tools.llm_tools import TOOL_SCHEMAS, dispatch_tool


def test_tool_schemas_have_required_openai_shape():
    for schema in TOOL_SCHEMAS:
        assert schema["type"] == "function"
        fn = schema["function"]
        assert "name" in fn and "description" in fn and "parameters" in fn
        assert fn["parameters"]["type"] == "object"


def test_dispatch_lookup_inventory_known(seeded_db_path):
    out = dispatch_tool(
        "lookup_inventory", {"item": "WidgetA"}, db_path=seeded_db_path,
    )
    assert out["found"] is True
    assert out["item"] == "WidgetA"
    assert out["stock"] == 15


def test_dispatch_lookup_inventory_unknown(seeded_db_path):
    out = dispatch_tool(
        "lookup_inventory", {"item": "ImaginaryThing"}, db_path=seeded_db_path,
    )
    assert out["found"] is False


def test_dispatch_lookup_vendor_known(seeded_db_path):
    out = dispatch_tool(
        "lookup_vendor", {"name": "Widgets Inc."}, db_path=seeded_db_path,
    )
    assert out["found"] is True


def test_dispatch_recompute_totals():
    out = dispatch_tool(
        "recompute_totals",
        {"line_items": [{"quantity": 2, "unit_price": 100.0}, {"quantity": 1, "unit_price": 50.0}]},
        db_path=None,
    )
    assert out["computed_subtotal"] == 250.0


def test_dispatch_unknown_tool_raises():
    with pytest.raises(ValueError):
        dispatch_tool("nope", {}, db_path=None)
```

If `seeded_db_path` fixture doesn't exist, add it to `backend/tests/conftest.py` (only if absent). Search first:

```bash
cd backend && grep -n "seeded_db_path" tests/conftest.py 2>/dev/null
```

If the fixture is not present, add to `backend/tests/conftest.py`:

```python
import pytest
from app.db.init_db import init_db


@pytest.fixture
def seeded_db_path(tmp_path):
    db = tmp_path / "inventory.db"
    init_db(db)
    return db
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd backend && .venv/bin/pytest tests/test_llm_tools.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.tools.llm_tools'`.

- [ ] **Step 3: Implement the tool registry**

Create `backend/app/tools/llm_tools.py`:

```python
from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

from app.tools.inventory_tool import inventory_lookup
from app.tools.vendor_tool import vendor_lookup

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "lookup_inventory",
            "description": (
                "Look up a single item in the inventory database. "
                "Returns whether it exists, stock on hand, and unit price."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item": {"type": "string", "description": "Exact or close item name"},
                },
                "required": ["item"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_vendor",
            "description": "Look up a vendor by name. Returns whether they are on file and their status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Vendor name as it appears on the invoice"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recompute_totals",
            "description": "Recompute subtotal from line_items as sum(quantity * unit_price). Use to verify arithmetic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "line_items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "quantity": {"type": "number"},
                                "unit_price": {"type": "number"},
                            },
                            "required": ["quantity", "unit_price"],
                        },
                    },
                },
                "required": ["line_items"],
            },
        },
    },
]


def dispatch_tool(
    name: str, arguments: dict[str, Any], *, db_path: Path | None,
) -> dict[str, Any]:
    """Run a tool by name. Raises ValueError on unknown tool."""
    if name == "lookup_inventory":
        result = inventory_lookup(arguments["item"], db_path=db_path)
        return result.model_dump()
    if name == "lookup_vendor":
        result = vendor_lookup(arguments["name"], db_path=db_path)
        return result.model_dump()
    if name == "recompute_totals":
        items = arguments.get("line_items", [])
        subtotal = sum(float(it["quantity"]) * float(it["unit_price"]) for it in items)
        return {"computed_subtotal": round(subtotal, 2), "line_count": len(items)}
    raise ValueError(f"unknown tool: {name}")


def time_dispatch(
    name: str, arguments: dict[str, Any], *, db_path: Path | None,
) -> tuple[dict[str, Any], int]:
    t0 = perf_counter()
    out = dispatch_tool(name, arguments, db_path=db_path)
    return out, int((perf_counter() - t0) * 1000)
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd backend && .venv/bin/pytest tests/test_llm_tools.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools/llm_tools.py backend/tests/test_llm_tools.py backend/tests/conftest.py
git commit -m "feat(tools): add LLM-callable tool registry for inventory/vendor/totals"
```

---

## Task 3: Tool-calling loop helper

**Files:**
- Create: `backend/app/llm/tools_loop.py`
- Create: `backend/tests/test_tools_loop.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_tools_loop.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
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
    usage: _FakeUsage = _FakeUsage()


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
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd backend && .venv/bin/pytest tests/test_tools_loop.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.llm.tools_loop'`.

- [ ] **Step 3: Implement the loop**

Create `backend/app/llm/tools_loop.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable

from app.graph.state import ToolCall

Dispatch = Callable[[str, dict[str, Any]], dict[str, Any]]


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
    tools_schema: list[dict[str, Any]], dispatch: Dispatch,
    max_iterations: int = 4, timeout: float = 30.0,
) -> ToolLoopResult:
    """Run a chat completion that may invoke tools, looping until a content reply.

    Raises RuntimeError if max_iterations exceeded without a final content reply.
    """
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    captured: list[ToolCall] = []
    tokens_in = 0
    tokens_out = 0
    t0 = perf_counter()

    for _ in range(max_iterations + 1):
        kwargs: dict[str, Any] = {
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
                tool=tc.function.name,  # type: ignore[arg-type]
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
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd backend && .venv/bin/pytest tests/test_tools_loop.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/llm/tools_loop.py backend/tests/test_tools_loop.py
git commit -m "feat(llm): add tool-calling loop helper with iteration cap"
```

---

## Task 4: Investigate pass in approve agent

**Files:**
- Modify: `backend/app/agents/approve.py`
- Modify: `backend/tests/test_approve_agent.py`

- [ ] **Step 1: Write the failing test**

First inspect what's already in the test file so the new test slots in cleanly:

```bash
cd backend && .venv/bin/pytest tests/test_approve_agent.py --collect-only -q
```

Add to `backend/tests/test_approve_agent.py` (import `ToolCall` at top if missing):

```python
from app.graph.state import ToolCall


def test_approve_captures_tool_calls_on_decision(monkeypatch, sample_state_needing_scrutiny):
    """The approve agent should propagate tool calls from the investigate pass
    onto Decision.tool_calls so they appear in the audit trail."""

    fake_tool_calls = [
        ToolCall(
            tool="lookup_inventory",
            arguments={"item": "WidgetA"},
            result={"found": True, "item": "WidgetA", "stock": 15, "unit_price": 250.0},
            latency_ms=4,
        ),
    ]

    def _fake_investigate(*, llm, emitter, context, db_path):
        return fake_tool_calls

    from app.agents import approve as approve_mod
    monkeypatch.setattr(approve_mod, "_run_investigate", _fake_investigate)

    state = run_approve_with_stubbed_llm(sample_state_needing_scrutiny)
    assert state.decision is not None
    assert len(state.decision.tool_calls) == 1
    assert state.decision.tool_calls[0].tool == "lookup_inventory"
```

If `sample_state_needing_scrutiny` and `run_approve_with_stubbed_llm` are not already in the suite, define them in `backend/tests/conftest.py` based on existing fixtures (search for an existing approve fixture pattern first):

```bash
cd backend && grep -n "run_approve\|sample_state" tests/conftest.py tests/test_approve_agent.py
```

Reuse whatever stubbing pattern the existing approve tests use. Do not invent a parallel pattern.

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd backend && .venv/bin/pytest tests/test_approve_agent.py::test_approve_captures_tool_calls_on_decision -v
```

Expected failure: `AttributeError: module 'app.agents.approve' has no attribute '_run_investigate'`.

- [ ] **Step 3: Wire the investigate pass**

In `backend/app/agents/approve.py`, add an import block at the top:

```python
from app.config import get_settings
from app.graph.state import ToolCall
from app.llm.tools_loop import run_tool_loop
from app.tools.llm_tools import TOOL_SCHEMAS, time_dispatch
```

Add the investigate system prompt below the existing `FINALIZE_SYSTEM` constant:

```python
INVESTIGATE_SYSTEM = """You are an AP investigator preparing a brief for the approver.

You have access to three tools:
- lookup_inventory(item): verify an item exists and check stock/price.
- lookup_vendor(name): verify a vendor is on file.
- recompute_totals(line_items): recompute subtotal from line items to catch arithmetic errors.

Decide which (if any) to call. Call zero tools if validation is already conclusive.
When done, return JSON: {"notes": "<one-paragraph brief for the approver>"}.
"""
```

Add the investigate function before `run_approve`:

```python
def _run_investigate(
    *, llm: GrokClient, emitter: EventEmitter, context: str, db_path: "Path",
) -> list[ToolCall]:
    emitter.emit("approve.investigate.start", node="approve")

    def _dispatch(name: str, args: dict) -> dict:
        result, _ = time_dispatch(name, args, db_path=db_path)
        emitter.emit("tool.call", node="approve", tool=name, arguments=args, result=result)
        return result

    try:
        loop_result = run_tool_loop(
            sdk=llm.sdk, model=llm.model,
            system=INVESTIGATE_SYSTEM, user=context,
            tools_schema=TOOL_SCHEMAS, dispatch=_dispatch, max_iterations=4,
        )
    except Exception as e:
        _logger.exception("approve: investigate pass failed")
        emitter.emit("approve.investigate.complete", node="approve", output={"error": str(e)})
        return []

    emitter.emit(
        "approve.investigate.complete", node="approve",
        output={"tool_call_count": len(loop_result.tool_calls)},
    )
    emitter.emit(
        "llm.call", node="approve", sub="investigate",
        tokens_in=loop_result.tokens_in, tokens_out=loop_result.tokens_out,
        latency_ms=loop_result.latency_ms, model=loop_result.model,
        prompt_chars=len(context), response_chars=len(loop_result.final_content),
    )
    return loop_result.tool_calls
```

Add `Path` import at top of file if not present:

```python
from pathlib import Path
```

Modify `run_approve` to call investigate before propose and to attach the tool calls to `Decision`. Replace the existing `run_approve` body so the relevant lines look like:

```python
def run_approve(state: InvoiceState, *, llm: GrokClient, emitter: EventEmitter) -> InvoiceState:
    emitter.emit("node.start", node="approve")
    evaluation = evaluate_rules(state)
    emitter.emit("approve.rules_evaluated", node="approve", evaluation={
        "hard_blocks": evaluation.hard_blocks,
        "auto_approve": evaluation.auto_approve,
        "scrutiny": evaluation.scrutiny,
        "summary": evaluation.summary,
    })

    context = _context_block(state, evaluation)
    raw_text = state.invoice.raw_text if state.invoice else None
    db_path = get_settings().invoice_processing_db_path

    tool_calls: list[ToolCall] = []
    if not evaluation.auto_approve and not evaluation.hard_blocks:
        tool_calls = _run_investigate(llm=llm, emitter=emitter, context=context, db_path=db_path)
        if tool_calls:
            context = context + "\n\nInvestigation tool results:\n" + json.dumps(
                [tc.model_dump() for tc in tool_calls], default=str, indent=2,
            )

    proposal, _ = _run_propose(llm, emitter, context)
    critique, forced_review = _run_critique(llm, emitter, context, proposal, raw_text)
    final_proposal = _run_finalize(llm, emitter, context, proposal, critique)

    outcome = final_proposal.outcome
    rules_applied = list(final_proposal.rules_applied)
    rationale = final_proposal.rationale

    if evaluation.hard_blocks:
        outcome = "rejected"
        rules_applied = [f"hard_block:{kind}" for kind in evaluation.hard_blocks] + rules_applied
        rationale = (
            f"Hard-block rules forced rejection: {', '.join(evaluation.hard_blocks)}. "
            f"Model rationale: {rationale}"
        )

    if forced_review and outcome == "approved":
        outcome = "needs_review"
        rationale = "Critique pass failed — escalated to needs_review. " + rationale

    state.decision = Decision(
        outcome=outcome, rationale=rationale, rules_applied=rules_applied,
        initial_proposal=proposal, critique=critique, final_proposal=final_proposal,
        tool_calls=tool_calls,
    )
    emitter.emit("approve.decision", node="approve", output=state.decision.model_dump())
    emitter.emit("node.complete", node="approve", output={"outcome": outcome})
    return state
```

Investigation runs only on the middle band — auto-approve and hard-block paths are deterministic and don't need it. This keeps cost predictable.

- [ ] **Step 4: Run the test — verify it passes**

```bash
cd backend && .venv/bin/pytest tests/test_approve_agent.py -v
```

Expected: all tests in the file pass.

- [ ] **Step 5: Run the full backend suite — confirm no regressions**

```bash
cd backend && .venv/bin/pytest -x -q
```

Expected: all pass. If `test_integration.py` golden fixtures break because the prompt context changed, those fixtures need regenerating — but only after verifying the structural changes are correct. If a fixture diff is purely additive (new tool.call events) update the fixture; if it changes a decision outcome, stop and investigate.

- [ ] **Step 6: Commit**

```bash
git add backend/app/agents/approve.py backend/tests/test_approve_agent.py backend/tests/conftest.py
git commit -m "feat(approve): add LLM tool-using investigate pass"
```

---

## Task 5: Surface tool calls in the frontend

**Files:**
- Modify: `frontend/src/types/state.ts`
- Modify: `frontend/src/components/Timeline.tsx`
- Modify: `frontend/src/components/CritiquePanel.tsx`

- [ ] **Step 1: Mirror the ToolCall type**

In `frontend/src/types/state.ts`, find the existing `Decision` type and add a sibling type plus a field. Inspect the current shape first:

```bash
grep -n "Decision\|tool_calls\|ToolCall" /Users/mwakichako/repos/invoice-processing/frontend/src/types/state.ts
```

Add:

```typescript
export type ToolCall = {
  tool: "lookup_inventory" | "lookup_vendor" | "recompute_totals";
  arguments: Record<string, unknown>;
  result: Record<string, unknown>;
  latency_ms: number;
};
```

And add to the existing `Decision` type definition:

```typescript
tool_calls: ToolCall[];
```

- [ ] **Step 2: Render tool.call events in Timeline**

In `frontend/src/components/Timeline.tsx`, find the switch/map that maps event `kind` to a row renderer. Add a case for `"tool.call"`:

```typescript
case "tool.call":
  return (
    <div className="flex items-start gap-2 py-1 text-sm">
      <span className="text-purple-600 font-mono">tool</span>
      <span className="font-medium">{String(event.tool)}</span>
      <span className="text-gray-500 truncate">
        {JSON.stringify(event.arguments)} → {JSON.stringify(event.result)}
      </span>
    </div>
  );
```

If the existing code uses a different rendering pattern (e.g., a lookup table keyed by `kind`), follow that pattern instead. Do not introduce a parallel rendering approach.

- [ ] **Step 3: Show tool calls in CritiquePanel**

In `frontend/src/components/CritiquePanel.tsx`, after the existing critique/proposal sections, add a tool-calls section:

```tsx
{decision.tool_calls.length > 0 && (
  <section className="mt-4">
    <h3 className="font-semibold mb-2">Investigation tool calls</h3>
    <ul className="space-y-1">
      {decision.tool_calls.map((tc, i) => (
        <li key={i} className="text-sm font-mono bg-gray-50 p-2 rounded">
          <span className="text-purple-700">{tc.tool}</span>(
          {JSON.stringify(tc.arguments)}) →{" "}
          <span className="text-gray-700">{JSON.stringify(tc.result)}</span>
          <span className="text-gray-400 ml-2">({tc.latency_ms}ms)</span>
        </li>
      ))}
    </ul>
  </section>
)}
```

- [ ] **Step 4: Verify the frontend builds**

```bash
cd frontend && npm run build
```

Expected: clean build, no TS errors. If the test suite has a frontend lint/typecheck step (`npm run typecheck`), run it too.

- [ ] **Step 5: Manual smoke test**

```bash
# Terminal 1
cd backend && .venv/bin/uvicorn app.api.app:app --reload
# Terminal 2
cd frontend && npm run dev
```

Upload `data/invoices/invoice_1002.txt` (the GadgetX over-stock case — middle band, triggers investigate). Confirm in the Timeline that one or more `tool` rows appear, and that the CritiquePanel shows the "Investigation tool calls" section.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types/state.ts frontend/src/components/Timeline.tsx frontend/src/components/CritiquePanel.tsx
git commit -m "feat(ui): render approve-agent tool calls in timeline and critique panel"
```

---

## Task 6: Update README to document tool-use

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Find the Architecture section**

```bash
grep -n "Architecture\|approve\|tool" /Users/mwakichako/repos/invoice-processing/README.md
```

- [ ] **Step 2: Add a "Tool use" bullet under Architecture**

In the architecture section, add a line that explicitly calls out the new capability. Example wording to drop in (adjust to match surrounding style):

```markdown
- **Tool use**: the approve agent runs an investigate pass on borderline cases,
  calling `lookup_inventory`, `lookup_vendor`, and `recompute_totals` via xAI's
  function-calling API. Tool calls are captured on `Decision.tool_calls` and
  visualised in the timeline.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document approve-agent tool use in README"
```

---

## Self-Review Notes (for plan-writer's reference)

- Tasks 1 and 2 are independent and could be parallelised by a subagent runner.
- Task 4 is the integration point and must follow 1, 2, 3.
- Task 5 depends only on Task 1 (the state shape) — the backend wiring can be in flight.
- The integration test (`test_integration.py`) uses recorded LLM fixtures. After Task 4, those fixtures are likely stale because the prompt context now includes investigation results. Re-record them as a separate commit if they fail: `pytest tests/test_integration.py --record-mode=all` (or whatever the project uses — check `lessons.md`).
