from __future__ import annotations
import asyncio
import logging
import sqlite3
import tempfile
from pathlib import Path
from typing import Any
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from app.api.runs import RunRegistry
from app.api.sse import sse_response
from app.parsers.file_loader import load_invoice_file

_logger = logging.getLogger(__name__)


def build_router(*, registry: RunRegistry, db_path: Path, graph) -> APIRouter:
    router = APIRouter(prefix="/api")

    async def _run_graph(run_id: str) -> None:
        run = registry.get(run_id)
        if run is None:
            return
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, graph.invoke, run.state)
        except Exception as e:
            _logger.exception("graph run failed for %s", run_id)
            run.emitter.emit("run.error", error=str(e))
        finally:
            registry.mark_done(run_id)

    @router.post("/runs")
    async def create_run(file: UploadFile = File(...)) -> dict[str, str]:
        suffix = Path(file.filename or "upload").suffix or ".txt"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
            tf.write(await file.read())
            tmp_path = Path(tf.name)
        loaded = load_invoice_file(tmp_path)
        run = registry.create(source_path=str(tmp_path), file_format=loaded.format)
        asyncio.create_task(_run_graph(run.run_id))
        return {"run_id": run.run_id}

    @router.get("/runs/{run_id}/events")
    async def stream_events(run_id: str, request: Request):
        run = registry.get(run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        q = registry.subscribe(run_id)
        return sse_response(q)

    @router.get("/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        run = registry.get(run_id)
        if run is None:
            raise HTTPException(404)
        return run.state.model_dump(mode="json")

    @router.get("/runs")
    async def list_runs() -> list[dict]:
        return [_summary(registry.get(rid).state) for rid in registry.list_ids()]

    @router.get("/runs/{run_id}/source")
    async def get_source(run_id: str) -> dict[str, str]:
        run = registry.get(run_id)
        if run is None:
            raise HTTPException(404)
        text = Path(run.state.source_path).read_text(encoding="utf-8", errors="replace")
        return {"text": text, "format": run.state.file_format}

    @router.post("/runs/batch")
    async def run_batch() -> dict:
        from app.config import get_settings
        settings = get_settings()
        invoices = sorted(p for p in settings.invoice_processing_invoices_dir.iterdir()
                          if p.suffix.lower() in {".txt", ".json", ".csv", ".xml", ".pdf"})
        # Create runs synchronously up-front so run_ids is complete before return
        runs = []
        for p in invoices:
            loaded = load_invoice_file(p)
            run = registry.create(source_path=str(p), file_format=loaded.format)
            runs.append(run)
        sem = asyncio.Semaphore(4)

        async def _one(run_id: str) -> None:
            async with sem:
                await _run_graph(run_id)

        for r in runs:
            asyncio.create_task(_one(r.run_id))
        return {"run_ids": [r.run_id for r in runs], "total": len(invoices)}

    @router.get("/inventory")
    async def inventory() -> dict:
        conn = sqlite3.connect(db_path)
        try:
            inv = [
                {"item": row[0], "stock": row[1], "unit_price": row[2]}
                for row in conn.execute("SELECT item, stock, unit_price FROM inventory ORDER BY item")
            ]
            vendors = [
                {"name": row[0], "display_name": row[1], "status": row[2]}
                for row in conn.execute("SELECT name, display_name, status FROM vendors ORDER BY display_name")
            ]
        finally:
            conn.close()
        return {"inventory": inv, "vendors": vendors}

    return router


def _summary(state) -> dict:
    decision = state.decision
    inv = state.invoice
    return {
        "run_id": state.run_id,
        "source_path": state.source_path,
        "invoice_number": inv.invoice_number if inv else None,
        "vendor": inv.vendor if inv else None,
        "total": inv.total if inv else None,
        "outcome": (decision.outcome if decision else ("unprocessable" if state.error else "running")),
        "error": state.error,
    }
