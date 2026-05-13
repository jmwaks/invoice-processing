from pathlib import Path
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient
from app.api.app import create_app
from app.db.init_db import init_db

BACKEND_DIR = Path(__file__).resolve().parents[1]
SEED = BACKEND_DIR / "app" / "db" / "seed.yaml"
INVOICE_1001 = BACKEND_DIR / "data" / "invoices" / "invoice_1001.txt"


@pytest.fixture()
def client(tmp_path: Path):
    db = tmp_path / "api.db"
    init_db(db, seed_path=SEED, reset=True)
    # Local MagicMock — does not depend on fixture_helpers.MockGrokClient
    # (avoids cross-task dependency during parallel implementation).
    fake_llm = MagicMock()
    fake_llm.structured_complete.side_effect = RuntimeError("no LLM in API test")
    app = create_app(llm=fake_llm, db_path=db, log_dir=tmp_path / "logs")
    return TestClient(app)


def test_inventory_endpoint(client):
    resp = client.get("/api/inventory")
    assert resp.status_code == 200
    body = resp.json()
    assert "inventory" in body and "vendors" in body
    items = {row["item"] for row in body["inventory"]}
    assert {"WidgetA", "WidgetB", "GadgetX", "FakeItem"} <= items


def test_create_run_uploads_and_returns_id(client):
    with INVOICE_1001.open("rb") as f:
        resp = client.post("/api/runs", files={"file": (INVOICE_1001.name, f, "text/plain")})
    assert resp.status_code == 200
    body = resp.json()
    assert "run_id" in body


def test_list_runs(client):
    with INVOICE_1001.open("rb") as f:
        client.post("/api/runs", files={"file": (INVOICE_1001.name, f, "text/plain")})
    resp = client.get("/api/runs")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1
