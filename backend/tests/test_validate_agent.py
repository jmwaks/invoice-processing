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
