from __future__ import annotations

import datetime as dt
from pathlib import Path

from app.db.init_db import normalize_vendor
from app.db.paid_invoices import PaidInvoiceRecord, lookup_paid, record_paid
from app.graph.state import InvoiceState
from app.logging_.event_emitter import EventEmitter
from app.tools.payment_tool import mock_payment


def run_pay(
    state: InvoiceState, *, emitter: EventEmitter, paid_invoices: set[str],
    db_path: Path,
) -> InvoiceState:
    emitter.emit("node.start", node="pay")
    inv = state.invoice
    if inv is None or inv.invoice_number is None or inv.total is None or not inv.vendor:
        emitter.emit(
            "node.complete", node="pay", output={"skipped": True, "reason": "missing fields"}
        )
        return state
    invoice_number: str = inv.invoice_number
    vendor: str = inv.vendor
    total: float = inv.total
    # SQL registry is source of truth; in-memory set is a same-process fast-path.
    if invoice_number in paid_invoices or lookup_paid(
        vendor=vendor, invoice_number=invoice_number, db_path=db_path,
    ) is not None:
        emitter.emit("pay.skipped_duplicate", node="pay",
                     output={"invoice_number": invoice_number})
        emitter.emit("node.complete", node="pay", output={"skipped": True, "reason": "duplicate"})
        return state
    receipt = mock_payment(
        vendor=vendor, amount=total,
        invoice_number=invoice_number, run_id=state.run_id,
    )
    paid_invoices.add(invoice_number)
    record_paid(
        PaidInvoiceRecord(
            vendor_normalized=normalize_vendor(vendor),
            invoice_number=invoice_number,
            run_id=state.run_id,
            vendor_display=vendor,
            amount=total,
            paid_at=dt.datetime.now(dt.UTC),
        ),
        db_path=db_path,
    )
    state.payment_receipt = receipt
    emitter.emit("tool.call", node="pay", tool="mock_payment",
                 args={"vendor": vendor, "amount": total}, result=receipt)
    emitter.emit("node.complete", node="pay", output=receipt)
    return state
