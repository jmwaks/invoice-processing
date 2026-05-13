from pathlib import Path

import pytest

from app.db.init_db import init_db

SEED = Path(__file__).resolve().parent.parent / "app" / "db" / "seed.yaml"


@pytest.fixture(scope="session")
def session_db(tmp_path_factory):
    db = tmp_path_factory.mktemp("dbs") / "session.db"
    init_db(db, seed_path=SEED, reset=True)
    return db


# Function-scoped seeded DB — isolates write-heavy tests from the
# shared session_db. Use this in any test that mutates inventory or vendors.
@pytest.fixture
def seeded_db_path(tmp_path):
    db = tmp_path / "inventory.db"
    init_db(db, seed_path=SEED)
    return db
