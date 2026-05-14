from unittest.mock import MagicMock

import httpx
import pytest
from openai import APIStatusError, RateLimitError
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


def _api_status_error(status_code: int) -> APIStatusError:
    response = httpx.Response(
        status_code,
        request=httpx.Request("POST", "https://api.x.ai/v1/chat/completions"),
    )
    return APIStatusError(message=f"http {status_code}", response=response, body=None)


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


def test_503_retries_then_raises_unavailable(monkeypatch):
    """All 3 grok-4 attempts return 503. Fallback disabled. Assert LLMUnavailableError."""
    monkeypatch.setattr("app.llm.grok_client.time.sleep", lambda s: None)
    monkeypatch.setattr("app.llm.grok_client.random.uniform", lambda a, b: 0.0)

    mock_sdk = MagicMock()
    mock_sdk.chat.completions.create.side_effect = [_api_status_error(503)] * 3

    from app.llm.grok_client import LLMUnavailableError
    client = GrokClient(model="grok-4", fallback_model="", sdk=mock_sdk)
    with pytest.raises(LLMUnavailableError):
        client.structured_complete(system="s", user="u", schema=Toy)
    assert mock_sdk.chat.completions.create.call_count == 3


def _api_status_subclass_error(cls_name: str, status_code: int) -> Exception:
    """Construct a real openai APIStatusError subclass for the given HTTP status."""
    import openai
    cls = getattr(openai, cls_name)
    response = httpx.Response(
        status_code,
        request=httpx.Request("POST", "https://api.x.ai/v1/chat/completions"),
    )
    return cls(message=f"http {status_code}", response=response, body=None)


def test_auth_error_raises_configuration_error_immediately(monkeypatch):
    """401 -> LLMConfigurationError immediately, no retry, no fallback."""
    monkeypatch.setattr("app.llm.grok_client.time.sleep", lambda s: None)

    mock_sdk = MagicMock()
    mock_sdk.chat.completions.create.side_effect = _api_status_subclass_error(
        "AuthenticationError", 401
    )

    from app.llm.grok_client import LLMConfigurationError
    client = GrokClient(model="grok-4", fallback_model="grok-3", sdk=mock_sdk)
    with pytest.raises(LLMConfigurationError) as exc_info:
        client.structured_complete(system="s", user="u", schema=Toy)

    assert "key" in exc_info.value.user_message.lower()
    assert mock_sdk.chat.completions.create.call_count == 1  # no retry, no fallback


def test_bad_request_re_raised_as_is(monkeypatch):
    """400 -> BadRequestError bubbles up unchanged. No retry."""
    from openai import BadRequestError
    monkeypatch.setattr("app.llm.grok_client.time.sleep", lambda s: None)

    mock_sdk = MagicMock()
    mock_sdk.chat.completions.create.side_effect = _api_status_subclass_error(
        "BadRequestError", 400
    )

    client = GrokClient(model="grok-4", fallback_model="grok-3", sdk=mock_sdk)
    with pytest.raises(BadRequestError):
        client.structured_complete(system="s", user="u", schema=Toy)
    assert mock_sdk.chat.completions.create.call_count == 1


def test_falls_back_to_grok3_after_exhaustion(monkeypatch):
    """3 RateLimitError on grok-4, then grok-3 succeeds. Assert 4th call uses grok-3 + date prefix.
    """
    monkeypatch.setattr("app.llm.grok_client.time.sleep", lambda s: None)
    monkeypatch.setattr("app.llm.grok_client.random.uniform", lambda a, b: 0.0)

    good_resp = MagicMock()
    good_resp.choices = [MagicMock(message=MagicMock(content='{"a": 9, "b": "ok"}'))]
    good_resp.usage = MagicMock(prompt_tokens=3, completion_tokens=2)

    mock_sdk = MagicMock()
    mock_sdk.chat.completions.create.side_effect = [
        _rate_limit_error(),
        _rate_limit_error(),
        _rate_limit_error(),
        good_resp,
    ]

    client = GrokClient(model="grok-4", fallback_model="grok-3", sdk=mock_sdk)
    parsed, meta = client.structured_complete(
        system="extract things", user="data", schema=Toy,
    )

    assert parsed == Toy(a=9, b="ok")
    assert mock_sdk.chat.completions.create.call_count == 4
    assert meta.model == "grok-3"

    fallback_call = mock_sdk.chat.completions.create.call_args_list[3]
    assert fallback_call.kwargs["model"] == "grok-3"
    system_msg = fallback_call.kwargs["messages"][0]["content"]
    assert system_msg.startswith("Today's date is ")
    assert "extract things" in system_msg


def test_fallback_disabled_raises_when_empty(monkeypatch):
    """Empty fallback_model means no grok-3 attempt; LLMUnavailableError after 3 grok-4 fails."""
    monkeypatch.setattr("app.llm.grok_client.time.sleep", lambda s: None)
    monkeypatch.setattr("app.llm.grok_client.random.uniform", lambda a, b: 0.0)

    mock_sdk = MagicMock()
    mock_sdk.chat.completions.create.side_effect = [_rate_limit_error()] * 3

    from app.llm.grok_client import LLMUnavailableError
    client = GrokClient(model="grok-4", fallback_model="", sdk=mock_sdk)
    with pytest.raises(LLMUnavailableError):
        client.structured_complete(system="s", user="u", schema=Toy)
    assert mock_sdk.chat.completions.create.call_count == 3


def test_total_attempt_budget_is_bounded(monkeypatch):
    """All 4 calls (3 grok-4 + 1 grok-3) raise 429. Assert exactly 4 SDK calls, LLMUnavailableError."""
    monkeypatch.setattr("app.llm.grok_client.time.sleep", lambda s: None)
    monkeypatch.setattr("app.llm.grok_client.random.uniform", lambda a, b: 0.0)

    mock_sdk = MagicMock()
    mock_sdk.chat.completions.create.side_effect = [_rate_limit_error()] * 10  # plenty

    from app.llm.grok_client import LLMUnavailableError
    client = GrokClient(model="grok-4", fallback_model="grok-3", sdk=mock_sdk)
    with pytest.raises(LLMUnavailableError):
        client.structured_complete(system="s", user="u", schema=Toy)
    assert mock_sdk.chat.completions.create.call_count == 4
