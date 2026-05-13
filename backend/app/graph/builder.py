from __future__ import annotations
from pathlib import Path
from typing import Any
from langgraph.graph import StateGraph, END
from app.agents.approve import route_after_approve, run_approve
from app.agents.ingest import run_ingest
from app.agents.log_node import run_log
from app.agents.pay import run_pay
from app.agents.validate import run_validate
from app.graph.state import InvoiceState
from app.llm.grok_client import GrokClient
from app.logging_.event_emitter import EventEmitter


def _emitter_for(state: InvoiceState, log_dir: Path) -> EventEmitter:
    return EventEmitter(state.run_id, state.events, log_dir)


def build_graph(
    *, llm: GrokClient, db_path: Path, log_dir: Path,
    paid_invoices: set[str] | None = None,
) -> Any:  # noqa: ANN401
    if paid_invoices is None:
        paid_invoices = set()
    graph = StateGraph(InvoiceState)

    def ingest_node(state: InvoiceState) -> InvoiceState:
        return run_ingest(state, llm=llm, emitter=_emitter_for(state, log_dir))

    def validate_node(state: InvoiceState) -> InvoiceState:
        return run_validate(state, db_path=db_path, emitter=_emitter_for(state, log_dir))

    def approve_node(state: InvoiceState) -> InvoiceState:
        return run_approve(state, llm=llm, emitter=_emitter_for(state, log_dir))

    def pay_node(state: InvoiceState) -> InvoiceState:
        return run_pay(state, emitter=_emitter_for(state, log_dir), paid_invoices=paid_invoices)

    def log_node_fn(state: InvoiceState) -> InvoiceState:
        return run_log(state, emitter=_emitter_for(state, log_dir))

    graph.add_node("ingest", ingest_node)
    graph.add_node("validate", validate_node)
    graph.add_node("approve", approve_node)
    graph.add_node("pay", pay_node)
    graph.add_node("log", log_node_fn)

    graph.set_entry_point("ingest")
    graph.add_conditional_edges(
        "ingest",
        lambda s: "log" if s.error else "validate",
        {"validate": "validate", "log": "log"},
    )
    graph.add_edge("validate", "approve")
    graph.add_conditional_edges(
        "approve", route_after_approve, {"pay": "pay", "log": "log"},
    )
    graph.add_edge("pay", END)
    graph.add_edge("log", END)
    return graph.compile()
