from __future__ import annotations
import sqlite3
from pathlib import Path
from app.db.init_db import normalize_vendor
from app.config import get_settings


def vendor_lookup(name: str, db_path: Path | None = None) -> dict:
    if not name or not name.strip():
        return {"found": False, "name": name, "status": None}
    db_path = db_path or get_settings().invoice_processing_db_path
    conn = sqlite3.connect(db_path)
    try:
        normalized = normalize_vendor(name)
        row = conn.execute(
            "SELECT display_name, status FROM vendors WHERE name = ?", (normalized,),
        ).fetchone()
        if row:
            return {"found": True, "name": row[0], "status": row[1]}
        return {"found": False, "name": name, "status": None}
    finally:
        conn.close()
