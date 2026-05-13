from pathlib import Path

from app.agents.pay import run_pay
from app.graph.state import Critique, Decision, InvoiceData, InvoiceState, Proposal
from app.logging_.event_emitter import EventEmitter


def _state(inv_num="INV-1", total=500.0) -> InvoiceState:
    p = Proposal(outcome="approved", rationale="ok", rules_applied=[], unresolved_concerns=[])
    c = Critique(agrees=True, objections=[], missed_signals=[], rule_misapplications=[])
    return InvoiceState(
        run_id="r", source_path="x", file_format="txt",
        invoice=InvoiceData(
            invoice_number=inv_num, vendor="Widgets Inc.", date=None, due_date=None,
            line_items=[], subtotal=total, tax_amount=0.0, total=total,
            raw_text="", payment_terms=None,
        ),
        decision=Decision(outcome="approved", rationale="", rules_applied=[],
                          initial_proposal=p, critique=c, final_proposal=p),
    )


def test_pay_returns_success_and_records_receipt(tmp_path: Path):
    paid: set[str] = set()
    state = _state()
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_pay(state, emitter=emitter, paid_invoices=paid)
    assert out.payment_receipt is not None
    assert out.payment_receipt["status"] == "success"
    assert out.payment_receipt["vendor"] == "Widgets Inc."
    assert out.payment_receipt["amount"] == 500.0


def test_pay_idempotent(tmp_path: Path):
    paid: set[str] = set()
    state = _state()
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    run_pay(state, emitter=emitter, paid_invoices=paid)
    state2 = _state()
    emitter2 = EventEmitter("r2", state2.events, tmp_path / "logs")
    out = run_pay(state2, emitter=emitter2, paid_invoices=paid)
    assert any(e["kind"] == "pay.skipped_duplicate" for e in out.events)
