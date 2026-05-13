from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import get_settings
from app.graph.state import InventoryLookupResult


def _norm_item(s: str) -> str:
    return "".join(s.split()).lower()


def inventory_lookup(item: str, db_path: Path | None = None) -> InventoryLookupResult:
    db_path = db_path or get_settings().invoice_processing_db_path
    conn = sqlite3.connect(db_path)
    try:
        target = _norm_item(item)
        cur = conn.execute("SELECT item, stock, unit_price FROM inventory")
        for row_item, stock, unit_price in cur.fetchall():
            if _norm_item(row_item) == target:
                return InventoryLookupResult(
                    found=True, item=row_item,
                    stock=int(stock), unit_price=float(unit_price),
                )
        return InventoryLookupResult(found=False, item=item)
    finally:
        conn.close()
