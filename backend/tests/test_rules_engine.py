import datetime as dt
from pathlib import Path

from app.agents.validate import run_validate
from app.db.init_db import init_db
from app.graph.state import (
    InvoiceData,
    InvoiceState,
    LineItem,
    SuspicionSignal,
    ValidationIssue,
    ValidationReport,
)
from app.logging_.event_emitter import EventEmitter
from app.rules.engine import evaluate_rules

SEED = Path(__file__).resolve().parents[1] / "app" / "db" / "seed.yaml"


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


def test_inv_1006_regression_past_date_round_total_clean_signals(tmp_path: Path):
    """INV-1006 cascade regression: an invoice with a past date and round line
    items must reach auto_approve=True when the LLM emits no suspicion signals
    (i.e., when the prompt no longer asks the LLM to make claims it can't verify)."""
    db = tmp_path / "t.db"
    init_db(db, seed_path=SEED, reset=True)

    invoice = InvoiceData(
        invoice_number="INV-1006",
        vendor="Acme Industrial Supplies",
        date=dt.date(2026, 1, 25),
        due_date=dt.date(2026, 2, 10),
        line_items=[
            LineItem(item="WidgetA", quantity=5, unit_price=250.0),
            LineItem(item="WidgetB", quantity=3, unit_price=500.0),
        ],
        subtotal=2750.0,
        tax_amount=0.0,
        total=2750.0,
        currency="USD",
        payment_terms="Net 15",
        raw_text="...",
    )
    state = InvoiceState(
        run_id="r", source_path="x", file_format="txt", invoice=invoice,
    )
    # Simulate a well-behaved LLM: no suspicion signals emitted.
    state.suspicion_signals = []
    state.extraction_confidence = 0.9

    emitter = EventEmitter("r", state.events, tmp_path / "logs")
    out = run_validate(
        state, db_path=db, emitter=emitter, today=dt.date(2026, 5, 13),
    )

    # No future_date issue (the date is in the past).
    assert not any(i.kind == "future_date" for i in out.validation.issues)
    # No deterministic blockers or warnings should fire for this clean invoice.
    assert not any(i.severity in ("block", "warn") for i in out.validation.issues), \
        f"unexpected issues: {[i.model_dump() for i in out.validation.issues]}"

    evaluation = evaluate_rules(out)
    assert evaluation.auto_approve is True, (
        f"INV-1006 should auto-approve under the new pipeline; "
        f"evaluation={evaluation}"
    )
    assert evaluation.scrutiny is False
    assert evaluation.hard_blocks == []
