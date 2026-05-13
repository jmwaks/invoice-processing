from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
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


class ConsoleEmitter(EventEmitter):
    """EventEmitter that also prints human-readable progress to stderr.

    Used by the CLI so 60-90s LLM runs are not silent. Per-node wall-clock
    is tracked between node.start and node.complete and printed alongside
    the completion line.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._node_starts: dict[str, float] = {}

    def emit(self, kind: str, **payload: Any) -> dict[str, Any]:
        event = super().emit(kind, **payload)
        line = self._format(event)
        if line is not None:
            print(line, file=sys.stderr, flush=True)
        return event

    def _format(self, event: dict[str, Any]) -> str | None:
        kind = event["kind"]
        node = event.get("node", "")
        if kind == "node.start":
            self._node_starts[node] = perf_counter()
            return f"[{node}] start"
        if kind == "node.complete":
            elapsed = perf_counter() - self._node_starts.pop(node, perf_counter())
            out = event.get("output") or {}
            extra = self._compact(out)
            return f"[{node}] complete {elapsed:.1f}s {extra}".rstrip()
        if kind == "ingest.skipped":
            return "[ingest]   (skipped — invoice pre-seeded by retry)"
        if kind == "approve.investigate.start":
            return "[approve]   investigate"
        if kind == "approve.investigate.complete":
            count = (event.get("output") or {}).get("tool_call_count")
            return f"[approve]   investigate done ({count} tool calls)" if count is not None else None
        if kind == "tool.call":
            tool = event.get("tool", "?")
            args = self._compact(event.get("arguments") or {})
            return f"[approve]     tool: {tool}({args})"
        if kind == "approve.propose.start":
            return "[approve]   propose"
        if kind == "approve.critique.start":
            return "[approve]   critique"
        if kind == "approve.finalize.start":
            return "[approve]   finalize"
        if kind == "approve.decision":
            outcome = (event.get("output") or {}).get("outcome", "?")
            return f"[approve]   decision: {outcome}"
        if kind == "llm.call":
            sub = event.get("sub")
            tag = f" ({sub})" if sub else ""
            latency = event.get("latency_ms", 0)
            tokens = event.get("tokens_out", 0)
            return f"[{node}]    llm{tag} {latency}ms, {tokens} tokens out"
        if kind == "run.error":
            return f"[error] {event.get('error', 'unknown')}"
        return None

    @staticmethod
    def _compact(d: dict[str, Any]) -> str:
        """Render a small dict as key=value pairs, truncated for stderr."""
        if not d:
            return ""
        pairs = [f"{k}={d[k]!r}" if not isinstance(d[k], str) else f"{k}={d[k]}"
                 for k in list(d)[:4]]
        s = " ".join(pairs)
        return s[:120] + ("…" if len(s) > 120 else "")
