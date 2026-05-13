import json
from pathlib import Path

from app.logging_.event_emitter import EventEmitter


def test_emitter_writes_to_state_and_file(tmp_path: Path):
    log_dir = tmp_path / "logs"
    state_events: list[dict] = []
    emitter = EventEmitter(run_id="r1", state_events=state_events, log_dir=log_dir)
    emitter.emit("node.start", node="ingest")
    emitter.emit("node.complete", node="ingest", output={"x": 1})
    assert len(state_events) == 2
    assert state_events[0]["kind"] == "node.start"
    assert "ts" in state_events[0]
    log_file = log_dir / "r1.jsonl"
    assert log_file.exists()
    lines = log_file.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["kind"] == "node.complete"


def test_emitter_queue_receives(tmp_path: Path):
    import asyncio

    async def _run():
        q: asyncio.Queue = asyncio.Queue()
        emitter = EventEmitter(run_id="r2", state_events=[], log_dir=tmp_path / "logs", queue=q)
        emitter.emit("node.start", node="ingest")
        event = await asyncio.wait_for(q.get(), timeout=0.5)
        assert event["kind"] == "node.start"

    asyncio.run(_run())
