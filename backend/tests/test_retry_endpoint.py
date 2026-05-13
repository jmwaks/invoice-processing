from __future__ import annotations

from fastapi.testclient import TestClient


def test_retry_creates_child_run_with_seeded_invoice(api_client: TestClient, seeded_run_id: str):
    edited = {
        "invoice_number": "INV-X-edit",
        "vendor": "Test Vendor",
        "date": None, "due_date": None,
        "line_items": [{"item": "WidgetA", "quantity": 1, "unit_price": 250.0, "notes": None}],
        "subtotal": 250.0, "tax_amount": 0.0, "total": 250.0,
        "currency": "USD", "payment_terms": None,
        "raw_text": "edited by user",
    }
    resp = api_client.post(
        f"/api/runs/{seeded_run_id}/retry", json={"invoice": edited},
    )
    assert resp.status_code == 200
    new_run_id = resp.json()["run_id"]
    assert new_run_id != seeded_run_id

    new_state = api_client.get(f"/api/runs/{new_run_id}").json()
    assert new_state["parent_run_id"] == seeded_run_id
    assert new_state["invoice"]["invoice_number"] == "INV-X-edit"


def test_retry_404_for_unknown_parent(api_client: TestClient):
    valid_invoice = {
        "invoice_number": "INV-X",
        "vendor": "V",
        "date": None,
        "due_date": None,
        "line_items": [{"item": "WidgetA", "quantity": 1, "unit_price": 250.0, "notes": None}],
        "subtotal": 250.0,
        "tax_amount": 0.0,
        "total": 250.0,
        "currency": "USD",
        "payment_terms": None,
        "raw_text": "x",
    }
    resp = api_client.post("/api/runs/does-not-exist/retry", json={"invoice": valid_invoice})
    assert resp.status_code == 404
