import os
from pathlib import Path
import pytest
from app.config import get_settings
from app.llm.grok_client import GrokClient
from app.graph.state import InvoiceState
from app.agents.ingest import run_ingest
from app.logging_.event_emitter import EventEmitter

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_TESTS") != "1", reason="set RUN_LIVE_TESTS=1 to run"
)


def test_live_ingest_inv_1001(tmp_path: Path):
    settings = get_settings()
    assert settings.xai_api_key, "Set XAI_API_KEY in .env"
    llm = GrokClient(
        api_key=settings.xai_api_key, base_url=settings.xai_base_url, model=settings.xai_model,
    )
    state = InvoiceState(
        run_id="live-1", source_path="data/invoices/invoice_1001.txt", file_format="txt",
    )
    emitter = EventEmitter("live-1", state.events, tmp_path / "logs")
    out = run_ingest(state, llm=llm, emitter=emitter)
    assert out.invoice is not None
    assert out.invoice.vendor and "widgets" in out.invoice.vendor.lower()
    assert out.invoice.total == 5000.0 or out.invoice.subtotal == 5000.0
