from unittest.mock import MagicMock

import httpx
from openai import RateLimitError
from pydantic import BaseModel

from app.llm.grok_client import GrokClient


def _rate_limit_error(retry_after: str | None = None) -> RateLimitError:
    headers = {"retry-after": retry_after} if retry_after is not None else {}
    response = httpx.Response(
        429,
        headers=headers,
        request=httpx.Request("POST", "https://api.x.ai/v1/chat/completions"),
    )
    return RateLimitError(message="capacity exhausted", response=response, body=None)


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


def test_grok_client_retries_on_validation_error_then_succeeds():
    """First response is invalid JSON for schema; second is corrected — should return parsed."""
    mock_sdk = MagicMock()
    bad_resp = MagicMock()
    bad_resp.choices = [MagicMock(message=MagicMock(content='{"a": "not_an_int", "b": "hi"}'))]
    bad_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
    good_resp = MagicMock()
    good_resp.choices = [MagicMock(message=MagicMock(content='{"a": 7, "b": "hi"}'))]
    good_resp.usage = MagicMock(prompt_tokens=12, completion_tokens=6)
    mock_sdk.chat.completions.create.side_effect = [bad_resp, good_resp]

    client = GrokClient(model="grok-4", sdk=mock_sdk)
    parsed, meta = client.structured_complete(
        system="extract", user="data", schema=Toy, max_retries=1,
    )
    assert parsed == Toy(a=7, b="hi")
    assert mock_sdk.chat.completions.create.call_count == 2
    # On retry, an extra user message is appended noting the validation error.
    second_call_messages = mock_sdk.chat.completions.create.call_args_list[1].kwargs["messages"]
    assert len(second_call_messages) == 3
    assert "failed validation" in second_call_messages[2]["content"]


def test_grok_client_raises_when_retries_exhausted():
    """Both responses invalid — should raise ValidationError after max_retries."""
    import pytest
    from pydantic import ValidationError
    mock_sdk = MagicMock()
    bad_resp = MagicMock()
    bad_resp.choices = [MagicMock(message=MagicMock(content='{"a": "not_an_int", "b": "hi"}'))]
    bad_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
    mock_sdk.chat.completions.create.return_value = bad_resp

    client = GrokClient(model="grok-4", sdk=mock_sdk)
    with pytest.raises(ValidationError):
        client.structured_complete(
            system="extract", user="data", schema=Toy, max_retries=1,
        )
    assert mock_sdk.chat.completions.create.call_count == 2  # 1 initial + 1 retry


def test_retries_succeed_after_429(monkeypatch):
    """First grok-4 call raises 429, second returns valid JSON. Assert 2 SDK calls."""
    sleeps: list[float] = []
    monkeypatch.setattr("app.llm.grok_client.time.sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr("app.llm.grok_client.random.uniform", lambda a, b: (a + b) / 2)

    good_resp = MagicMock()
    good_resp.choices = [MagicMock(message=MagicMock(content='{"a": 7, "b": "hi"}'))]
    good_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)

    mock_sdk = MagicMock()
    mock_sdk.chat.completions.create.side_effect = [_rate_limit_error(), good_resp]

    client = GrokClient(model="grok-4", sdk=mock_sdk)
    parsed, _ = client.structured_complete(system="extract", user="data", schema=Toy)

    assert parsed == Toy(a=7, b="hi")
    assert mock_sdk.chat.completions.create.call_count == 2
    assert len(sleeps) == 1


def test_retries_honor_retry_after_header(monkeypatch):
    """RateLimitError with Retry-After: 2 should cause sleep of ~2s (not exponential backoff)."""
    sleeps: list[float] = []
    monkeypatch.setattr("app.llm.grok_client.time.sleep", lambda s: sleeps.append(s))
    # lambda returns 999.0 — would dominate exponential backoff if jitter path were taken
    monkeypatch.setattr("app.llm.grok_client.random.uniform", lambda a, b: 999.0)

    good_resp = MagicMock()
    good_resp.choices = [MagicMock(message=MagicMock(content='{"a": 1, "b": "x"}'))]
    good_resp.usage = MagicMock(prompt_tokens=1, completion_tokens=1)

    mock_sdk = MagicMock()
    mock_sdk.chat.completions.create.side_effect = [_rate_limit_error(retry_after="2"), good_resp]

    client = GrokClient(model="grok-4", sdk=mock_sdk)
    client.structured_complete(system="s", user="u", schema=Toy)

    assert sleeps == [2.0]  # exact header value used, jitter NOT applied
