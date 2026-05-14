from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel

from app.agents.homoglyph_check import detect_homoglyphs
from app.graph.state import InvoiceData, InvoiceState, SuspicionSignal
from app.llm.grok_client import GrokClient, LLMConfigurationError, LLMUnavailableError
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
  return null. (A null date is itself visible downstream — no signal needed.)
- Quantities are integers; preserve negative values as written.
- Flag suspicion signals for any of:
  * urgent / threatening language ("URGENT", "pay immediately", "wire transfer")
  * generic or alarming vendor names
  * unknown / made-up looking item names
  * homoglyph corruption: invoice numbers or dates where letters substitute
    for digits (O<->0, l<->1, I<->1, B<->8, S<->5, Z<->2), or the literal
    word "INVOICE" mangled (e.g. "INV0ICE"). Emit kind='homoglyph_corruption'
    with text_match set to the exact corrupted token from the source.
- Do NOT emit signals about dates, totals, arithmetic, or other claims
  derivable from the extracted fields — these are checked deterministically
  after extraction. Emit only signals about the wording, naming, or visual
  integrity of the source text. Valid kinds are: urgent_language,
  unknown_vendor_pattern, wire_transfer_demand, homoglyph_corruption, other.
- For each suspicion signal, when possible, set `text_match` to the EXACT verbatim
  phrase from the source that triggered the signal (e.g. "wire transfer required
  within 24 hours"). The phrase must appear in the source character-for-character.
  Omit `text_match` (return null) only when no single phrase captures the signal.
- Confidence is your self-assessment: 1.0 = perfect, 0.5 = needs human re-check, <0.3 = unreadable.

Return JSON matching this schema exactly:
{
  "invoice": {
    invoice_number, vendor, date, due_date,
    line_items:[{item, quantity, unit_price, notes}],
    subtotal, tax_amount, total, currency, payment_terms
  },
  "suspicion_signals": [{ kind, detail, severity, text_match }],
  "extraction_confidence": number
}
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
            on_attempt=lambda model: emitter.emit(
                "llm.attempt", node="ingest", model=model,
            ),
        )
    except (LLMUnavailableError, LLMConfigurationError):
        raise
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
    # Deterministic floor: ensure obvious homoglyph corruption is always flagged,
    # even if the LLM did not catch it. Dedup against signals the LLM already produced
    # so we do not double-emit the same text_match.
    existing_matches = {s.text_match for s in state.suspicion_signals if s.text_match}
    for sig in detect_homoglyphs(state.invoice):
        if sig.text_match in existing_matches:
            continue
        state.suspicion_signals.append(sig)
        if sig.text_match is not None:
            existing_matches.add(sig.text_match)
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
