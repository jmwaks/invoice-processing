from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from openai import AuthenticationError, RateLimitError

from app.agents import approve as approve_mod
from app.agents.approve import _run_investigate as _real_run_investigate
from app.agents.approve import route_after_approve, run_approve
from app.graph.state import (
    Critique,
    Decision,
    InvoiceData,
    InvoiceState,
    LineItem,
    Proposal,
    ToolCall,
    ValidationIssue,
    ValidationReport,
)
from app.logging_.event_emitter import EventEmitter


@pytest.fixture(autouse=True)
def _stub_investigate_by_default(monkeypatch):
    """By default no test exercises the investigate pass — keep the LLM tool
    loop out of the way so MagicMock-backed tests don't silently hit the
    broad exception handler. Tests that need to exercise investigate
    override this with their own monkeypatch."""
    from app.agents import approve as approve_mod
    monkeypatch.setattr(approve_mod, "_run_investigate", lambda **_kw: [])


def _state(total=1000.0, issues=None, vendor="Widgets Inc.") -> InvoiceState:
    return InvoiceState(
        run_id="r", source_path="x", file_format="txt",
        invoice=InvoiceData(
            invoice_number="INV-1", vendor=vendor, date=None, due_date=None,
            line_items=[LineItem(item="WidgetA", quantity=1, unit_price=250.0)],
            subtotal=total, tax_amount=0.0, total=total, raw_text="raw",
        ),
        extraction_confidence=0.95,
        validation=ValidationReport(issues=issues or [], inventory_lookups=[], vendor_lookup=None),
    )


def _fake_meta():
    return MagicMock(tokens_in=10, tokens_out=10, latency_ms=50, model="grok-4")


def test_approve_hard_block_forces_reject_regardless_of_llm(tmp_path: Path):
    issue = ValidationIssue(kind="qty_exceeds_stock", item="GadgetX", detail="", severity="block")
    state = _state(total=15000.0, issues=[issue])

    _ok = Proposal(
        outcome="approved", rationale="seems fine", rules_applied=[], unresolved_concerns=[]
    )
    _crit = Critique(agrees=True, objections=[], missed_signals=[], rule_misapplications=[])
    llm = MagicMock()
    llm.structured_complete.side_effect = [
        (_ok, _fake_meta()),
        (_crit, _fake_meta()),
        (
            Proposal(
                outcome="approved", rationale="confirmed",
                rules_applied=[], unresolved_concerns=[],
            ),
            _fake_meta(),
        ),
    ]

    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_approve(state, llm=llm, emitter=emitter)
    assert out.decision is not None
    assert out.decision.outcome == "rejected"
    assert "qty_exceeds_stock" in out.decision.rules_applied[0]


def test_approve_clean_invoice_approves(tmp_path: Path):
    state = _state(total=1000.0)
    llm = MagicMock()
    _approved = Proposal(
        outcome="approved", rationale="clean",
        rules_applied=["auto_approve"], unresolved_concerns=[],
    )
    _crit = Critique(agrees=True, objections=[], missed_signals=[], rule_misapplications=[])
    llm.structured_complete.side_effect = [
        (_approved, _fake_meta()),
        (_crit, _fake_meta()),
        (_approved, _fake_meta()),
    ]
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_approve(state, llm=llm, emitter=emitter)
    assert out.decision.outcome == "approved"
    assert out.decision.initial_proposal.outcome == "approved"
    assert out.decision.critique.agrees is True


def test_approve_critic_revises_initial(tmp_path: Path):
    state = _state(total=12000.0)
    llm = MagicMock()
    _prop1 = Proposal(
        outcome="approved", rationale="passed checks",
        rules_applied=["scrutiny"], unresolved_concerns=[],
    )
    _crit = Critique(
        agrees=False, objections=["missed risk"], missed_signals=[], rule_misapplications=[],
    )
    _prop2 = Proposal(
        outcome="needs_review", rationale="critic raised concern",
        rules_applied=["scrutiny"], unresolved_concerns=["missed risk"],
    )
    llm.structured_complete.side_effect = [
        (_prop1, _fake_meta()),
        (_crit, _fake_meta()),
        (_prop2, _fake_meta()),
    ]
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_approve(state, llm=llm, emitter=emitter)
    assert out.decision.outcome == "needs_review"
    assert out.decision.initial_proposal.outcome == "approved"
    assert out.decision.final_proposal.outcome == "needs_review"


def test_approve_critique_failure_escalates_to_needs_review(tmp_path: Path):
    state = _state(total=500.0)
    llm = MagicMock()
    _ok = Proposal(outcome="approved", rationale="ok", rules_applied=[], unresolved_concerns=[])
    llm.structured_complete.side_effect = [
        (_ok, _fake_meta()),
        RuntimeError("simulated critique timeout"),
        (_ok, _fake_meta()),
    ]
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_approve(state, llm=llm, emitter=emitter)
    assert out.decision.outcome == "needs_review"
    assert "Critique pass failed" in out.decision.rationale
    # Verify the synthetic critique landed in the audit trail
    assert out.decision.critique.agrees is False
    assert any("critique pass failed" in o for o in out.decision.critique.objections)


def _dec(outcome):
    p = Proposal(outcome=outcome, rationale="", rules_applied=[], unresolved_concerns=[])
    c = Critique(agrees=True, objections=[], missed_signals=[], rule_misapplications=[])
    return Decision(outcome=outcome, rationale="", rules_applied=[],
                    initial_proposal=p, critique=c, final_proposal=p)


def test_route_after_approve_approved_goes_to_pay():
    state = InvoiceState(run_id="r", source_path="x", file_format="txt")
    state.decision = _dec("approved")
    assert route_after_approve(state) == "pay"


def test_route_after_approve_rejected_goes_to_log():
    state = InvoiceState(run_id="r", source_path="x", file_format="txt")
    state.decision = _dec("rejected")
    assert route_after_approve(state) == "log"


def test_route_after_approve_needs_review_goes_to_log():
    state = InvoiceState(run_id="r", source_path="x", file_format="txt")
    state.decision = _dec("needs_review")
    assert route_after_approve(state) == "log"


# ---------------------------------------------------------------------------
# Middle-band (scrutiny) helpers
# ---------------------------------------------------------------------------

def _make_scrutiny_state() -> InvoiceState:
    """Total > $10k, no hard blocks — triggers the middle band (not auto-approve, not hard-block)."""
    return _state(total=12000.0)


def _run_approve_with_stubbed_llm(state: InvoiceState, tmp_path: Path) -> InvoiceState:
    """Run approve with a fake LLM that always returns a canned approval."""
    _ok = Proposal(
        outcome="approved", rationale="ok", rules_applied=["scrutiny"], unresolved_concerns=[]
    )
    _crit = Critique(agrees=True, objections=[], missed_signals=[], rule_misapplications=[])
    llm = MagicMock()
    llm.structured_complete.side_effect = [
        (_ok, _fake_meta()),
        (_crit, _fake_meta()),
        (_ok, _fake_meta()),
    ]
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    return run_approve(state, llm=llm, emitter=emitter)


def test_approve_captures_tool_calls_on_decision(monkeypatch, tmp_path):
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

    state = _run_approve_with_stubbed_llm(_make_scrutiny_state(), tmp_path)
    assert state.decision is not None
    assert len(state.decision.tool_calls) == 1
    assert state.decision.tool_calls[0].tool == "lookup_inventory"


def _make_rate_limit_error() -> RateLimitError:
    response = httpx.Response(
        429,
        request=httpx.Request("POST", "https://api.x.ai/v1/chat/completions"),
    )
    return RateLimitError(message="capacity exhausted", response=response, body=None)


def _make_auth_error() -> AuthenticationError:
    response = httpx.Response(
        401,
        request=httpx.Request("POST", "https://api.x.ai/v1/chat/completions"),
    )
    return AuthenticationError(message="invalid api key", response=response, body=None)


def test_investigate_surfaces_rate_limit_as_llm_unavailable(monkeypatch, tmp_path):
    """RateLimitError from run_tool_loop must propagate as LLMUnavailableError."""
    from app.llm.grok_client import GrokClient, LLMUnavailableError

    monkeypatch.setattr(
        approve_mod, "run_tool_loop", MagicMock(side_effect=_make_rate_limit_error())
    )
    # Restore the real _run_investigate so the autouse stub doesn't swallow the call.
    monkeypatch.setattr(approve_mod, "_run_investigate", _real_run_investigate)

    mock_sdk = MagicMock()
    client = GrokClient(model="grok-4", fallback_model="grok-3", sdk=mock_sdk)
    emitter = EventEmitter("r", [], tmp_path / "logs")

    with pytest.raises(LLMUnavailableError):
        approve_mod._run_investigate(
            llm=client, emitter=emitter, context="x", db_path=tmp_path / "db.sqlite"
        )


def test_investigate_surfaces_auth_error_as_llm_configuration(monkeypatch, tmp_path):
    """AuthenticationError from run_tool_loop must propagate as LLMConfigurationError."""
    from app.llm.grok_client import GrokClient, LLMConfigurationError

    monkeypatch.setattr(
        approve_mod, "run_tool_loop", MagicMock(side_effect=_make_auth_error())
    )
    # Restore the real _run_investigate so the autouse stub doesn't swallow the call.
    monkeypatch.setattr(approve_mod, "_run_investigate", _real_run_investigate)

    mock_sdk = MagicMock()
    client = GrokClient(model="grok-4", fallback_model="grok-3", sdk=mock_sdk)
    emitter = EventEmitter("r", [], tmp_path / "logs")

    with pytest.raises(LLMConfigurationError) as exc_info:
        approve_mod._run_investigate(
            llm=client, emitter=emitter, context="x", db_path=tmp_path / "db.sqlite"
        )

    assert "key" in exc_info.value.user_message.lower()
