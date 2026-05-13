from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def sample_api_client(tmp_path, seeded_db_path, monkeypatch):
    """A TestClient whose invoices dir contains a single known sample file."""
    from unittest.mock import MagicMock

    from app.api.app import create_app
    from app.config import get_settings

    # Build a sample invoices dir on tmp_path
    invoices_dir = tmp_path / "invoices"
    invoices_dir.mkdir()
    (invoices_dir / "INV-SAMPLE.txt").write_text(
        "Invoice\nVendor: Acme\nWidgetA x 1 @ $10\nTotal: $10\n"
    )

    # Patch the settings to point at our sample dir
    settings = get_settings()
    monkeypatch.setattr(settings, "invoice_processing_invoices_dir", invoices_dir)

    fake_llm = MagicMock()
    fake_llm.structured_complete.side_effect = RuntimeError("no LLM in sample test")
    app = create_app(llm=fake_llm, db_path=seeded_db_path, log_dir=tmp_path / "logs")
    return TestClient(app), invoices_dir


def test_sample_endpoint_creates_run_for_known_file(sample_api_client):
    client, _ = sample_api_client
    resp = client.post("/api/runs/sample/INV-SAMPLE.txt")
    assert resp.status_code == 200
    body = resp.json()
    assert "run_id" in body
    assert len(body["run_id"]) > 0


def test_sample_endpoint_returns_404_for_missing_file(sample_api_client):
    client, _ = sample_api_client
    resp = client.post("/api/runs/sample/does-not-exist.txt")
    assert resp.status_code == 404


def test_sample_endpoint_rejects_path_traversal_dot_dot(sample_api_client):
    client, _ = sample_api_client
    resp = client.post("/api/runs/sample/..%2Fetc%2Fpasswd")
    # FastAPI decodes; we then guard against ".." and slashes
    assert resp.status_code in (400, 404)


def test_sample_endpoint_rejects_filename_with_slash(sample_api_client):
    client, _ = sample_api_client
    resp = client.post("/api/runs/sample/subdir%2Ffile.txt")
    assert resp.status_code in (400, 404)
