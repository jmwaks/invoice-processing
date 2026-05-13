from pathlib import Path

from app.db.init_db import init_db
from app.tools.inventory_tool import inventory_lookup
from app.tools.vendor_tool import vendor_lookup

SEED = Path(__file__).resolve().parents[1] / "app" / "db" / "seed.yaml"


def _seeded(tmp_path: Path) -> Path:
    db = tmp_path / "test.db"
    init_db(db, seed_path=SEED, reset=True)
    return db


def test_inventory_lookup_found(tmp_path: Path):
    db = _seeded(tmp_path)
    r = inventory_lookup("WidgetA", db_path=db)
    assert r.found is True
    assert r.item == "WidgetA"
    assert r.stock == 15
    assert r.unit_price == 250.0


def test_inventory_lookup_not_found(tmp_path: Path):
    db = _seeded(tmp_path)
    r = inventory_lookup("SuperGizmo", db_path=db)
    assert r.found is False
    assert r.item == "SuperGizmo"
    assert r.stock is None
    assert r.unit_price is None


def test_inventory_lookup_normalizes_widget_spacing(tmp_path: Path):
    db = _seeded(tmp_path)
    r = inventory_lookup("Widget A", db_path=db)
    assert r.found is True
    assert r.stock == 15


def test_vendor_lookup_match_via_normalization(tmp_path: Path):
    db = _seeded(tmp_path)
    r = vendor_lookup("widgets inc.", db_path=db)
    assert r.found is True
    assert r.status == "approved"


def test_vendor_lookup_unknown(tmp_path: Path):
    db = _seeded(tmp_path)
    r = vendor_lookup("Fraudster LLC", db_path=db)
    assert r.found is False
