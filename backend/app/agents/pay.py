from __future__ import annotations
from app.graph.state import InvoiceState
from app.logging_.event_emitter import EventEmitter
from app.tools.payment_tool import mock_payment

_PAID_INVOICES: set[str] = set()


def reset_paid_invoices() -> None:
    _PAID_INVOICES.clear()


def run_pay(state: InvoiceState, *, emitter: EventEmitter) -> InvoiceState:
    emitter.emit("node.start", node="pay")
    inv = state.invoice
    if inv is None or inv.invoice_number is None or inv.total is None or not inv.vendor:
        emitter.emit("node.complete", node="pay", output={"skipped": True, "reason": "missing fields"})
        return state
    if inv.invoice_number in _PAID_INVOICES:
        emitter.emit("pay.skipped_duplicate", node="pay",
                     output={"invoice_number": inv.invoice_number})
        emitter.emit("node.complete", node="pay", output={"skipped": True, "reason": "duplicate"})
        return state
    receipt = mock_payment(
        vendor=inv.vendor, amount=inv.total,
        invoice_number=inv.invoice_number, run_id=state.run_id,
    )
    _PAID_INVOICES.add(inv.invoice_number)
    state.payment_receipt = receipt
    emitter.emit("tool.call", node="pay", tool="mock_payment",
                 args={"vendor": inv.vendor, "amount": inv.total}, result=receipt)
    emitter.emit("node.complete", node="pay", output=receipt)
    return state
