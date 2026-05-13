from pathlib import Path
from app.db.init_db import init_db
from app.graph.state import InvoiceData, InvoiceState, LineItem
from app.agents.validate import run_validate
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
