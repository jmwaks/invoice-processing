from __future__ import annotations
import asyncio
import json
from sse_starlette.sse import EventSourceResponse


async def event_stream(queue: asyncio.Queue):
    while True:
        event = await queue.get()
        yield {"data": json.dumps(event, default=str)}
        if event.get("kind") == "run.complete" or event.get("kind") == "run.error":
            break


def sse_response(queue: asyncio.Queue):
    return EventSourceResponse(event_stream(queue))
