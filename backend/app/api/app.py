from __future__ import annotations
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import build_router
from app.api.runs import RunRegistry
from app.config import get_settings
from app.db.init_db import init_db
from app.graph.builder import build_graph
from app.llm.grok_client import GrokClient

_SEED_PATH = Path(__file__).parent.parent / "db" / "seed.yaml"


def create_app(
    *, llm: GrokClient | None = None, db_path: Path | None = None, log_dir: Path | None = None,
) -> FastAPI:
    settings = get_settings()
    db_path = db_path or settings.invoice_processing_db_path
    log_dir = log_dir or settings.invoice_processing_log_dir
    if not db_path.exists():
        init_db(db_path, seed_path=_SEED_PATH, reset=True)
    if llm is None:
        # OpenAI SDK (>= 1.52) rejects an empty api_key at construction time.
        # Use a placeholder when no key is configured; actual calls will still fail,
        # but app construction and tests that mock the LLM proceed safely.
        api_key = settings.xai_api_key or "not-configured"
        llm = GrokClient(
            api_key=api_key, base_url=settings.xai_base_url, model=settings.xai_model,
        )
    registry = RunRegistry(log_dir=log_dir)
    paid: set[str] = set()
    graph = build_graph(llm=llm, db_path=db_path, log_dir=log_dir, paid_invoices=paid)
    app = FastAPI(title="Invoice Processing")
    app.add_middleware(
        CORSMiddleware, allow_origins=["http://localhost:5173"],
        allow_credentials=False, allow_methods=["*"], allow_headers=["*"],
    )
    app.include_router(build_router(registry=registry, db_path=db_path, graph=graph))
    return app


app = create_app()
