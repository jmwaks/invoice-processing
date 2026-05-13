import json
from pathlib import Path

from app.agents.log_node import run_log
from app.graph.state import (
    Critique,
    Decision,
    InvoiceData,
    InvoiceState,
    Proposal,
    ValidationReport,
)
from app.logging_.event_emitter import EventEmitter


def _rejected_state(tmp_path: Path) -> InvoiceState:
    p = Proposal(
        outcome="rejected", rationale="bad",
        rules_applied=["hard_block:out_of_stock"], unresolved_concerns=[],
    )
    c = Critique(agrees=True, objections=[], missed_signals=[], rule_misapplications=[])
    return InvoiceState(
        run_id="r-rej", source_path="x", file_format="txt",
        invoice=InvoiceData(
            invoice_number="INV-X", vendor="Fraudster LLC", date=None, due_date=None,
            line_items=[], subtotal=100.0, tax_amount=0.0, total=100.0,
            raw_text="", payment_terms=None,
        ),
        decision=Decision(
            outcome="rejected", rationale="bad",
            rules_applied=["hard_block:out_of_stock"],
            initial_proposal=p, critique=c, final_proposal=p,
        ),
        validation=ValidationReport(issues=[], inventory_lookups=[], vendor_lookup=None),
    )


def test_log_writes_rejection_record(tmp_path: Path):
    state = _rejected_state(tmp_path)
    emitter = EventEmitter("r-rej", state.events, tmp_path / "logs")
    rejections_file = tmp_path / "logs" / "rejections.jsonl"
    run_log(state, emitter=emitter, rejections_file=rejections_file)
    assert rejections_file.exists()
    record = json.loads(rejections_file.read_text().splitlines()[-1])
    assert record["outcome"] == "rejected"
    assert record["vendor"] == "Fraudster LLC"


def test_log_writes_unprocessable_record(tmp_path: Path):
    state = InvoiceState(
        run_id="r-bad", source_path="x", file_format="txt", error="unprocessable: foo"
    )
    emitter = EventEmitter("r-bad", state.events, tmp_path / "logs")
    rejections_file = tmp_path / "logs" / "rejections.jsonl"
    run_log(state, emitter=emitter, rejections_file=rejections_file)
    record = json.loads(rejections_file.read_text().splitlines()[-1])
    assert record["outcome"] == "unprocessable"
