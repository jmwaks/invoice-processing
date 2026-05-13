import asyncio
import datetime as dt
from pathlib import Path

from app.api.runs import RunRegistry


def test_registry_creates_and_lists(tmp_path: Path):
    async def _run():
        reg = RunRegistry(log_dir=tmp_path)
        run = reg.create(source_path=str(tmp_path / "x.txt"), file_format="txt")
        assert run.run_id in reg.list_ids()
        assert reg.get(run.run_id) is run
    asyncio.run(_run())


def test_registry_subscribe_receives_events(tmp_path: Path):
    async def _run():
        reg = RunRegistry(log_dir=tmp_path)
        run = reg.create(source_path="x", file_format="txt")
        q = reg.subscribe(run.run_id)
        run.emitter.emit("node.start", node="ingest")
        ev = await asyncio.wait_for(q.get(), timeout=0.5)
        assert ev["kind"] == "node.start"
    asyncio.run(_run())


def test_create_seeded_carries_parent_and_invoice(tmp_path):
    from app.graph.state import InvoiceData, LineItem
    registry = RunRegistry(log_dir=tmp_path)
    invoice = InvoiceData(
        invoice_number="INV-X", vendor="V",
        date=None, due_date=None,
        line_items=[LineItem(item="WidgetA", quantity=1, unit_price=250.0)],
        subtotal=250.0, tax_amount=0.0, total=250.0,
        currency="USD", payment_terms=None, raw_text="",
    )
    run = registry.create_seeded(
        source_path="/tmp/x.txt", file_format="txt",
        invoice=invoice, parent_run_id="parent-id",
    )
    assert run.state.parent_run_id == "parent-id"
    assert run.state.invoice == invoice


def test_create_records_created_at(tmp_path):
    registry = RunRegistry(log_dir=tmp_path)
    before = dt.datetime.now(dt.UTC)
    run = registry.create(source_path="/tmp/x.txt", file_format="txt")
    after = dt.datetime.now(dt.UTC)
    assert run.created_at is not None
    assert before <= run.created_at <= after
    assert run.completed_at is None


def test_mark_done_records_completed_at(tmp_path):
    registry = RunRegistry(log_dir=tmp_path)
    run = registry.create(source_path="/tmp/x.txt", file_format="txt")
    registry.mark_done(run.run_id)
    assert run.completed_at is not None
    assert run.completed_at >= run.created_at
