from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Type, TypeVar
from pydantic import BaseModel
from app.llm.grok_client import CallMeta, GrokClient

T = TypeVar("T", bound=BaseModel)
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "grok"


def _key(system: str, user: str) -> str:
    h = hashlib.sha256()
    h.update(system.encode())
    h.update(b"|")
    h.update(user.encode())
    return h.hexdigest()[:16]


class MockGrokClient(GrokClient):
    """Returns recorded responses keyed by prompt hash."""

    def __init__(self) -> None:
        self.model = "grok-mock"

    def structured_complete(
        self, *, system: str, user: str, schema: Type[T], max_retries: int = 1,
    ) -> tuple[T, CallMeta]:
        key = _key(system, user)
        path = FIXTURES_DIR / f"{key}.json"
        if not path.exists():
            raise FileNotFoundError(
                f"No fixture for prompt hash {key}. Re-record with scripts/record_fixtures.py."
            )
        payload = json.loads(path.read_text())
        return (
            schema.model_validate(payload["response"]),
            CallMeta(tokens_in=payload.get("tokens_in", 0),
                     tokens_out=payload.get("tokens_out", 0),
                     latency_ms=payload.get("latency_ms", 0),
                     model="grok-mock"),
        )

    @staticmethod
    def record(system: str, user: str, response: BaseModel, *, tokens_in: int = 0, tokens_out: int = 0) -> Path:
        FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
        key = _key(system, user)
        path = FIXTURES_DIR / f"{key}.json"
        path.write_text(json.dumps({
            "system_preview": system[:200],
            "user_preview": user[:500],
            "response": response.model_dump(),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        }, indent=2))
        return path
