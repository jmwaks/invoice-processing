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


def test_effective_outcome_no_override_falls_back_to_decision(tmp_path: Path) -> None:
    import json
    from app.api.decisions import effective_outcome

    log_dir = tmp_path
    run_id = "r1"
    (log_dir / f"{run_id}.jsonl").write_text(
        json.dumps({
            "kind": "approve.decision",
            "output": {"outcome": "approved", "rationale": "all gates green",
                       "rules_applied": []},
        }) + "\n"
    )

    eo = effective_outcome(run_id, log_dir=log_dir)
    assert eo.outcome == "approved"
    assert eo.override_reason is None
    assert eo.overridden_at is None
    assert eo.triggered_by_run_id is None


def test_effective_outcome_applies_override_from_sidecar(tmp_path: Path) -> None:
    import json
    from app.api.decisions import effective_outcome

    log_dir = tmp_path
    run_id = "r1"
    (log_dir / f"{run_id}.jsonl").write_text(
        json.dumps({
            "kind": "approve.decision",
            "output": {"outcome": "approved", "rationale": "",
                       "rules_applied": []},
        }) + "\n"
    )
    (log_dir / "decision_updates.jsonl").write_text(
        json.dumps({
            "run_id": run_id,
            "invoice_number": "INV-1001",
            "previous_outcome": "approved",
            "new_outcome": "needs_review",
            "reason": "duplicate_detected",
            "updated_at": "2026-05-13T12:00:00+00:00",
            "triggered_by_run_id": "later-run",
        }) + "\n"
    )

    eo = effective_outcome(run_id, log_dir=log_dir)
    assert eo.outcome == "needs_review"
    assert eo.override_reason == "duplicate_detected"
    assert eo.triggered_by_run_id == "later-run"
    assert eo.overridden_at is not None


def test_effective_outcome_uses_latest_when_multiple_overrides(tmp_path: Path) -> None:
    import json
    from app.api.decisions import effective_outcome

    log_dir = tmp_path
    run_id = "r1"
    (log_dir / f"{run_id}.jsonl").write_text(
        json.dumps({"kind": "approve.decision",
                    "output": {"outcome": "approved", "rationale": "",
                               "rules_applied": []}}) + "\n"
    )
    (log_dir / "decision_updates.jsonl").write_text(
        json.dumps({"run_id": run_id, "invoice_number": "INV-1001",
                    "previous_outcome": "approved", "new_outcome": "needs_review",
                    "reason": "duplicate_detected",
                    "updated_at": "2026-05-13T12:00:00+00:00",
                    "triggered_by_run_id": "x"}) + "\n"
        + json.dumps({"run_id": run_id, "invoice_number": "INV-1001",
                      "previous_outcome": "needs_review", "new_outcome": "rejected",
                      "reason": "manual_review",
                      "updated_at": "2026-05-13T15:00:00+00:00",
                      "triggered_by_run_id": "y"}) + "\n"
    )

    eo = effective_outcome(run_id, log_dir=log_dir)
    assert eo.outcome == "rejected"
    assert eo.override_reason == "manual_review"
    assert eo.triggered_by_run_id == "y"


def test_get_run_includes_effective_outcome_block(api_client, tmp_path: Path) -> None:
    invoice_file = tmp_path / "inv.txt"
    invoice_file.write_text("INVOICE\nVendor: V\nInvoice Number: INV-X\nTotal: 100\n")
    with invoice_file.open("rb") as f:
        resp = api_client.post(
            "/api/runs", files={"file": ("inv.txt", f, "text/plain")},
        )
    run_id = resp.json()["run_id"]

    detail = api_client.get(f"/api/runs/{run_id}").json()
    assert "effective_outcome" in detail
    eo = detail["effective_outcome"]
    assert "outcome" in eo
    assert "override_reason" in eo
    assert "overridden_at" in eo
    assert "triggered_by_run_id" in eo
    assert eo["override_reason"] is None
