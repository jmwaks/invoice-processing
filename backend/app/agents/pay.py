from __future__ import annotations
from app.graph.state import InvoiceState
from app.logging_.event_emitter import EventEmitter
from app.tools.payment_tool import mock_payment


def run_pay(
    state: InvoiceState, *, emitter: EventEmitter, paid_invoices: set[str],
) -> InvoiceState:
    emitter.emit("node.start", node="pay")
    inv = state.invoice
    if inv is None or inv.invoice_number is None or inv.total is None or not inv.vendor:
        emitter.emit("node.complete", node="pay", output={"skipped": True, "reason": "missing fields"})
        return state
    if inv.invoice_number in paid_invoices:
        emitter.emit("pay.skipped_duplicate", node="pay",
                     output={"invoice_number": inv.invoice_number})
        emitter.emit("node.complete", node="pay", output={"skipped": True, "reason": "duplicate"})
        return state
    receipt = mock_payment(
        vendor=inv.vendor, amount=inv.total,
        invoice_number=inv.invoice_number, run_id=state.run_id,
    )
    paid_invoices.add(inv.invoice_number)
    state.payment_receipt = receipt
    emitter.emit("tool.call", node="pay", tool="mock_payment",
                 args={"vendor": inv.vendor, "amount": inv.total}, result=receipt)
    emitter.emit("node.complete", node="pay", output=receipt)
    return state
