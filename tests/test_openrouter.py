"""OpenRouter request contract and streaming regressions; no network needed."""

import json

import httpx
import pytest

from app.utils.adapters import get_adapter
from app.utils.adapters import openrouter as module
from app.utils.adapters.base import AgentConfig, Message, TextDelta, ToolDefinition, TurnComplete, UsageStats


@pytest.fixture
def adapter(monkeypatch):
    monkeypatch.setattr(module.settings, "openrouter_api_key", "test-key")
    return module.OpenRouterAdapter(AgentConfig(adapter="openrouter", model="openai/gpt-4o"))


def mock_api(monkeypatch, handler):
    client = httpx.AsyncClient
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda: client(transport=httpx.MockTransport(handler)))


def sse(*chunks):
    return httpx.Response(200, text=": OPENROUTER PROCESSING\n\n" + "".join(
        "data:" + (chunk if isinstance(chunk, str) else json.dumps(chunk)) + "\n\n"
        for chunk in chunks
    ), headers={"Content-Type": "text/event-stream"})


async def test_complete_request_and_registry(adapter, monkeypatch):
    def handler(request):
        assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-key"
        assert request.headers["Content-Type"] == "application/json"
        body = json.loads(request.content)
        assert body["model"] == "openai/gpt-4o"
        assert body["messages"] == [
            {"role": "system", "content": "Be concise."},
            {"role": "assistant", "content": "Hello"},
            {"role": "user", "content": "Meaning of life?"},
        ]
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "42"}}]})

    mock_api(monkeypatch, handler)
    assert isinstance(get_adapter(adapter._config), module.OpenRouterAdapter)
    assert await adapter.complete("Be concise.", "Meaning of life?", [Message("assistant", "Hello")]) == "42"


async def test_stream_handles_multiline_sse_and_done(adapter, monkeypatch):
    body = (
        ': comment\n\n'
        'data: {"choices":\n'
        'data: [{"delta":{"content":"Hello"}}]}\n\n'
        'data: {"choices":[{"delta":null,"finish_reason":"stop"}]}\n\n'
        'data: [DONE]\n\n'
        'data: invalid after DONE\n\n'
    )
    mock_api(monkeypatch, lambda _: httpx.Response(200, text=body))
    assert [part async for part in adapter.stream("", "hello")] == ["Hello"]


@pytest.mark.parametrize("method", ["stream", "stream_with_tools"])
@pytest.mark.parametrize("chunks,match", [
    ([{"error": {"message": "upstream failed"}}], "upstream failed"),
    ([{"choices": [{"delta": {"content": "partial"}}]}, "[DONE]"], "without a terminal event"),
    ([{"choices": [{"delta": {}, "finish_reason": "error"}]}], "Incomplete provider response"),
])
async def test_stream_failures(adapter, monkeypatch, method, chunks, match):
    mock_api(monkeypatch, lambda _: sse(*chunks))
    iterator = adapter.stream("", "hello") if method == "stream" else adapter.stream_with_tools("", [], [])
    with pytest.raises(RuntimeError, match=match):
        _ = [event async for event in iterator]


async def test_tool_round_trip_and_usage(adapter, monkeypatch):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return sse(
            {"choices": [{"delta": {"content": "Checking", "tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "lookup", "arguments": '{"q":'}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"test"}'}}]}, "finish_reason": "tool_calls"}]},
            {"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 20, "prompt_tokens_details": {"cached_tokens": 40, "cache_write_tokens": 10}}},
            "[DONE]",
        )

    mock_api(monkeypatch, handler)
    tools = [ToolDefinition(name="lookup", description="Look up a query", input_schema={"type": "object"})]
    events = [e async for e in adapter.stream_with_tools("system", [{"role": "user", "content": "hello"}], tools)]
    assert events[0] == TextDelta("Checking")
    usage = next(e for e in events if isinstance(e, UsageStats))
    assert (usage.input_tokens, usage.output_tokens, usage.cache_read_tokens, usage.cache_creation_tokens) == (100, 20, 40, 10)
    turn = events[-1]
    assert isinstance(turn, TurnComplete)
    assert turn.stop_reason == "tool_use"
    assert turn.tool_calls[0].input == {"q": "test"}
    history = [{"role": "assistant", "content": turn.assistant_content}, {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "found"}]}]
    _ = [e async for e in adapter.stream_with_tools("system", history, [])]
    assert requests[0]["tools"][0]["function"]["name"] == "lookup"
    assert "tools" not in requests[1]
    assert requests[1]["messages"][1]["tool_calls"][0]["id"] == "call_1"
    assert requests[1]["messages"][2] == {"role": "tool", "tool_call_id": "call_1", "content": "found"}


async def test_missing_key_fails_locally(adapter):
    adapter._api_key = ""
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        await adapter.complete("", "hello")


@pytest.mark.parametrize("status", [401, 402, 429, 503])
async def test_http_errors(adapter, monkeypatch, status):
    mock_api(monkeypatch, lambda _: httpx.Response(status, json={"error": {"message": "failed"}}))
    with pytest.raises(httpx.HTTPStatusError):
        await adapter.complete("", "hello")


async def test_complete_error_in_success_response(adapter, monkeypatch):
    mock_api(monkeypatch, lambda _: httpx.Response(200, json={"error": {"message": "upstream failed"}}))
    with pytest.raises(RuntimeError, match="upstream failed"):
        await adapter.complete("", "hello")


def test_dynamic_context_precedes_static_catalog(adapter, monkeypatch):
    monkeypatch.setattr(module, "_cached_models", [{"id": "openai/gpt-4o", "context_length": 256_000}])
    assert adapter.context_window_size() == 256_000
    monkeypatch.setattr(module, "_cached_models", [{"id": "openai/gpt-4o", "context_length": None}])
    assert adapter.context_window_size() == 128_000
