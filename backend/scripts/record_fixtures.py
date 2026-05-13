"""Record Grok responses for every sample invoice for use as test fixtures.

Run once after setting XAI_API_KEY. Run again when prompts change.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.db.init_db import init_db
from app.graph.builder import build_graph
from app.graph.state import InvoiceState
from app.llm.grok_client import GrokClient
from app.parsers.file_loader import load_invoice_file
from tests.fixture_helpers import MockGrokClient


class RecordingClient(GrokClient):
    def __init__(self, base: GrokClient):
        self.base = base
        self.model = base.model

    def structured_complete(self, *, system, user, schema, max_retries=1):
        result, meta = self.base.structured_complete(
            system=system, user=user, schema=schema, max_retries=max_retries,
        )
        MockGrokClient.record(system, user, result,
                              tokens_in=meta.tokens_in, tokens_out=meta.tokens_out)
        return result, meta


def main():
    settings = get_settings()
    assert settings.xai_api_key, "Set XAI_API_KEY"
    db = settings.invoice_processing_db_path
    if not db.exists():
        init_db(db, seed_path=ROOT / "app" / "db" / "seed.yaml", reset=True)
    real = GrokClient(
        api_key=settings.xai_api_key,
        base_url=settings.xai_base_url,
        model=settings.xai_model,
    )
    recorder = RecordingClient(real)
    graph = build_graph(llm=recorder, db_path=db, log_dir=settings.invoice_processing_log_dir)

    invoices = sorted(p for p in settings.invoice_processing_invoices_dir.iterdir()
                      if p.suffix.lower() in {".txt", ".json", ".csv", ".xml", ".pdf"})
    for p in invoices:
        loaded = load_invoice_file(p)
        state = InvoiceState(
            run_id=f"rec-{p.stem}", source_path=str(p.resolve()), file_format=loaded.format,  # type: ignore[arg-type]
        )
        try:
            final = graph.invoke(state)
            outcome = final.get("decision").outcome if final.get("decision") else final.get("error")
            print(f"recorded {p.name}: {outcome}")
        except Exception as e:
            print(f"FAILED  {p.name}: {e}")


if __name__ == "__main__":
    main()
