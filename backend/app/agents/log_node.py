from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app.graph.state import InvoiceState
from app.logging_.event_emitter import EventEmitter


def run_log(
    state: InvoiceState, *, emitter: EventEmitter, rejections_file: Path | None = None,
) -> InvoiceState:
    emitter.emit("node.start", node="log")
    rejections_file = rejections_file or emitter.log_dir / "rejections.jsonl"
    rejections_file.parent.mkdir(parents=True, exist_ok=True)

    record: dict[str, object]
    if state.error and state.invoice is None:
        record = {
            "run_id": state.run_id,
            "invoice_number": None,
            "vendor": None,
            "outcome": "unprocessable",
            "rationale": state.error,
            "rules_applied": [],
            "validation_issues": [],
            "suspicion_signals": [],
            "rejected_at": datetime.now(UTC).isoformat(),
        }
        emitter.emit("log.unprocessable_written", node="log", output=record)
    else:
        inv = state.invoice
        decision = state.decision
        record = {
            "run_id": state.run_id,
            "invoice_number": inv.invoice_number if inv else None,
            "vendor": inv.vendor if inv else None,
            "outcome": decision.outcome if decision else "rejected",
            "rationale": decision.rationale if decision else "",
            "rules_applied": decision.rules_applied if decision else [],
            "validation_issues": [
                i.model_dump() for i in (state.validation.issues if state.validation else [])
            ],
            "suspicion_signals": [s.model_dump() for s in state.suspicion_signals],
            "rejected_at": datetime.now(UTC).isoformat(),
        }
        emitter.emit("log.rejection_written", node="log", output=record)

    with rejections_file.open("a") as f:
        f.write(json.dumps(record, default=str) + "\n")
    emitter.emit("node.complete", node="log", output={"written": True})
    return state
