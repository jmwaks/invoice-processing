import sqlite3
from pathlib import Path
from app.db.init_db import init_db, normalize_vendor


def test_init_db_creates_tables_and_seeds(tmp_path: Path):
    db = tmp_path / "test.db"
    init_db(db, seed_path=Path("app/db/seed.yaml"), reset=True)
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT item, stock, unit_price FROM inventory ORDER BY item").fetchall()
    assert ("FakeItem", 0, 0.0) in rows
    assert ("WidgetA", 15, 250.0) in rows
    v = conn.execute("SELECT name, status FROM vendors WHERE display_name='Widgets Inc.'").fetchone()
    assert v == ("widgets", "approved")  # normalized form


def test_init_db_is_idempotent(tmp_path: Path):
    db = tmp_path / "test.db"
    init_db(db, seed_path=Path("app/db/seed.yaml"), reset=True)
    init_db(db, seed_path=Path("app/db/seed.yaml"), reset=False)
    conn = sqlite3.connect(db)
    n = conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
    assert n == 4


def test_normalize_vendor():
    assert normalize_vendor("Widgets Inc.") == "widgets"
    assert normalize_vendor("Acme Industrial Supplies") == "acme industrial supplies"
    assert normalize_vendor("Summit Manufacturing Co.") == "summit manufacturing"
    assert normalize_vendor("Fraudster LLC") == "fraudster"
