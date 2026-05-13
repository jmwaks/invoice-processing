from app.graph.state import (
    InvoiceData,
    InvoiceState,
    SuspicionSignal,
    ValidationIssue,
    ValidationReport,
)
from app.rules.engine import evaluate_rules


def _state(total=1000.0, issues=None, signals=None, confidence=0.95) -> InvoiceState:
    return InvoiceState(
        run_id="r1", source_path="x", file_format="txt",
        invoice=InvoiceData(
            invoice_number="INV-1", vendor="Widgets Inc.", date=None, due_date=None,
            line_items=[], subtotal=total, tax_amount=0.0, total=total, raw_text="",
        ),
        suspicion_signals=signals or [],
        extraction_confidence=confidence,
        validation=ValidationReport(issues=issues or [], inventory_lookups=[], vendor_lookup=None),
    )


def test_auto_approve_when_clean_and_small():
    r = evaluate_rules(_state(total=1000.0))
    assert r.hard_blocks == []
    assert r.auto_approve is True
    assert r.scrutiny is False


def test_scrutiny_above_10k():
    r = evaluate_rules(_state(total=15000.0))
    assert r.auto_approve is False
    assert r.scrutiny is True


def test_hard_block_qty_exceeds_stock():
    issue = ValidationIssue(
        kind="qty_exceeds_stock", item="GadgetX", detail="20>5", severity="block"
    )
    r = evaluate_rules(_state(issues=[issue]))
    assert "qty_exceeds_stock" in r.hard_blocks
    assert r.auto_approve is False


def test_warn_triggers_scrutiny():
    issue = ValidationIssue(kind="price_mismatch", item="WidgetA", detail="", severity="warn")
    r = evaluate_rules(_state(issues=[issue]))
    assert r.scrutiny is True
    assert r.hard_blocks == []


def test_medium_suspicion_triggers_scrutiny():
    sig = SuspicionSignal(kind="urgent_language", detail="urgent", severity="medium")
    r = evaluate_rules(_state(signals=[sig]))
    assert r.scrutiny is True


def test_low_confidence_triggers_scrutiny():
    r = evaluate_rules(_state(confidence=0.6))
    assert r.scrutiny is True
    assert r.auto_approve is False
