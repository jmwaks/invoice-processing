import datetime as dt
from pathlib import Path

from app.agents.validate import run_validate
from app.db.init_db import init_db
from app.graph.state import InvoiceData, InvoiceState, LineItem
from app.logging_.event_emitter import EventEmitter

SEED = Path(__file__).resolve().parents[1] / "app" / "db" / "seed.yaml"


def _seeded(tmp_path: Path) -> Path:
    db = tmp_path / "t.db"
    init_db(db, seed_path=SEED, reset=True)
    return db


def _state(invoice: InvoiceData) -> InvoiceState:
    return InvoiceState(
        run_id="r", source_path="x", file_format="txt", invoice=invoice,
    )


def _inv(**kw) -> InvoiceData:
    base = dict(
        invoice_number="INV-X", vendor="Widgets Inc.", date=None, due_date=None,
        line_items=[], subtotal=None, tax_amount=None, total=None, raw_text="",
    )
    base.update(kw)
    return InvoiceData(**base)


def test_unknown_item_blocks(tmp_path: Path):
    db = _seeded(tmp_path)
    state = _state(_inv(
        line_items=[LineItem(item="SuperGizmo", quantity=2, unit_price=400.0)],
        total=800.0,
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    kinds = {i.kind for i in out.validation.issues}
    assert "unknown_item" in kinds


def test_qty_exceeds_stock_blocks(tmp_path: Path):
    db = _seeded(tmp_path)
    state = _state(_inv(
        line_items=[LineItem(item="GadgetX", quantity=20, unit_price=750.0)],
        total=15000.0,
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    kinds = {i.kind for i in out.validation.issues}
    assert "qty_exceeds_stock" in kinds


def test_out_of_stock_blocks(tmp_path: Path):
    db = _seeded(tmp_path)
    state = _state(_inv(
        line_items=[LineItem(item="FakeItem", quantity=1, unit_price=1000.0)],
        total=1000.0,
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    kinds = {i.kind for i in out.validation.issues}
    assert "out_of_stock" in kinds


def test_missing_vendor_blocks(tmp_path: Path):
    db = _seeded(tmp_path)
    state = _state(_inv(vendor=None, line_items=[LineItem(item="WidgetA", quantity=1)]))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    kinds = {i.kind for i in out.validation.issues}
    assert "missing_vendor" in kinds


def test_negative_qty_blocks(tmp_path: Path):
    db = _seeded(tmp_path)
    state = _state(_inv(line_items=[LineItem(item="WidgetA", quantity=-5)]))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    kinds = {i.kind for i in out.validation.issues}
    assert "negative_qty" in kinds


def test_price_mismatch_warns(tmp_path: Path):
    db = _seeded(tmp_path)
    state = _state(_inv(
        line_items=[LineItem(item="WidgetA", quantity=4, unit_price=100.0)],
        total=400.0,
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    kinds = {i.kind for i in out.validation.issues}
    assert "price_mismatch" in kinds


def test_unknown_vendor_warns(tmp_path: Path):
    db = _seeded(tmp_path)
    state = _state(_inv(
        vendor="Fraudster LLC",
        line_items=[LineItem(item="WidgetA", quantity=1, unit_price=250.0)],
        total=250.0,
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    kinds = {i.kind for i in out.validation.issues}
    assert "unknown_vendor" in kinds


def test_records_lookups_for_ui(tmp_path: Path):
    db = _seeded(tmp_path)
    state = _state(_inv(
        line_items=[LineItem(item="WidgetA", quantity=1, unit_price=250.0)],
        total=250.0,
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    assert len(out.validation.inventory_lookups) == 1
    assert out.validation.vendor_lookup is not None
    from app.graph.state import InventoryLookupResult, VendorLookupResult
    assert isinstance(out.validation.inventory_lookups[0], InventoryLookupResult)
    assert isinstance(out.validation.vendor_lookup, VendorLookupResult)


def test_missing_total_blocks(tmp_path: Path):
    db = _seeded(tmp_path)
    state = _state(_inv(
        line_items=[LineItem(item="WidgetA", quantity=1, unit_price=250.0)],
        total=None,
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    kinds = {i.kind for i in out.validation.issues}
    assert "missing_total" in kinds


def test_no_line_items_blocks(tmp_path: Path):
    db = _seeded(tmp_path)
    state = _state(_inv(line_items=[], total=0.0))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    kinds = {i.kind for i in out.validation.issues}
    assert "no_line_items" in kinds


def test_past_due_date_warns(tmp_path: Path):
    from datetime import date
    db = _seeded(tmp_path)
    state = _state(_inv(
        date=date(2025, 1, 15),
        due_date=date(2025, 1, 10),
        line_items=[LineItem(item="WidgetA", quantity=1, unit_price=250.0)],
        total=250.0,
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    kinds = {i.kind for i in out.validation.issues}
    assert "past_due_date" in kinds


def test_total_math_error_warns(tmp_path: Path):
    db = _seeded(tmp_path)
    # 2 × $250 = $500, but invoice says total $9999 → math error
    state = _state(_inv(
        line_items=[LineItem(item="WidgetA", quantity=2, unit_price=250.0)],
        subtotal=9999.0,
        total=9999.0,
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    kinds = {i.kind for i in out.validation.issues}
    assert "total_math_error" in kinds


def test_non_usd_currency_warns(tmp_path: Path):
    db = _seeded(tmp_path)
    # INV-9004 case: invoice in EUR. The payment pipeline has no FX support and
    # would pay the numeric amount as USD. Flag for scrutiny.
    state = _state(_inv(
        line_items=[LineItem(item="WidgetA", quantity=4, unit_price=225.0)],
        total=900.0, currency="EUR",
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    by_kind = {i.kind: i for i in out.validation.issues}
    assert "currency_mismatch" in by_kind
    assert by_kind["currency_mismatch"].severity == "warn"


def test_usd_currency_does_not_warn(tmp_path: Path):
    db = _seeded(tmp_path)
    state = _state(_inv(
        line_items=[LineItem(item="WidgetA", quantity=1, unit_price=250.0)],
        total=250.0, currency="USD",
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    kinds = {i.kind for i in out.validation.issues}
    assert "currency_mismatch" not in kinds


def test_qty_exceeds_stock_aggregates_across_split_lines(tmp_path: Path):
    db = _seeded(tmp_path)
    # INV-9005 case: same item split across 49 lines of qty=1, each below stock (15)
    # individually but aggregate (49) exceeds stock. Per-line check misses; aggregate must catch.
    state = _state(_inv(
        line_items=[LineItem(item="WidgetA", quantity=1, unit_price=250.0) for _ in range(49)],
        total=12250.0,
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    kinds = [i.kind for i in out.validation.issues]
    assert "qty_exceeds_stock" in kinds
    # Should emit exactly one qty_exceeds_stock for WidgetA, not 49.
    assert kinds.count("qty_exceeds_stock") == 1


def test_total_math_error_detects_subtotal_plus_tax_mismatch(tmp_path: Path):
    db = _seeded(tmp_path)
    # INV-9003 case: line items × unit price match subtotal (4 × $250 = $1000),
    # but subtotal $1000 + tax $50 = $1050 does NOT match stated total $1500.
    # The line-items-vs-subtotal check alone passes; we must also verify
    # subtotal + tax ≈ total.
    state = _state(_inv(
        line_items=[LineItem(item="WidgetA", quantity=4, unit_price=250.0)],
        subtotal=1000.0,
        tax_amount=50.0,
        total=1500.0,
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    kinds = {i.kind for i in out.validation.issues}
    assert "total_math_error" in kinds


def test_price_mismatch_fires_at_exact_tolerance_boundary(tmp_path: Path):
    # INV-9004's exact numbers: 4 × $225 vs catalog $250 = drift exactly 10%.
    # `drift > PRICE_TOLERANCE` excludes this boundary; `drift >= PRICE_TOLERANCE`
    # catches it. Semantic intent of `PRICE_TOLERANCE = 0.10` is "10% or more".
    db = _seeded(tmp_path)
    state = _state(_inv(
        line_items=[LineItem(item="WidgetA", quantity=4, unit_price=225.0)],
        total=900.0,
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    kinds = {i.kind for i in out.validation.issues}
    assert "price_mismatch" in kinds


def test_duplicate_invoice_warns_when_registry_has_prior(tmp_path: Path):
    import datetime as dt
    from app.db.paid_invoices import PaidInvoiceRecord, record_paid
    from app.db.init_db import normalize_vendor

    db = _seeded(tmp_path)
    record_paid(
        PaidInvoiceRecord(
            vendor_normalized=normalize_vendor("Widgets Inc."),
            invoice_number="INV-1001",
            run_id="prior-run",
            vendor_display="Widgets Inc.",
            amount=5000.0,
            paid_at=dt.datetime(2026, 1, 16, 12, 0, tzinfo=dt.timezone.utc),
        ),
        db_path=db,
    )
    state = _state(_inv(
        invoice_number="INV-1001", vendor="Widgets Inc.",
        line_items=[LineItem(item="WidgetA", quantity=5, unit_price=250.0)],
        total=1250.0,
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    by_kind = {i.kind: i for i in out.validation.issues}
    assert "duplicate_invoice" in by_kind
    assert by_kind["duplicate_invoice"].severity == "warn"
    assert "prior-run" in by_kind["duplicate_invoice"].detail


def test_duplicate_invoice_does_not_fire_for_different_vendor(tmp_path: Path):
    import datetime as dt
    from app.db.paid_invoices import PaidInvoiceRecord, record_paid
    from app.db.init_db import normalize_vendor

    db = _seeded(tmp_path)
    record_paid(
        PaidInvoiceRecord(
            vendor_normalized=normalize_vendor("Vendor A"),
            invoice_number="INV-001",
            run_id="r-a", vendor_display="Vendor A",
            amount=100.0,
            paid_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
        ),
        db_path=db,
    )
    state = _state(_inv(
        invoice_number="INV-001", vendor="Widgets Inc.",
        line_items=[LineItem(item="WidgetA", quantity=1, unit_price=250.0)],
        total=250.0,
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    kinds = {i.kind for i in out.validation.issues}
    assert "duplicate_invoice" not in kinds


def test_duplicate_check_skipped_when_vendor_missing(tmp_path: Path):
    db = _seeded(tmp_path)
    state = _state(_inv(
        invoice_number="INV-1001", vendor=None,
        line_items=[LineItem(item="WidgetA", quantity=1, unit_price=250.0)],
        total=250.0,
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter)
    kinds = {i.kind for i in out.validation.issues}
    assert "missing_vendor" in kinds
    assert "duplicate_invoice" not in kinds
    event_kinds = [e.get("kind") for e in state.events]
    assert "duplicate_check_skipped" in event_kinds


def test_duplicate_invoice_writes_retroactive_event_to_prior_log(tmp_path: Path):
    """When a duplicate is detected, append `duplicate_detected_retroactive`
    to the prior run's jsonl event log."""
    import datetime as dt
    import json
    from app.db.paid_invoices import PaidInvoiceRecord, record_paid
    from app.db.init_db import normalize_vendor

    db = _seeded(tmp_path)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    prior_run_id = "prior-run"
    prior_log = log_dir / f"{prior_run_id}.jsonl"
    prior_log.write_text(
        json.dumps({"kind": "node.start", "ts": "2026-01-16T12:00:00Z", "node": "ingest"})
        + "\n"
    )
    record_paid(
        PaidInvoiceRecord(
            vendor_normalized=normalize_vendor("Widgets Inc."),
            invoice_number="INV-1001", run_id=prior_run_id,
            vendor_display="Widgets Inc.", amount=5000.0,
            paid_at=dt.datetime(2026, 1, 16, 12, 0, tzinfo=dt.timezone.utc),
        ),
        db_path=db,
    )

    state = _state(_inv(
        invoice_number="INV-1001", vendor="Widgets Inc.",
        line_items=[LineItem(item="WidgetA", quantity=5, unit_price=250.0)],
        total=1250.0,
    ))
    state.run_id = "later-run"
    emitter = EventEmitter("later-run", state.events, log_dir)
    run_validate(state, db_path=db, emitter=emitter)

    lines = prior_log.read_text().splitlines()
    retro = [
        json.loads(line) for line in lines
        if json.loads(line).get("kind") == "duplicate_detected_retroactive"
    ]
    assert len(retro) == 1
    assert retro[0]["later_run_id"] == "later-run"
    assert retro[0]["later_amount"] == 1250.0


def test_duplicate_invoice_writes_decision_update_sidecar(tmp_path: Path):
    """When a duplicate is detected, append a row to decision_updates.jsonl
    flipping the prior run to needs_review."""
    import datetime as dt
    import json
    from app.db.paid_invoices import PaidInvoiceRecord, record_paid
    from app.db.init_db import normalize_vendor

    db = _seeded(tmp_path)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    prior_run_id = "prior-run"
    (log_dir / f"{prior_run_id}.jsonl").write_text("")
    record_paid(
        PaidInvoiceRecord(
            vendor_normalized=normalize_vendor("Widgets Inc."),
            invoice_number="INV-1001", run_id=prior_run_id,
            vendor_display="Widgets Inc.", amount=5000.0,
            paid_at=dt.datetime(2026, 1, 16, tzinfo=dt.timezone.utc),
        ),
        db_path=db,
    )

    state = _state(_inv(
        invoice_number="INV-1001", vendor="Widgets Inc.",
        line_items=[LineItem(item="WidgetA", quantity=5, unit_price=250.0)],
        total=1250.0,
    ))
    state.run_id = "later-run"
    emitter = EventEmitter("later-run", state.events, log_dir)
    run_validate(state, db_path=db, emitter=emitter)

    sidecar = log_dir / "decision_updates.jsonl"
    assert sidecar.exists()
    rows = [json.loads(line) for line in sidecar.read_text().splitlines() if line.strip()]
    matching = [r for r in rows if r["run_id"] == prior_run_id]
    assert len(matching) == 1
    assert matching[0]["new_outcome"] == "needs_review"
    assert matching[0]["reason"] == "duplicate_detected"
    assert matching[0]["triggered_by_run_id"] == "later-run"


def test_duplicate_invoice_handles_missing_prior_log_gracefully(tmp_path: Path):
    """If the prior run's jsonl is not on disk, emit a skipped event but do not raise."""
    import datetime as dt
    from app.db.paid_invoices import PaidInvoiceRecord, record_paid
    from app.db.init_db import normalize_vendor

    db = _seeded(tmp_path)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    # NOTE: no prior log file created.
    record_paid(
        PaidInvoiceRecord(
            vendor_normalized=normalize_vendor("Widgets Inc."),
            invoice_number="INV-1001", run_id="prior-run-gone",
            vendor_display="Widgets Inc.", amount=5000.0,
            paid_at=dt.datetime(2026, 1, 16, tzinfo=dt.timezone.utc),
        ),
        db_path=db,
    )

    state = _state(_inv(
        invoice_number="INV-1001", vendor="Widgets Inc.",
        line_items=[LineItem(item="WidgetA", quantity=1, unit_price=250.0)],
        total=250.0,
    ))
    state.run_id = "later-run"
    emitter = EventEmitter("later-run", state.events, log_dir)
    out = run_validate(state, db_path=db, emitter=emitter)
    kinds = {i.kind for i in out.validation.issues}
    assert "duplicate_invoice" in kinds
    event_kinds = [e.get("kind") for e in state.events]
    assert "duplicate_detected_retroactive_skipped" in event_kinds


import datetime as dt

from app.agents.validate import _check_future_date


def test_check_future_date_empty_when_date_none():
    inv = _inv(date=None)
    assert _check_future_date(inv, dt.date(2026, 5, 13)) == []


def test_check_future_date_empty_when_date_equals_today():
    inv = _inv(date=dt.date(2026, 5, 13))
    assert _check_future_date(inv, dt.date(2026, 5, 13)) == []


def test_check_future_date_empty_when_date_in_past():
    """The INV-1006 case: invoice date is in the past relative to today."""
    inv = _inv(date=dt.date(2026, 1, 25))
    assert _check_future_date(inv, dt.date(2026, 5, 13)) == []


def test_check_future_date_emits_warn_when_date_in_future():
    inv = _inv(date=dt.date(2026, 5, 23))
    issues = _check_future_date(inv, dt.date(2026, 5, 13))
    assert len(issues) == 1
    issue = issues[0]
    assert issue.kind == "future_date"
    assert issue.severity == "warn"
    assert "2026-05-23" in issue.detail
    assert "2026-05-13" in issue.detail
    assert "10" in issue.detail  # day count


def test_duplicate_invoice_retroactive_write_io_error_does_not_crash(
    tmp_path: Path, monkeypatch
):
    """If the retroactive write to the prior jsonl fails, validate must still
    emit the duplicate_invoice issue and a skipped event — never raise."""
    import datetime as dt
    from app.db.paid_invoices import PaidInvoiceRecord, record_paid
    from app.db.init_db import normalize_vendor

    db = _seeded(tmp_path)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    prior_log = log_dir / "prior-run.jsonl"
    prior_log.write_text("")  # exists, so the if-branch is taken
    record_paid(
        PaidInvoiceRecord(
            vendor_normalized=normalize_vendor("Widgets Inc."),
            invoice_number="INV-1001", run_id="prior-run",
            vendor_display="Widgets Inc.", amount=5000.0,
            paid_at=dt.datetime(2026, 1, 16, tzinfo=dt.timezone.utc),
        ),
        db_path=db,
    )

    # Patch Path.open so any append to the prior log raises OSError.
    # Only the prior_log path (prior-run.jsonl) in append mode should fail;
    # everything else (including emitter writes) must work normally.
    original_open = Path.open

    def _selective_open(self, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        if self.name.endswith("prior-run.jsonl") and "a" in mode:
            raise OSError("simulated disk full")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", _selective_open)

    state = _state(_inv(
        invoice_number="INV-1001", vendor="Widgets Inc.",
        line_items=[LineItem(item="WidgetA", quantity=1, unit_price=250.0)],
        total=250.0,
    ))
    state.run_id = "later-run"
    emitter = EventEmitter("later-run", state.events, log_dir)
    # Must not raise:
    out = run_validate(state, db_path=db, emitter=emitter)
    # Issue is still emitted on the current run:
    kinds = {i.kind for i in out.validation.issues}
    assert "duplicate_invoice" in kinds
    # Skipped event is emitted:
    event_kinds = [e.get("kind") for e in state.events]
    assert "duplicate_detected_retroactive_skipped" in event_kinds


def test_run_validate_emits_future_date_issue_when_date_after_today(tmp_path: Path):
    """Positive: invoice date 10 days in the future surfaces as a warn-level ValidationIssue."""
    db = _seeded(tmp_path)
    state = _state(_inv(
        date=dt.date(2026, 5, 23),
        line_items=[LineItem(item="WidgetA", quantity=1, unit_price=250.0)],
        total=250.0,
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter, today=dt.date(2026, 5, 13))
    future_date_issues = [i for i in out.validation.issues if i.kind == "future_date"]
    assert len(future_date_issues) == 1
    assert future_date_issues[0].severity == "warn"


def test_run_validate_no_future_date_issue_when_date_in_past(tmp_path: Path):
    """Regression for INV-1006: a past invoice date must NOT trigger a future_date issue."""
    db = _seeded(tmp_path)
    state = _state(_inv(
        invoice_number="INV-1006",
        vendor="Acme Industrial Supplies",
        date=dt.date(2026, 1, 25),
        line_items=[
            LineItem(item="WidgetA", quantity=5, unit_price=250.0),
            LineItem(item="WidgetB", quantity=3, unit_price=500.0),
        ],
        subtotal=2750.0, tax_amount=0.0, total=2750.0,
    ))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(state, db_path=db, emitter=emitter, today=dt.date(2026, 5, 13))
    assert not any(i.kind == "future_date" for i in out.validation.issues)
