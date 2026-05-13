from __future__ import annotations
import argparse
import re
import sqlite3
from pathlib import Path
import yaml

INVENTORY_DDL = """
CREATE TABLE IF NOT EXISTS inventory (
    item       TEXT PRIMARY KEY,
    stock      INTEGER NOT NULL,
    unit_price REAL    NOT NULL
);
"""

VENDORS_DDL = """
CREATE TABLE IF NOT EXISTS vendors (
    name         TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('approved','pending','blocked'))
);
"""

_SUFFIX_RE = re.compile(r"\b(inc|llc|ltd|co|corp|corporation|company)\b\.?", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[^\w\s]")


def normalize_vendor(name: str) -> str:
    s = name.lower()
    s = _PUNCT_RE.sub("", s)
    s = _SUFFIX_RE.sub("", s)
    return " ".join(s.split())


def init_db(db_path: Path, seed_path: Path, reset: bool = False) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if reset and db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(INVENTORY_DDL + VENDORS_DDL)
        with seed_path.open() as f:
            seed = yaml.safe_load(f)
        for row in seed["inventory"]:
            conn.execute(
                "INSERT OR REPLACE INTO inventory(item, stock, unit_price) VALUES (?,?,?)",
                (row["item"], row["stock"], row["unit_price"]),
            )
        for display in seed["vendors"]:
            conn.execute(
                "INSERT OR REPLACE INTO vendors(name, display_name, status) VALUES (?,?,?)",
                (normalize_vendor(display), display, "approved"),
            )
        conn.commit()
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--db", type=Path, default=Path("data/inventory.db"))
    ap.add_argument("--seed", type=Path, default=Path("app/db/seed.yaml"))
    args = ap.parse_args()
    init_db(args.db, args.seed, reset=args.reset)
    print(f"DB initialized at {args.db}")


if __name__ == "__main__":
    main()
