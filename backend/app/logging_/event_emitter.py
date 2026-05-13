from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)


class EventEmitter:
    def __init__(
        self,
        run_id: str,
        state_events: list[dict[str, Any]],
        log_dir: Path,
        queue: asyncio.Queue[dict[str, Any]] | None = None,
    ) -> None:
        self.run_id = run_id
        self.state_events = state_events
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_dir / f"{run_id}.jsonl"
        self.queue = queue

    def emit(self, kind: str, **payload: Any) -> dict[str, Any]:
        event: dict[str, Any] = {
            "kind": kind,
            "ts": datetime.now(UTC).isoformat(),
            **payload,
        }
        self.state_events.append(event)
        with self.log_path.open("a") as f:
            f.write(json.dumps(event, default=str) + "\n")
        if self.queue is not None:
            try:
                self.queue.put_nowait(event)
            except asyncio.QueueFull:
                _logger.warning(
                    "sse queue full; dropping event kind=%s run_id=%s",
                    kind, self.run_id,
                )
        return event
