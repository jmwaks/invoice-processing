from unittest.mock import MagicMock
from pydantic import BaseModel
from app.llm.grok_client import GrokClient


class Toy(BaseModel):
    a: int
    b: str


def test_grok_client_parses_structured_output():
    mock_sdk = MagicMock()
    mock_sdk.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content='{"a": 7, "b": "hi"}'))
    ]
    mock_sdk.chat.completions.create.return_value.usage = MagicMock(
        prompt_tokens=10, completion_tokens=5
    )
    client = GrokClient(model="grok-4", sdk=mock_sdk)
    parsed, meta = client.structured_complete(
        system="extract", user="data", schema=Toy
    )
    assert parsed == Toy(a=7, b="hi")
    assert meta.tokens_in == 10
    assert meta.tokens_out == 5
