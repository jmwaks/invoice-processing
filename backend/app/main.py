from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.db.init_db import init_db
from app.graph.builder import build_graph
from app.graph.state import InvoiceState
from app.llm.grok_client import GrokClient
from app.parsers.file_loader import load_invoice_file

# Resolve seed path relative to this file so it works regardless of CWD.
_SEED_PATH = Path(__file__).parent / "db" / "seed.yaml"


def _format_summary(final: dict[str, Any]) -> str:
    decision: dict[str, Any] | None = final.get("decision")
    receipt: dict[str, Any] | None = final.get("payment_receipt")
    inv: dict[str, Any] | None = final.get("invoice")
    vendor = inv.get("vendor") if inv is not None else None
    total = inv.get("total") if inv is not None else None
    lines = [
        f"Run:        {final.get('run_id')}",
        f"File:       {final.get('source_path')}",
        f"Vendor:     {vendor}",
        f"Amount:     ${total}" if total is not None else "Amount:     -",
        f"Outcome:    {decision['outcome'] if decision else final.get('error', 'unknown')}",
    ]
    if decision:
        lines.append(f"Rules:      {', '.join(decision['rules_applied']) or '-'}")
        lines.append("Rationale:")
        for line in str(decision.get("rationale", "")).splitlines():
            lines.append(f"  {line}")
    if receipt:
        lines.append(f"Receipt:    {receipt['transaction_id']} at {receipt['paid_at']}")
    return "\n".join(lines)


def _build_runtime(settings: Any) -> tuple[GrokClient, Any, set[str]]:
    """Build the shared GrokClient and compiled graph once for all runs."""
    db = settings.invoice_processing_db_path
    if not db.exists():
        init_db(db, seed_path=_SEED_PATH, reset=True)
    llm = GrokClient(
        api_key=settings.xai_api_key,
        base_url=settings.xai_base_url,
        model=settings.xai_model,
    )
    paid: set[str] = set()
    graph = build_graph(
        llm=llm, db_path=db, log_dir=settings.invoice_processing_log_dir,
        paid_invoices=paid,
    )
    return llm, graph, paid


def run_one(invoice_path: Path, *, graph: Any) -> dict[str, Any]:
    loaded = load_invoice_file(invoice_path)
    state = InvoiceState(
        run_id=uuid.uuid4().hex,
        source_path=str(invoice_path.resolve()),
        file_format=loaded.format,
    )
    return graph.invoke(state)  # type: ignore[no-any-return]


def main() -> int:
    ap = argparse.ArgumentParser(prog="invoice-processor")
    ap.add_argument("--invoice_path", type=Path, help="Path to a single invoice file")
    ap.add_argument("--batch", action="store_true",
                    help="Run all invoices in INVOICE_PROCESSING_INVOICES_DIR")
    ap.add_argument("--json", action="store_true", help="Print final state as JSON")
    args = ap.parse_args()
    settings = get_settings()
    _llm, graph, _paid = _build_runtime(settings)

    if args.batch:
        paths = sorted(p for p in settings.invoice_processing_invoices_dir.iterdir()
                       if p.suffix.lower() in {".txt", ".json", ".csv", ".xml", ".pdf"})
        for p in paths:
            print(f"\n=== {p.name} ===")
            final = run_one(p, graph=graph)
            print(_format_summary(final))
        return 0

    if args.invoice_path is None:
        ap.error("--invoice_path is required unless --batch is set")
    final = run_one(args.invoice_path, graph=graph)
    if args.json:
        print(json.dumps(final, default=str, indent=2))
    else:
        print(_format_summary(final))
    return 0


if __name__ == "__main__":
    sys.exit(main())
