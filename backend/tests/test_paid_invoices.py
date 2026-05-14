import datetime as dt
from pathlib import Path

import pytest

from app.db.paid_invoices import (
    PaidInvoiceRecord,
    lookup_paid,
    record_paid,
)

_NOW = dt.datetime(2026, 5, 13, 12, 0, tzinfo=dt.UTC)


def _record(
    invoice_number: str = "INV-1001",
    vendor_display: str = "Widgets Inc.",
    amount: float = 1250.0,
    run_id: str = "r1",
) -> PaidInvoiceRecord:
    from app.db.init_db import normalize_vendor
    return PaidInvoiceRecord(
        vendor_normalized=normalize_vendor(vendor_display),
        invoice_number=invoice_number,
        run_id=run_id,
        vendor_display=vendor_display,
        amount=amount,
        paid_at=_NOW,
    )


def test_lookup_miss_returns_none(seeded_db_path: Path) -> None:
    assert lookup_paid(
        vendor="Widgets Inc.", invoice_number="INV-1001", db_path=seeded_db_path,
    ) is None


def test_record_then_lookup_returns_record(seeded_db_path: Path) -> None:
    record_paid(_record(), db_path=seeded_db_path)
    got = lookup_paid(
        vendor="Widgets Inc.", invoice_number="INV-1001", db_path=seeded_db_path,
    )
    assert got is not None
    assert got.invoice_number == "INV-1001"
    assert got.amount == 1250.0
    assert got.run_id == "r1"


def test_composite_key_isolates_by_vendor(seeded_db_path: Path) -> None:
    record_paid(_record(vendor_display="Vendor A", run_id="r1"), db_path=seeded_db_path)
    record_paid(_record(vendor_display="Vendor B", run_id="r2"), db_path=seeded_db_path)
    a = lookup_paid(vendor="Vendor A", invoice_number="INV-1001", db_path=seeded_db_path)
    b = lookup_paid(vendor="Vendor B", invoice_number="INV-1001", db_path=seeded_db_path)
    assert a is not None and a.run_id == "r1"
    assert b is not None and b.run_id == "r2"


def test_vendor_normalization_parity(seeded_db_path: Path) -> None:
    record_paid(_record(vendor_display="Acme Corp", run_id="r1"), db_path=seeded_db_path)
    got = lookup_paid(
        vendor="Acme Corporation", invoice_number="INV-1001", db_path=seeded_db_path,
    )
    assert got is not None
    assert got.run_id == "r1"


def test_vendor_blank_lookup_returns_none(seeded_db_path: Path) -> None:
    record_paid(_record(), db_path=seeded_db_path)
    assert lookup_paid(vendor="", invoice_number="INV-1001", db_path=seeded_db_path) is None
    assert lookup_paid(vendor="   ", invoice_number="INV-1001", db_path=seeded_db_path) is None


def test_insert_or_ignore_preserves_first(seeded_db_path: Path) -> None:
    record_paid(_record(amount=1250.0, run_id="r1"), db_path=seeded_db_path)
    record_paid(_record(amount=9999.0, run_id="r2"), db_path=seeded_db_path)
    got = lookup_paid(
        vendor="Widgets Inc.", invoice_number="INV-1001", db_path=seeded_db_path,
    )
    assert got is not None
    assert got.amount == 1250.0
    assert got.run_id == "r1"


def test_init_db_idempotent_on_existing_table(seeded_db_path: Path) -> None:
    from app.db.init_db import init_db
    seed = Path(__file__).resolve().parent.parent / "app" / "db" / "seed.yaml"
    init_db(seeded_db_path, seed_path=seed, reset=False)
    assert lookup_paid(
        vendor="Widgets Inc.", invoice_number="INV-1001", db_path=seeded_db_path,
    ) is None
