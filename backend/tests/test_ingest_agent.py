from pathlib import Path
from unittest.mock import MagicMock
from app.graph.state import InvoiceState
from app.agents.ingest import run_ingest
from app.logging_.event_emitter import EventEmitter


def _mk_state(path: str, fmt: str = "txt") -> InvoiceState:
    return InvoiceState(run_id="r", source_path=path, file_format=fmt)


def test_ingest_populates_state_when_llm_returns_valid(tmp_path: Path):
    inv_file = tmp_path / "inv.txt"
    inv_file.write_text("INVOICE\nVendor: Widgets Inc.\nTotal: $1000\n")

    fake_meta = MagicMock(tokens_in=100, tokens_out=50, latency_ms=200, model="grok-4")
    llm = MagicMock()
    llm.structured_complete.return_value = (
        MagicMock(
            invoice=MagicMock(model_dump=lambda: {
                "invoice_number": "INV-1", "vendor": "Widgets Inc.",
                "date": None, "due_date": None, "line_items": [],
                "subtotal": 1000.0, "tax_amount": 0.0, "total": 1000.0,
                "currency": "USD", "payment_terms": None, "raw_text": "...",
            }),
            suspicion_signals=[],
            extraction_confidence=0.95,
        ),
        fake_meta,
    )

    state = _mk_state(str(inv_file))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_ingest(state, llm=llm, emitter=emitter)
    assert out.invoice is not None
    assert out.invoice.vendor == "Widgets Inc."
    assert out.extraction_confidence == 0.95
    assert any(e["kind"] == "ingest.complete" for e in out.events)
