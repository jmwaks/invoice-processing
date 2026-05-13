import asyncio
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
