import json
from pathlib import Path
from unittest.mock import MagicMock

from app.agents.ingest import run_ingest
from app.graph.state import InvoiceData, InvoiceState, LineItem
from app.logging_.event_emitter import EventEmitter
from app.llm.grok_client import GrokClient


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


def test_ingest_skips_llm_when_invoice_already_seeded(tmp_path: Path):
    """If state.invoice is already populated, ingest must not call the LLM
    — this is the seed path used by retry."""

    class _PoisonedLLM:
        def structured_complete(self, **kwargs):
            raise AssertionError("LLM must not be called when invoice is pre-seeded")

    src = tmp_path / "src.txt"
    src.write_text("ignored — not used because invoice is seeded")

    pre_invoice = InvoiceData(
        invoice_number="INV-X",
        vendor="Test Vendor",
        date=None, due_date=None,
        line_items=[LineItem(item="WidgetA", quantity=1, unit_price=250.0)],
        subtotal=250.0, tax_amount=0.0, total=250.0,
        currency="USD", payment_terms=None,
        raw_text="ignored",
    )
    state = InvoiceState(
        run_id="r1", source_path=str(src), file_format="txt",
        invoice=pre_invoice, parent_run_id="parent",
    )
    emitter = EventEmitter("r1", state.events, tmp_path / "logs")

    out = run_ingest(state, llm=_PoisonedLLM(), emitter=emitter)

    assert out.invoice is pre_invoice
    assert any(e["kind"] == "ingest.skipped" for e in state.events)


def test_ingest_passes_text_match_through_from_llm(monkeypatch, tmp_path):
    """The ingest agent must propagate text_match from the LLM response to state."""
    from unittest.mock import MagicMock
    from pathlib import Path

    from app.agents.ingest import IngestResponse, run_ingest
    from app.graph.state import InvoiceData, InvoiceState, SuspicionSignal
    from app.logging_.event_emitter import EventEmitter

    invoice_text = "URGENT — wire transfer required within 24 hours. Vendor: X. Total: $100."
    src = tmp_path / "inv.txt"
    src.write_text(invoice_text)

    fake_invoice = InvoiceData(
        invoice_number="X-1", vendor="X", date=None, due_date=None,
        line_items=[], subtotal=None, tax_amount=None, total=100.0, raw_text=invoice_text,
    )
    fake_response = IngestResponse(
        invoice=fake_invoice,
        suspicion_signals=[
            SuspicionSignal(
                kind="wire_transfer_demand",
                detail="demands wire within 24 hours",
                severity="high",
                text_match="wire transfer required within 24 hours",
            ),
        ],
        extraction_confidence=0.9,
    )
    fake_meta = MagicMock(tokens_in=1, tokens_out=1, latency_ms=1, model="fake")

    fake_llm = MagicMock()
    fake_llm.structured_complete.return_value = (fake_response, fake_meta)

    state = InvoiceState(run_id="r1", source_path=str(src), file_format="txt")
    emitter = EventEmitter("r1", state.events, tmp_path)
    out = run_ingest(state, llm=fake_llm, emitter=emitter)

    assert len(out.suspicion_signals) == 1
    assert out.suspicion_signals[0].text_match == "wire transfer required within 24 hours"


def test_homoglyph_post_check_emits_signal_even_when_llm_misses_it(tmp_path: Path) -> None:
    """Layer B is the floor: even if the LLM returns no suspicion_signals,
    the deterministic post-check must add one for an obviously corrupted invoice."""
    from unittest.mock import MagicMock
    from app.agents.ingest import IngestResponse, run_ingest
    from app.graph.state import InvoiceData, InvoiceState, LineItem
    from app.llm.grok_client import CallMeta
    from app.logging_.event_emitter import EventEmitter

    raw = (
        "INV0ICE\n"
        "Vendor: Atlas Industrial Supply\n"
        "Invoice Number: INV-9OO1\n"
        "Date: 2026-O2-O3\nDue Date: 2026-03-03\n"
        "Items:\n  Widget A    qty: 5    unit price: $250\nTotal: $1,250\n"
    )
    source = tmp_path / "invoice_9001.txt"
    source.write_text(raw)

    fake_llm = MagicMock()
    fake_llm.structured_complete.return_value = (
        IngestResponse(
            invoice=InvoiceData(
                invoice_number="INV-9OO1",
                vendor="Atlas Industrial Supply",
                date=None, due_date=None,
                line_items=[LineItem(item="Widget A", quantity=5, unit_price=250.0)],
                subtotal=None, tax_amount=None, total=1250.0,
                currency="USD", payment_terms="Net 30",
                raw_text=raw,
            ),
            suspicion_signals=[],
            extraction_confidence=0.9,
        ),
        CallMeta(tokens_in=100, tokens_out=50, latency_ms=120, model="stub"),
    )

    state = InvoiceState(
        run_id="r", source_path=str(source), file_format="txt",
    )
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_ingest(state, llm=fake_llm, emitter=emitter)

    kinds = [s.kind for s in out.suspicion_signals]
    assert "homoglyph_corruption" in kinds, (
        f"expected post-check to emit homoglyph_corruption, got {kinds}"
    )


def _make_sdk_returning(content: str) -> MagicMock:
    """Build a MagicMock that mimics the OpenAI SDK shape `structured_complete` consumes."""
    sdk = MagicMock()
    sdk.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=content))],
        usage=MagicMock(prompt_tokens=10, completion_tokens=5),
    )
    return sdk


def test_ingest_hydrates_raw_text_from_disk_when_llm_omits_it(tmp_path: Path):
    """LLM is no longer asked to echo raw_text (saves ~30% output tokens).
    Ingest must still produce state.invoice.raw_text == loaded.text by
    overwriting whatever the response held."""
    invoice_text = "INVOICE\nVendor: Widgets Inc.\nTotal: $1000\n"
    inv_file = tmp_path / "inv.txt"
    inv_file.write_text(invoice_text)

    # Response omits raw_text entirely — schema default ("") applies.
    response = json.dumps({
        "invoice": {
            "invoice_number": "INV-1", "vendor": "Widgets Inc.",
            "date": None, "due_date": None, "line_items": [],
            "subtotal": 1000.0, "tax_amount": 0.0, "total": 1000.0,
            "currency": "USD", "payment_terms": None,
        },
        "suspicion_signals": [],
        "extraction_confidence": 0.9,
    })
    sdk = _make_sdk_returning(response)
    llm = GrokClient(sdk=sdk, model="grok-3-test")

    state = _mk_state(str(inv_file))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_ingest(state, llm=llm, emitter=emitter)

    assert out.error is None
    assert out.invoice is not None
    # Hydrated from disk, not from the LLM.
    assert out.invoice.raw_text == invoice_text


def test_ingest_rejects_llm_response_with_banned_suspicion_kind(tmp_path: Path):
    """If the LLM emits a banned kind (e.g., impossible_date), pydantic must reject
    the response and run_ingest must mark the state as unprocessable.
    Regression guard for the INV-1006 cascade if the prompt drifts."""
    inv_file = tmp_path / "inv.txt"
    inv_file.write_text("INVOICE\nVendor: Widgets Inc.\nTotal: $1000\n")

    bad_response = json.dumps({
        "invoice": {
            "invoice_number": "INV-1", "vendor": "Widgets Inc.",
            "date": "2026-01-25", "due_date": None, "line_items": [],
            "subtotal": 1000.0, "tax_amount": 0.0, "total": 1000.0,
            "currency": "USD", "payment_terms": None, "raw_text": "...",
        },
        "suspicion_signals": [
            {"kind": "impossible_date", "detail": "Date is in the future",
             "severity": "high", "text_match": None},
        ],
        "extraction_confidence": 0.9,
    })

    sdk = _make_sdk_returning(bad_response)
    llm = GrokClient(sdk=sdk, model="grok-3-test")

    state = _mk_state(str(inv_file))
    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_ingest(state, llm=llm, emitter=emitter)

    assert out.error is not None
    assert out.error.startswith("unprocessable: extraction failed")
    # The SDK was called at least once (structured_complete may retry).
    assert sdk.chat.completions.create.call_count >= 1
