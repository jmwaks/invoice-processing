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


def test_pay_does_not_dedup_across_different_vendors_with_same_invoice_number(
    tmp_path: Path,
) -> None:
    """The in-memory paid_invoices set is keyed by invoice_number only, but
    the registry key is composite (vendor, invoice_number). Two different
    vendors sharing the same invoice_number must both be allowed to pay."""
    from app.agents.pay import run_pay
    from app.db.init_db import init_db
    from app.db.paid_invoices import lookup_paid
    from app.graph.state import InvoiceData, InvoiceState, LineItem
    from app.logging_.event_emitter import EventEmitter

    seed = Path(__file__).resolve().parent.parent / "app" / "db" / "seed.yaml"
    db = tmp_path / "inv.db"
    init_db(db, seed_path=seed, reset=True)

    paid: set[str] = set()

    def _inv(vendor: str) -> InvoiceData:
        return InvoiceData(
            invoice_number="INV-001", vendor=vendor,
            date=None, due_date=None,
            line_items=[LineItem(item="WidgetA", quantity=1, unit_price=250.0)],
            subtotal=None, tax_amount=None, total=250.0,
            currency="USD", payment_terms=None, raw_text="",
        )

    # Vendor A pays INV-001.
    s1 = InvoiceState(run_id="r1", source_path="x", file_format="txt", invoice=_inv("Widgets Inc."))
    e1 = EventEmitter("r1", s1.events, tmp_path / "logs")
    run_pay(s1, emitter=e1, paid_invoices=paid, db_path=db)
    assert s1.payment_receipt is not None, "Vendor A should have paid"

    # Vendor B pays INV-001 — same in-process set, same invoice_number, different vendor.
    s2 = InvoiceState(run_id="r2", source_path="x", file_format="txt", invoice=_inv("Gadget Supplier"))
    e2 = EventEmitter("r2", s2.events, tmp_path / "logs")
    run_pay(s2, emitter=e2, paid_invoices=paid, db_path=db)
    assert s2.payment_receipt is not None, (
        "Vendor B should also have paid; the legacy in-memory check was incorrectly "
        "blocking on invoice_number alone."
    )
    # Both rows exist in the registry under different composite keys.
    assert lookup_paid(vendor="Widgets Inc.", invoice_number="INV-001", db_path=db) is not None
    assert lookup_paid(vendor="Gadget Supplier", invoice_number="INV-001", db_path=db) is not None
