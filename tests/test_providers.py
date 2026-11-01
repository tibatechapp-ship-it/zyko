"""Provider adapters against canned HTTP payloads (no network involved)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from zyko.core.messages import Message
from zyko.core.response import ChatRequest
from zyko.exceptions import AuthError, ProviderError, RateLimitError
from zyko.providers.anthropic import AnthropicProvider
from zyko.providers.google import GoogleProvider
from zyko.providers.ollama import OllamaProvider
from zyko.providers.openai_compat import OpenAICompatProvider


def _request(**kw: Any) -> ChatRequest:
    return ChatRequest(messages=[Message.user("hi")], **kw)


async def _collect(agen) -> list[Any]:
    return [item async for item in agen]


# --------------------------------------------------------------------- openai
def test_openai_request_shape_and_parse():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={
            "id": "x1", "model": "gpt-4o-mini",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hello!"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 5},
        })

    provider = OpenAICompatProvider(api_key="sk-test", transport=httpx.MockTransport(handler))
    resp = provider.complete(_request(model="gpt-4o-mini", temperature=0.2))
    assert captured["url"].endswith("/chat/completions")
    assert captured["auth"] == "Bearer sk-test"
    assert captured["payload"]["model"] == "gpt-4o-mini"
    assert captured["payload"]["messages"][0]["role"] == "user"
    assert resp.text == "hello!"
    assert resp.usage.input_tokens == 12
    assert resp.provider == "openai"


def test_openai_tools_payload():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "x", "choices": [{"message": {"content": None,
            "tool_calls": [{"id": "c1", "type": "function",
                            "function": {"name": "calculator", "arguments": "{\"expression\": \"2+2\"}"}}],
            }, "finish_reason": "tool_calls"}], "usage": {}})

    provider = OpenAICompatProvider(api_key="k", transport=httpx.MockTransport(handler))
    request = _request(tools=[{"name": "calculator", "description": "calc", "parameters": {"type": "object", "properties": {}}}])
    resp = provider.complete(request)
    assert captured["payload"]["tools"][0]["type"] == "function"
    assert resp.tool_calls[0].name == "calculator"
    assert resp.tool_calls[0].arguments == {"expression": "2+2"}
    assert resp.finish_reason == "tool_calls"


async def test_openai_streaming_sse():
    sse = (
        b'data: {"choices":[{"delta":{"content":"hel"}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
        b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        b"data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})

    provider = OpenAICompatProvider(api_key="k", transport=httpx.MockTransport(handler))
    events = await _collect(provider.astream(_request()))
    assert "".join(e.data["text"] for e in events if e.type == "text") == "hello"
    assert events[-1].type == "done"


def test_http_error_mapping():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "slow down"})

    provider = OpenAICompatProvider(api_key="k", transport=httpx.MockTransport(handler), retries=0)
    with pytest.raises(RateLimitError):
        provider.complete(_request())

    def handler401(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    provider401 = OpenAICompatProvider(api_key="bad", transport=httpx.MockTransport(handler401))
    with pytest.raises(AuthError):
        provider401.complete(_request())


def test_provider_404_is_not_retryable_but_raises_provider_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "no model"})

    provider = OpenAICompatProvider(api_key="k", transport=httpx.MockTransport(handler), retries=0)
    with pytest.raises(ProviderError) as e:
        provider.complete(_request())
    assert e.value.status == 404
    assert e.value.retryable is False


# ------------------------------------------------------------------ anthropic
def test_anthropic_build_and_parse():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={
            "id": "msg_1", "model": "claude-sonnet-4-20250514",
            "content": [{"type": "text", "text": "answer"}, {"type": "tool_use", "id": "tu1", "name": "t", "input": {"a": 1}}],
            "stop_reason": "tool_use", "usage": {"input_tokens": 9, "output_tokens": 4},
        })

    provider = AnthropicProvider(api_key="ak", transport=httpx.MockTransport(handler))
    request = ChatRequest(
        messages=[Message.system("be nice"), Message.user("hi"), Message.tool_result("tu0", "t", "prev")],
        max_tokens=123,
    )
    resp = provider.complete(request)
    assert captured["url"].endswith("/messages")
    assert captured["headers"]["x-api-key"] == "ak"
    assert captured["payload"]["system"] == "be nice"
    assert captured["payload"]["max_tokens"] == 123
    assert captured["payload"]["messages"][-1]["content"][0]["type"] == "tool_result"
    assert resp.finish_reason == "tool_calls"
    assert resp.tool_calls[0].name == "t"
    assert resp.usage.output_tokens == 4


async def test_anthropic_stream_tool_accumulation():
    sse = (
        b'event: message_start\ndata: {"type":"message_start","message":{"usage":{"input_tokens":5}}}\n\n'
        b'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":"tu1","name":"calc"}}\n\n'
        b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":"{\\"x\\":"}}\n\n'
        b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":"1}"}}\n\n'
        b'event: message_delta\ndata: {"type":"message_delta","usage":{"output_tokens":7}}\n\n'
        b'event: message_stop\ndata: {"type":"message_stop"}\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse)

    provider = AnthropicProvider(api_key="k", transport=httpx.MockTransport(handler))
    text, tools, usage = await _collect_result(provider, _request())
    assert text == ""
    assert len(tools) == 1
    assert tools[0]["name"] == "calc"
    assert json.loads(tools[0]["arguments"]) == {"x": 1}
    assert usage["output_tokens"] == 7


async def _collect_result(provider, request):
    from zyko.core.events import accumulate_stream

    return await accumulate_stream(provider.astream(request))


# --------------------------------------------------------------------- google
def test_google_build_and_parse():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["key"] = request.headers.get("x-goog-api-key")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={
            "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "g'day"}]}}],
            "usageMetadata": {"promptTokenCount": 8, "candidatesTokenCount": 3},
        })

    provider = GoogleProvider(api_key="gk", transport=httpx.MockTransport(handler))
    request = ChatRequest(messages=[Message.system("s"), Message.user("hi")], temperature=0.1)
    resp = provider.complete(request)
    assert ":generateContent" in captured["url"]
    assert captured["key"] == "gk"
    assert captured["payload"]["systemInstruction"]["parts"][0]["text"] == "s"
    assert "temperature" in captured["payload"]["generationConfig"]
    assert resp.text == "g'day"
    assert resp.usage.input_tokens == 8


def test_google_function_call_parse():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "candidates": [{"finishReason": "STOP", "content": {"parts": [
                {"functionCall": {"name": "find", "args": {"q": "x"}}}]}}]})

    provider = GoogleProvider(api_key="k", transport=httpx.MockTransport(handler))
    resp = provider.complete(_request())
    assert resp.tool_calls[0].name == "find"
    assert resp.tool_calls[0].arguments == {"q": "x"}


# --------------------------------------------------------------------- ollama
def test_ollama_native_chat_and_tools():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={
            "model": "llama3.2",
            "message": {"role": "assistant", "content": "local answer",
                        "tool_calls": [{"function": {"name": "calc", "arguments": {"expression": "1+1"}}}]},
            "prompt_eval_count": 15, "eval_count": 6, "done": True,
        })

    provider = OllamaProvider(transport=httpx.MockTransport(handler))
    resp = provider.complete(_request(model="llama3.2"))
    assert "/api/chat" in captured["url"]
    assert "Authorization" not in {k for k in captured["payload"]}
    assert resp.text == "local answer"
    assert resp.tool_calls[0].arguments == {"expression": "1+1"}
    assert resp.usage.input_tokens == 15


async def test_ollama_ndjson_stream():
    nd = (
        b'{"message":{"content":"par"}}\n'
        b'{"message":{"content":"tial"}}\n'
        b'{"done":true,"prompt_eval_count":5,"eval_count":2}\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=nd)

    provider = OllamaProvider(transport=httpx.MockTransport(handler))
    events = await _collect(provider.astream(_request()))
    text = "".join(e.data["text"] for e in events if e.type == "text")
    assert text == "partial"
    usage_events = [e for e in events if e.type == "usage"]
    assert usage_events and usage_events[0].data["usage"]["eval_count"] == 2
