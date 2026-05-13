from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.graph.state import InvoiceState
from app.logging_.event_emitter import EventEmitter


@dataclass
class Run:
    run_id: str
    state: InvoiceState
    emitter: EventEmitter
    subscribers: list[asyncio.Queue[dict[str, Any]]] = field(default_factory=list)
    done: bool = False


class _FanoutEmitter(EventEmitter):
    """Emitter that fans out to every subscriber on its parent Run."""
    _run: Run | None = None

    def emit(self, kind: str, **payload: Any) -> dict[str, Any]:
        event = super().emit(kind, **payload)
        if self._run is not None:
            for q in self._run.subscribers:
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    pass
        return event


class RunRegistry:
    def __init__(self, *, log_dir: Path):
        self.log_dir = log_dir
        self._runs: dict[str, Run] = {}

    def create(self, *, source_path: str, file_format: str) -> Run:
        run_id = uuid.uuid4().hex
        state = InvoiceState(run_id=run_id, source_path=source_path, file_format=file_format)  # type: ignore[arg-type]
        emitter = _FanoutEmitter(run_id, state.events, self.log_dir)
        run = Run(run_id=run_id, state=state, emitter=emitter)
        emitter._run = run
        self._runs[run_id] = run
        return run

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def list_ids(self) -> list[str]:
        return list(self._runs.keys())

    def subscribe(self, run_id: str) -> asyncio.Queue[dict[str, Any]]:
        run = self._runs[run_id]
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        for e in run.state.events:
            q.put_nowait(e)
        run.subscribers.append(q)
        return q

    def mark_done(self, run_id: str) -> None:
        run = self._runs.get(run_id)
        if run:
            run.done = True
            for q in run.subscribers:
                q.put_nowait({
                    "kind": "run.complete",
                    "ts": "",
                    "final_state": run.state.model_dump(mode="json"),
                })
