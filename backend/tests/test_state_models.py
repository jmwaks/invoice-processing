import pytest
from pydantic import ValidationError

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


def test_tool_call_rejects_negative_latency():
    with pytest.raises(ValidationError):
        ToolCall(
            tool="lookup_inventory",
            arguments={"item": "WidgetA"},
            result={"found": False, "item": "WidgetA"},
            latency_ms=-1,
        )


def test_invoice_state_supports_parent_run_id():
    state = InvoiceState(
        run_id="r2", source_path="/tmp/x.txt", file_format="txt",
        parent_run_id="r1",
    )
    assert state.parent_run_id == "r1"


def test_invoice_state_parent_run_id_optional():
    state = InvoiceState(run_id="r1", source_path="/tmp/x.txt", file_format="txt")
    assert state.parent_run_id is None


def test_suspicion_signal_text_match_defaults_to_none():
    from app.graph.state import SuspicionSignal

    sig = SuspicionSignal(kind="urgent_language", detail="says URGENT", severity="medium")
    assert sig.text_match is None


def test_suspicion_signal_accepts_text_match_phrase():
    from app.graph.state import SuspicionSignal

    sig = SuspicionSignal(
        kind="wire_transfer_demand",
        detail="demands wire transfer",
        severity="high",
        text_match="wire transfer required within 24 hours",
    )
    assert sig.text_match == "wire transfer required within 24 hours"


def test_suspicion_signal_text_match_round_trips_json():
    from app.graph.state import SuspicionSignal

    sig = SuspicionSignal(
        kind="urgent_language", detail="x", severity="low",
        text_match="URGENT — pay now",
    )
    payload = sig.model_dump_json()
    restored = SuspicionSignal.model_validate_json(payload)
    assert restored.text_match == "URGENT — pay now"


def test_suspicion_signal_rejects_impossible_date_kind():
    """Banned kind: impossible_date is now owned by validate.py as `future_date`."""
    from app.graph.state import SuspicionSignal

    with pytest.raises(ValidationError):
        SuspicionSignal(kind="impossible_date", detail="x", severity="high")


def test_suspicion_signal_rejects_round_number_kind():
    """Banned kind: round_number is dropped; total_math_error covers the real risk."""
    from app.graph.state import SuspicionSignal

    with pytest.raises(ValidationError):
        SuspicionSignal(kind="round_number", detail="x", severity="medium")


def test_suspicion_signal_still_accepts_textual_kinds():
    """Remaining LLM-emitted kinds must still construct cleanly."""
    from app.graph.state import SuspicionSignal

    for kind in (
        "urgent_language",
        "unknown_vendor_pattern",
        "wire_transfer_demand",
        "homoglyph_corruption",
        "other",
    ):
        SuspicionSignal(kind=kind, detail="x", severity="low")  # must not raise


def test_validation_issue_accepts_future_date_kind():
    """New kind: future_date — owned by validate.py."""
    ValidationIssue(kind="future_date", detail="x", severity="warn")  # must not raise
