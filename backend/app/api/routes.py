from __future__ import annotations

import asyncio
import logging
import sqlite3
import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.api.runs import Run, RunRegistry
from app.api.sse import sse_response
from app.graph.state import InvoiceData, InvoiceState
from app.parsers.file_loader import load_invoice_file

_logger = logging.getLogger(__name__)


class _RetryRequest(BaseModel):
    invoice: InvoiceData


def build_router(*, registry: RunRegistry, db_path: Path, graph: Any) -> APIRouter:
    router = APIRouter(prefix="/api")

    async def _run_graph(run_id: str) -> None:
        run = registry.get(run_id)
        if run is None:
            return
        loop = asyncio.get_event_loop()
        try:
            final = await loop.run_in_executor(None, graph.invoke, run.state)
            # LangGraph returns the final state as a dict; sync it back so
            # /api/runs summaries reflect the actual outcome instead of "running".
            run.state = InvoiceState.model_validate(final)
        except Exception as e:
            _logger.exception("graph run failed for %s", run_id)
            run.state.error = f"graph crashed: {e}"
            run.emitter.emit("run.error", error=str(e))
        finally:
            registry.mark_done(run_id)

    @router.post("/runs")
    async def create_run(file: Annotated[UploadFile, File()]) -> dict[str, str]:
        suffix = Path(file.filename or "upload").suffix or ".txt"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
            tf.write(await file.read())
            tmp_path = Path(tf.name)
        loaded = load_invoice_file(tmp_path)
        run = registry.create(source_path=str(tmp_path), file_format=loaded.format)
        asyncio.create_task(_run_graph(run.run_id))
        return {"run_id": run.run_id}

    @router.post("/runs/{run_id}/retry")
    async def retry_run(run_id: str, body: _RetryRequest) -> dict[str, str]:
        parent = registry.get(run_id)
        if parent is None:
            raise HTTPException(404)
        new_run = registry.create_seeded(
            source_path=parent.state.source_path,
            file_format=parent.state.file_format,
            invoice=body.invoice,
            parent_run_id=run_id,
        )
        asyncio.create_task(_run_graph(new_run.run_id))
        return {"run_id": new_run.run_id}

    @router.get("/runs/{run_id}/events")
    async def stream_events(run_id: str, request: Request) -> EventSourceResponse:
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
    async def list_runs() -> list[dict[str, Any]]:
        runs: list[Run | None] = [registry.get(rid) for rid in registry.list_ids()]
        return [_summary(r.state) for r in runs if r is not None]

    @router.get("/runs/{run_id}/source")
    async def get_source(run_id: str) -> dict[str, str]:
        run = registry.get(run_id)
        if run is None:
            raise HTTPException(404)
        text = Path(run.state.source_path).read_text(encoding="utf-8", errors="replace")
        return {"text": text, "format": run.state.file_format}

    @router.post("/runs/batch")
    async def run_batch() -> dict[str, Any]:
        from app.config import get_settings
        settings = get_settings()
        valid_exts = {".txt", ".json", ".csv", ".xml", ".pdf"}
        invoices = sorted(
            p for p in settings.invoice_processing_invoices_dir.iterdir()
            if p.suffix.lower() in valid_exts
        )
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

    @router.get("/metrics")
    async def metrics() -> dict[str, Any]:
        from app.config import get_settings
        manual_cost = get_settings().manual_cost_per_invoice_usd

        total = 0
        approved = 0
        rejected = 0
        needs_review = 0
        unprocessable = 0
        dollars_approved = 0.0
        durations_s: list[float] = []

        for rid in registry.list_ids():
            run = registry.get(rid)
            if run is None:
                continue
            total += 1
            decision = run.state.decision
            if decision is not None:
                if decision.outcome == "approved":
                    approved += 1
                    if run.state.invoice and run.state.invoice.total:
                        dollars_approved += float(run.state.invoice.total)
                elif decision.outcome == "rejected":
                    rejected += 1
                elif decision.outcome == "needs_review":
                    needs_review += 1
            elif run.state.error:
                unprocessable += 1

            if run.completed_at is not None and run.created_at is not None:
                durations_s.append((run.completed_at - run.created_at).total_seconds())

        avg_run_seconds = (sum(durations_s) / len(durations_s)) if durations_s else None
        return {
            "total_runs": total,
            "approved_count": approved,
            "rejected_count": rejected,
            "needs_review_count": needs_review,
            "unprocessable_count": unprocessable,
            "total_dollars_approved": round(dollars_approved, 2),
            "simulated_dollars_saved": round(total * manual_cost, 2),
            "avg_run_seconds": round(avg_run_seconds, 2) if avg_run_seconds is not None else None,
            "manual_cost_per_invoice_usd": manual_cost,
        }

    @router.get("/inventory")
    async def inventory() -> dict[str, Any]:
        conn = sqlite3.connect(db_path)
        try:
            inv = [
                {"item": row[0], "stock": row[1], "unit_price": row[2]}
                for row in conn.execute(
                    "SELECT item, stock, unit_price FROM inventory ORDER BY item"
                )
            ]
            vendors = [
                {"name": row[0], "display_name": row[1], "status": row[2]}
                for row in conn.execute(
                    "SELECT name, display_name, status FROM vendors ORDER BY display_name"
                )
            ]
        finally:
            conn.close()
        return {"inventory": inv, "vendors": vendors}

    return router


def _summary(state: InvoiceState) -> dict[str, Any]:
    decision = state.decision
    inv = state.invoice
    return {
        "run_id": state.run_id,
        "parent_run_id": state.parent_run_id,
        "source_path": state.source_path,
        "invoice_number": inv.invoice_number if inv else None,
        "vendor": inv.vendor if inv else None,
        "total": inv.total if inv else None,
        "outcome": (
            decision.outcome if decision else ("unprocessable" if state.error else "running")
        ),
        "error": state.error,
    }
