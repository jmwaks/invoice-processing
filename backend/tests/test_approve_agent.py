from pathlib import Path
from unittest.mock import MagicMock
from app.graph.state import (
    InvoiceData, InvoiceState, ValidationIssue, ValidationReport, LineItem,
    Proposal, Critique,
)
from app.agents.approve import run_approve
from app.logging_.event_emitter import EventEmitter


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

    llm = MagicMock()
    llm.structured_complete.side_effect = [
        (Proposal(outcome="approved", rationale="seems fine", rules_applied=[], unresolved_concerns=[]), _fake_meta()),
        (Critique(agrees=True, objections=[], missed_signals=[], rule_misapplications=[]), _fake_meta()),
        (Proposal(outcome="approved", rationale="confirmed", rules_applied=[], unresolved_concerns=[]), _fake_meta()),
    ]

    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_approve(state, llm=llm, emitter=emitter)
    assert out.decision is not None
    assert out.decision.outcome == "rejected"
    assert "qty_exceeds_stock" in out.decision.rules_applied[0]


def test_approve_clean_invoice_approves(tmp_path: Path):
    state = _state(total=1000.0)
    llm = MagicMock()
    llm.structured_complete.side_effect = [
        (Proposal(outcome="approved", rationale="clean", rules_applied=["auto_approve"], unresolved_concerns=[]), _fake_meta()),
        (Critique(agrees=True, objections=[], missed_signals=[], rule_misapplications=[]), _fake_meta()),
        (Proposal(outcome="approved", rationale="clean", rules_applied=["auto_approve"], unresolved_concerns=[]), _fake_meta()),
    ]
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_approve(state, llm=llm, emitter=emitter)
    assert out.decision.outcome == "approved"
    assert out.decision.initial_proposal.outcome == "approved"
    assert out.decision.critique.agrees is True


def test_approve_critic_revises_initial(tmp_path: Path):
    state = _state(total=12000.0)
    llm = MagicMock()
    llm.structured_complete.side_effect = [
        (Proposal(outcome="approved", rationale="passed checks", rules_applied=["scrutiny"], unresolved_concerns=[]), _fake_meta()),
        (Critique(agrees=False, objections=["missed risk"], missed_signals=[], rule_misapplications=[]), _fake_meta()),
        (Proposal(outcome="needs_review", rationale="critic raised concern", rules_applied=["scrutiny"], unresolved_concerns=["missed risk"]), _fake_meta()),
    ]
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_approve(state, llm=llm, emitter=emitter)
    assert out.decision.outcome == "needs_review"
    assert out.decision.initial_proposal.outcome == "approved"
    assert out.decision.final_proposal.outcome == "needs_review"
