from app.graph.state import (
    Critique,
    Decision,
    InvoiceData,
    InvoiceState,
    LineItem,
    Proposal,
    ToolCall,
    ValidationIssue,
)


def test_invoice_data_accepts_nullable_fields():
    inv = InvoiceData(
        invoice_number=None, vendor=None, date=None, due_date=None,
        line_items=[], subtotal=None, tax_amount=None, total=None,
        raw_text="",
    )
    assert inv.currency == "USD"


def test_line_item_requires_quantity():
    item = LineItem(item="WidgetA", quantity=3)
    assert item.unit_price is None
    assert item.quantity == 3


def test_validation_issue_kinds_constrained():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ValidationIssue(kind="not_a_real_kind", detail="x", severity="warn")


def test_decision_round_trips_to_json():
    p = Proposal(outcome="approved", rationale="ok", rules_applied=["r1"], unresolved_concerns=[])
    c = Critique(agrees=True, objections=[], missed_signals=[], rule_misapplications=[])
    d = Decision(
        outcome="approved", rationale="ok", rules_applied=["r1"],
        initial_proposal=p, critique=c, final_proposal=p,
    )
    payload = d.model_dump_json()
    Decision.model_validate_json(payload)


def test_invoice_state_serialises():
    s = InvoiceState(run_id="r1", source_path="x", file_format="txt")
    assert s.invoice is None
    assert s.events == []


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
