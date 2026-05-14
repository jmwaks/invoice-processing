"""End-to-end: process INV-1001 through pay (registry row written), then
process a second invoice with the same (vendor, invoice_number) through a
fresh paid_invoices set to simulate a cross-batch arrival. Asserts the
retroactive flag, the validation issue, the sidecar override, and the
effective_outcome composer."""

import json
from pathlib import Path

from app.agents.pay import run_pay
from app.agents.validate import run_validate
from app.api.decisions import effective_outcome
from app.db.init_db import init_db
from app.db.paid_invoices import lookup_paid
from app.graph.state import InvoiceData, InvoiceState, LineItem
from app.logging_.event_emitter import EventEmitter

SEED = Path(__file__).resolve().parent.parent / "app" / "db" / "seed.yaml"


def _state(run_id: str, invoice: InvoiceData) -> InvoiceState:
    return InvoiceState(
        run_id=run_id, source_path=f"{run_id}.txt", file_format="txt",
        invoice=invoice,
    )


def _invoice_1001() -> InvoiceData:
    return InvoiceData(
        invoice_number="INV-1001", vendor="Widgets Inc.",
        date=None, due_date=None,
        line_items=[
            LineItem(item="WidgetA", quantity=10, unit_price=250.0),
            LineItem(item="WidgetB", quantity=5, unit_price=500.0),
        ],
        subtotal=5000.0, tax_amount=0.0, total=5000.0,
        currency="USD", payment_terms=None, raw_text="",
    )


def _invoice_9002_resubmit() -> InvoiceData:
    return InvoiceData(
        invoice_number="INV-1001", vendor="Widgets Inc.",
        date=None, due_date=None,
        line_items=[LineItem(item="WidgetA", quantity=5, unit_price=250.0)],
        subtotal=None, tax_amount=None, total=1250.0,
        currency="USD", payment_terms=None, raw_text="",
    )


def test_cross_batch_dedup_retroactive_flag(tmp_path: Path) -> None:
    db = tmp_path / "inv.db"
    init_db(db, seed_path=SEED, reset=True)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    # ----- Batch 1: pay INV-1001 -----
    s1 = _state("run-1001", _invoice_1001())
    e1 = EventEmitter("run-1001", s1.events, log_dir)
    run_pay(s1, emitter=e1, paid_invoices=set(), db_path=db)
    # Need a recorded decision so effective_outcome has a base to read.
    (log_dir / "run-1001.jsonl").open("a").write(
        json.dumps({
            "kind": "approve.decision",
            "output": {"outcome": "approved", "rationale": "auto",
                       "rules_applied": ["auto_approve"]},
        }) + "\n"
    )

    assert lookup_paid(
        vendor="Widgets Inc.", invoice_number="INV-1001", db_path=db,
    ) is not None

    # ----- Batch 2: validate the re-submit (fresh in-memory set) -----
    s2 = _state("run-9002", _invoice_9002_resubmit())
    e2 = EventEmitter("run-9002", s2.events, log_dir)
    out = run_validate(s2, db_path=db, emitter=e2)

    # (a) duplicate_invoice issue on the new run
    kinds = {i.kind for i in out.validation.issues}
    assert "duplicate_invoice" in kinds

    # (b) retroactive event appended to prior log
    prior_events = [
        json.loads(line) for line in (log_dir / "run-1001.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert any(e.get("kind") == "duplicate_detected_retroactive" for e in prior_events)

    # (c) sidecar override row exists
    sidecar = log_dir / "decision_updates.jsonl"
    rows = [json.loads(line) for line in sidecar.read_text().splitlines() if line.strip()]
    matching = [r for r in rows if r["run_id"] == "run-1001"]
    assert len(matching) == 1 and matching[0]["new_outcome"] == "needs_review"

    # (d) effective_outcome composer flips INV-1001 to needs_review
    eo = effective_outcome("run-1001", log_dir=log_dir)
    assert eo.outcome == "needs_review"
    assert eo.override_reason == "duplicate_detected"
    assert eo.triggered_by_run_id == "run-9002"
