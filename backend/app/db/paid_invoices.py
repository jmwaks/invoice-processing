from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

from pydantic import BaseModel

from app.db.init_db import normalize_vendor

_DB_TIMEOUT = 30.0  # seconds; covers multi-worker contention windows


class PaidInvoiceRecord(BaseModel):
    vendor_normalized: str
    invoice_number: str
    run_id: str
    vendor_display: str | None
    amount: float
    paid_at: dt.datetime


def _connect(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(db_path, timeout=_DB_TIMEOUT)


def lookup_paid(
    *, vendor: str | None, invoice_number: str, db_path: Path,
) -> PaidInvoiceRecord | None:
    if not vendor or not vendor.strip() or not invoice_number:
        return None
    vendor_normalized = normalize_vendor(vendor)
    if not vendor_normalized:
        return None
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT vendor_normalized, invoice_number, run_id, vendor_display, "
            "       amount, paid_at "
            "  FROM paid_invoices "
            " WHERE vendor_normalized = ? AND invoice_number = ?",
            (vendor_normalized, invoice_number),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return PaidInvoiceRecord(
        vendor_normalized=row[0],
        invoice_number=row[1],
        run_id=row[2],
        vendor_display=row[3],
        amount=row[4],
        paid_at=dt.datetime.fromisoformat(row[5]),
    )


def record_paid(record: PaidInvoiceRecord, *, db_path: Path) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO paid_invoices ("
            "  vendor_normalized, invoice_number, run_id, "
            "  vendor_display, amount, paid_at"
            ") VALUES (?, ?, ?, ?, ?, ?)",
            (
                record.vendor_normalized,
                record.invoice_number,
                record.run_id,
                record.vendor_display,
                record.amount,
                record.paid_at.isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()
