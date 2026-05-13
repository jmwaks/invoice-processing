from pathlib import Path
from unittest.mock import MagicMock

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


@pytest.fixture
def api_client(tmp_path, seeded_db_path):
    from fastapi.testclient import TestClient

    from app.api.app import create_app

    # Stub the LLM so graph.invoke never reaches xAI.
    # The stub returns the state dict unchanged so the run completes without error.
    fake_llm = MagicMock()
    fake_llm.structured_complete.side_effect = RuntimeError("no LLM in API test")
    app = create_app(llm=fake_llm, db_path=seeded_db_path, log_dir=tmp_path / "logs")
    return TestClient(app)


@pytest.fixture
def seeded_run_id(api_client, tmp_path) -> str:
    invoice_file = tmp_path / "inv.txt"
    invoice_file.write_bytes(b"INV-PARENT\nVendor: V\nTotal: 100\n")
    with invoice_file.open("rb") as f:
        resp = api_client.post("/api/runs", files={"file": ("inv.txt", f, "text/plain")})
    assert resp.status_code == 200
    return resp.json()["run_id"]
