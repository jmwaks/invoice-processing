from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel

from app.graph.state import InvoiceData, InvoiceState, SuspicionSignal
from app.llm.grok_client import GrokClient
from app.logging_.event_emitter import EventEmitter
from app.parsers.file_loader import load_invoice_file

_logger = logging.getLogger(__name__)


class IngestResponse(BaseModel):
    invoice: InvoiceData
    suspicion_signals: list[SuspicionSignal] = []
    extraction_confidence: float


SYSTEM_PROMPT = """You are an invoice extractor.
Convert the provided invoice text into a structured JSON object.

Rules:
- Extract values verbatim from the source. Do not invent values.
- If a field is missing or unreadable, return null. Do not guess.
- Dates use YYYY-MM-DD. If the source says "yesterday" or another relative term,
  return null and note it as a suspicion signal.
- Quantities are integers; preserve negative values as written.
- Flag suspicion signals for any of:
  * urgent / threatening language ("URGENT", "pay immediately", "wire transfer")
  * dates in the past or expressed as "yesterday"
  * round-number totals on otherwise odd line items
  * generic or alarming vendor names
  * unknown / made-up looking item names
- Confidence is your self-assessment: 1.0 = perfect, 0.5 = needs human re-check, <0.3 = unreadable.

Return JSON matching this schema exactly:
{
  "invoice": {
    invoice_number, vendor, date, due_date,
    line_items:[{item, quantity, unit_price, notes}],
    subtotal, tax_amount, total, currency, payment_terms, raw_text
  },
  "suspicion_signals": [{ kind, detail, severity }],
  "extraction_confidence": number
}
The raw_text field should echo the input text exactly.
"""


def run_ingest(state: InvoiceState, *, llm: GrokClient, emitter: EventEmitter) -> InvoiceState:
    emitter.emit("node.start", node="ingest")

    if state.invoice is not None:
        emitter.emit("ingest.skipped", node="ingest", reason="invoice pre-seeded (retry path)")
        emitter.emit("node.complete", node="ingest", output={
            "vendor": state.invoice.vendor,
            "total": state.invoice.total,
            "skipped": True,
        })
        return state

    path = Path(state.source_path)

    try:
        loaded = load_invoice_file(path)
        state.file_format = loaded.format
    except Exception as e:
        _logger.exception("ingest: file load failed for %s", state.source_path)
        state.error = f"unprocessable: {e}"
        emitter.emit("node.complete", node="ingest", output={"error": state.error})
        return state

    user = f"Source format: {loaded.format}\n\nInvoice content:\n{loaded.text}"
    try:
        parsed, meta = llm.structured_complete(
            system=SYSTEM_PROMPT, user=user, schema=IngestResponse, max_retries=1,
        )
    except Exception as e:
        _logger.exception("ingest: LLM extraction failed for %s", state.source_path)
        state.error = f"unprocessable: extraction failed ({e})"
        emitter.emit("ingest.retry", node="ingest", reason="pydantic validation exhausted")
        emitter.emit("node.complete", node="ingest", output={"error": state.error})
        return state

    emitter.emit(
        "llm.call", node="ingest",
        tokens_in=meta.tokens_in, tokens_out=meta.tokens_out,
        latency_ms=meta.latency_ms, model=meta.model,
        prompt_chars=len(user), response_chars=0,
    )
    state.invoice = InvoiceData(**parsed.invoice.model_dump())
    state.invoice.raw_text = loaded.text
    state.suspicion_signals = parsed.suspicion_signals
    state.extraction_confidence = parsed.extraction_confidence
    emitter.emit("node.complete", node="ingest", output={
        "vendor": state.invoice.vendor,
        "total": state.invoice.total,
        "confidence": parsed.extraction_confidence,
        "suspicion_count": len(parsed.suspicion_signals),
    })
    emitter.emit(
        "ingest.complete",
        vendor=state.invoice.vendor,
        total=state.invoice.total,
        confidence=parsed.extraction_confidence,
    )
    return state
