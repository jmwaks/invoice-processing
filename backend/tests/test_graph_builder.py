from pathlib import Path
from unittest.mock import MagicMock

from app.agents.ingest import IngestResponse
from app.db.init_db import init_db
from app.graph.builder import build_graph
from app.graph.state import Critique, InvoiceData, InvoiceState, LineItem, Proposal

BACKEND_DIR = Path(__file__).resolve().parents[1]
SEED = BACKEND_DIR / "app" / "db" / "seed.yaml"
INVOICE_1001 = BACKEND_DIR / "data" / "invoices" / "invoice_1001.txt"


def test_graph_compiles_and_runs_approved_path(tmp_path: Path):
    db = tmp_path / "t.db"
    init_db(db, seed_path=SEED, reset=True)

    ingest_inv = InvoiceData(
        invoice_number="INV-1001", vendor="Widgets Inc.",
        date=None, due_date=None,
        line_items=[LineItem(item="WidgetA", quantity=1, unit_price=250.0)],
        subtotal=250.0, tax_amount=0.0, total=250.0,
        currency="USD", payment_terms="Net 15", raw_text="",
    )
    ingest_resp = IngestResponse(
        invoice=ingest_inv, suspicion_signals=[], extraction_confidence=0.95,
    )
    meta = MagicMock(tokens_in=10, tokens_out=10, latency_ms=10, model="grok-4")

    proposal = Proposal(
        outcome="approved", rationale="ok",
        rules_applied=["auto_approve"], unresolved_concerns=[],
    )
    critique = Critique(agrees=True, objections=[], missed_signals=[], rule_misapplications=[])
    llm = MagicMock()
    llm.structured_complete.side_effect = [
        (ingest_resp, meta),
        (proposal, meta),
        (critique, meta),
        (proposal, meta),
    ]

    graph = build_graph(llm=llm, db_path=db, log_dir=tmp_path / "logs")
    init_state = InvoiceState(
        run_id="r-graph",
        source_path=str(INVOICE_1001),
        file_format="txt",
    )
    out = graph.invoke(init_state)
    assert out["decision"].outcome == "approved"
    assert out["payment_receipt"] is not None
