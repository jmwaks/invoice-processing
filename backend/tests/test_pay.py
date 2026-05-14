from pathlib import Path

import pytest

from app.agents.pay import run_pay
from app.db.init_db import init_db
from app.graph.state import Critique, Decision, InvoiceData, InvoiceState, Proposal
from app.logging_.event_emitter import EventEmitter

SEED = Path(__file__).resolve().parent.parent / "app" / "db" / "seed.yaml"


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
    db = tmp_path / "inv.db"
    init_db(db, seed_path=SEED, reset=True)
    paid: set[str] = set()
    state = _state()
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_pay(state, emitter=emitter, paid_invoices=paid, db_path=db)
    assert out.payment_receipt is not None
    assert out.payment_receipt["status"] == "success"
    assert out.payment_receipt["vendor"] == "Widgets Inc."
    assert out.payment_receipt["amount"] == 500.0


def test_pay_idempotent(tmp_path: Path):
    db = tmp_path / "inv.db"
    init_db(db, seed_path=SEED, reset=True)
    paid: set[str] = set()
    state = _state()
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    run_pay(state, emitter=emitter, paid_invoices=paid, db_path=db)
    state2 = _state()
    emitter2 = EventEmitter("r2", state2.events, tmp_path / "logs")
    out = run_pay(state2, emitter=emitter2, paid_invoices=paid, db_path=db)
    assert any(e["kind"] == "pay.skipped_duplicate" for e in out.events)


def test_pay_persists_to_registry(tmp_path: Path) -> None:
    from app.agents.pay import run_pay
    from app.db.paid_invoices import lookup_paid
    from app.db.init_db import init_db
    from app.graph.state import InvoiceData, InvoiceState, LineItem
    from app.logging_.event_emitter import EventEmitter

    seed = Path(__file__).resolve().parent.parent / "app" / "db" / "seed.yaml"
    db = tmp_path / "inv.db"
    init_db(db, seed_path=seed, reset=True)

    invoice = InvoiceData(
        invoice_number="INV-1001", vendor="Widgets Inc.",
        date=None, due_date=None,
        line_items=[LineItem(item="WidgetA", quantity=5, unit_price=250.0)],
        subtotal=None, tax_amount=None, total=1250.0,
        currency="USD", payment_terms=None, raw_text="",
    )
    state = InvoiceState(
        run_id="run-pay-1", source_path="x", file_format="txt", invoice=invoice,
    )
    emitter = EventEmitter("run-pay-1", state.events, tmp_path / "logs")
    run_pay(state, emitter=emitter, paid_invoices=set(), db_path=db)

    got = lookup_paid(vendor="Widgets Inc.", invoice_number="INV-1001", db_path=db)
    assert got is not None
    assert got.run_id == "run-pay-1"
    assert got.amount == 1250.0
